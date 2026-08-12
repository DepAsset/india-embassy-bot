import secrets
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from .config import settings
from .db import Database
from .warera import WarEraClient


MAX_OTP_ATTEMPTS = 5
OTP_TTL_MINUTES = 20


def make_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def privileged(member: discord.Member) -> bool:
    ids = {
        settings.role_president_id,
        settings.role_vice_president_id,
        settings.role_nsa_id,
        settings.role_minister_id,
        settings.role_eam_id,
        settings.role_foreign_secretary_id,
        settings.role_ambassador_id,
    }
    return any(role.id in ids for role in member.roles)


class EmbassyView(discord.ui.View):
    def __init__(self, cog: "EmbassyCog", request_id: str):
        super().__init__(timeout=1800)
        self.cog = cog
        self.request_id = request_id

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="embassy:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not privileged(interaction.user):
            await interaction.response.send_message("You are not authorized to approve embassy requests.", ephemeral=True)
            return
        await self.cog.finalize_request(interaction, self.request_id, approved=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="embassy:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not privileged(interaction.user):
            await interaction.response.send_message("You are not authorized to reject embassy requests.", ephemeral=True)
            return
        await self.cog.finalize_request(interaction, self.request_id, approved=False)


class EmbassyCog(commands.Cog):
    embassy = app_commands.Group(name="embassy", description="India Embassy verification and management")

    def __init__(self, bot: commands.Bot, db: Database, warera: WarEraClient):
        self.bot = bot
        self.db = db
        self.warera = warera

    @embassy.command(name="start", description="Start foreign diplomat verification")
    @app_commands.describe(warera_user_id="Your WarEra user ID")
    async def start(self, interaction: discord.Interaction, warera_user_id: str):
        await interaction.response.defer(ephemeral=True)
        existing = await self.db.requests.find_one({"discord_user_id": interaction.user.id, "status": {"$in": ["pending_otp", "pending_country", "pending_approval"]}})
        if existing:
            await interaction.followup.send("You already have an embassy verification request in progress.", ephemeral=True)
            return

        try:
            profile = await self.warera.get_profile(warera_user_id)
        except NotImplementedError:
            await interaction.followup.send("The WarEra API adapter still needs its exact endpoint configuration. I have not guessed the endpoint.", ephemeral=True)
            return
        except Exception as exc:
            await interaction.followup.send(f"WarEra verification failed: `{type(exc).__name__}`. Please try again later.", ephemeral=True)
            return

        otp = make_otp()
        now = datetime.now(timezone.utc)
        doc = {
            "discord_user_id": interaction.user.id,
            "warera_user_id": profile.user_id,
            "warera_username": profile.username,
            "country": profile.country,
            "country_code": profile.country_code,
            "otp": otp,
            "otp_attempts": 0,
            "otp_expires_at": now + timedelta(minutes=OTP_TTL_MINUTES),
            "status": "pending_otp",
            "created_at": now,
            "updated_at": now,
        }
        result = await self.db.requests.insert_one(doc)
        await self.db.audit_event("verification_started", interaction.user.id, interaction.user.id, {"request_id": str(result.inserted_id), "warera_user_id": profile.user_id})

        await interaction.followup.send(
            f"**WarEra ownership verification**\n\n"
            f"WarEra account: **{profile.username}**\n"
            f"Country: **{profile.country or 'Unknown'}**\n\n"
            f"Temporarily rename your WarEra company to: **`{otp}`**\n"
            f"Then use `/embassy otp` with the same code.\n\n"
            f"You have **{MAX_OTP_ATTEMPTS} attempts** and the code expires in {OTP_TTL_MINUTES} minutes.",
            ephemeral=True,
        )

    @embassy.command(name="otp", description="Submit your WarEra ownership OTP")
    @app_commands.describe(code="The 6-digit OTP shown by the bot")
    async def otp(self, interaction: discord.Interaction, code: str):
        await interaction.response.defer(ephemeral=True)
        request = await self.db.requests.find_one({"discord_user_id": interaction.user.id, "status": "pending_otp"}, sort=[("created_at", -1)])
        if not request:
            await interaction.followup.send("No pending OTP verification was found.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        if request["otp_expires_at"] < now:
            await self.db.requests.update_one({"_id": request["_id"]}, {"$set": {"status": "expired", "updated_at": now}})
            await interaction.followup.send("That OTP has expired. Start a new verification request.", ephemeral=True)
            return
        if request["otp_attempts"] >= MAX_OTP_ATTEMPTS:
            await interaction.followup.send("Maximum OTP attempts reached. Start a new verification request.", ephemeral=True)
            return

        if code != request["otp"]:
            await self.db.requests.update_one({"_id": request["_id"]}, {"$inc": {"otp_attempts": 1}, "$set": {"updated_at": now}})
            remaining = MAX_OTP_ATTEMPTS - request["otp_attempts"] - 1
            await interaction.followup.send(f"OTP verification failed. Attempts remaining: **{remaining}**.", ephemeral=True)
            return

        try:
            verified = await self.warera.verify_company_rename_otp(request["warera_user_id"], request["otp"])
        except NotImplementedError:
            await interaction.followup.send("The WarEra ownership-verification endpoint still needs to be connected.", ephemeral=True)
            return
        except Exception as exc:
            await interaction.followup.send(f"WarEra ownership verification failed: `{type(exc).__name__}`.", ephemeral=True)
            return

        if not verified:
            await interaction.followup.send("WarEra could not confirm ownership. Make sure the company name is exactly the OTP.", ephemeral=True)
            return

        await self.db.requests.update_one({"_id": request["_id"]}, {"$set": {"status": "pending_country", "ownership_verified": True, "updated_at": now}})
        await self.db.audit_event("ownership_verified", interaction.user.id, interaction.user.id, {"request_id": str(request["_id"]), "warera_user_id": request["warera_user_id"]})

        view = CountryTypeView(self, str(request["_id"]))
        await interaction.followup.send("Ownership verified. Choose which diplomatic representation you are requesting.", view=view, ephemeral=True)

    @embassy.command(name="status", description="Show your current embassy verification status")
    async def status(self, interaction: discord.Interaction):
        request = await self.db.requests.find_one({"discord_user_id": interaction.user.id}, sort=[("created_at", -1)])
        if not request:
            await interaction.response.send_message("No embassy verification request found.", ephemeral=True)
            return
        await interaction.response.send_message(f"Current status: **{request.get('status', 'unknown')}**", ephemeral=True)

    @embassy.command(name="preapprove", description="Pre-approve a user to bypass manual embassy approval")
    @app_commands.describe(user="Discord user to pre-approve")
    async def preapprove(self, interaction: discord.Interaction, user: discord.Member):
        if not privileged(interaction.user):
            await interaction.response.send_message("You are not authorized to pre-approve diplomats.", ephemeral=True)
            return
        await self.db.requests.update_one({"discord_user_id": user.id}, {"$set": {"preapproved": True}}, upsert=True)
        await self.db.audit_event("preapproved", interaction.user.id, user.id)
        await interaction.response.send_message(f"{user.mention} is now pre-approved for embassy requests.", ephemeral=True)

    @embassy.command(name="revoke", description="Revoke embassy access from a user")
    @app_commands.describe(user="Diplomat whose access should be revoked")
    async def revoke(self, interaction: discord.Interaction, user: discord.Member):
        if not privileged(interaction.user):
            await interaction.response.send_message("You are not authorized to revoke embassy access.", ephemeral=True)
            return
        channels = await self.db.embassies.find({"active_diplomats": user.id}).to_list(length=100)
        for embassy in channels:
            channel = interaction.guild.get_channel(embassy["channel_id"])
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(user, view_channel=False, send_messages=False, read_message_history=False)
            await self.db.embassies.update_one({"_id": embassy["_id"]}, {"$pull": {"active_diplomats": user.id}})
        await self.db.audit_event("access_revoked", interaction.user.id, user.id)
        await interaction.response.send_message(f"Embassy access revoked for {user.mention}.", ephemeral=True)

    async def process_country_choice(self, interaction: discord.Interaction, request_id: str, representation: str):
        from bson import ObjectId
        request = await self.db.requests.find_one({"_id": ObjectId(request_id)})
        if not request:
            await interaction.response.send_message("Verification request not found.", ephemeral=True)
            return
        now = datetime.now(timezone.utc)
        await self.db.requests.update_one({"_id": request["_id"]}, {"$set": {"representation": representation, "status": "pending_approval", "updated_at": now}})

        embassy = None
        if request.get("country_code"):
            embassy = await self.db.embassies.find_one({"country_code": request["country_code"]})

        if request.get("preapproved"):
            await interaction.response.send_message("Your request is pre-approved. Finalizing embassy access...", ephemeral=True)
            await self._grant_existing_or_create(interaction, request, embassy)
            return

        if embassy and embassy.get("active_diplomats"):
            channel = interaction.guild.get_channel(embassy["channel_id"])
            if isinstance(channel, discord.TextChannel):
                await channel.send(f"New embassy access request from <@{request['discord_user_id']}>.", view=EmbassyView(self, request_id))
            await interaction.response.send_message("Your request has been sent to the active embassy diplomats for approval.", ephemeral=True)
            await self.db.audit_event("approval_requested", interaction.user.id, interaction.user.id, {"request_id": request_id, "channel_id": embassy.get("channel_id")})
            return

        management = interaction.guild.get_channel(settings.channel_embassy_management_id)
        if isinstance(management, discord.TextChannel):
            await management.send(f"Embassy administration review required for <@{request['discord_user_id']}>. No active diplomat currently controls this embassy.", view=EmbassyView(self, request_id))
        await interaction.response.send_message("Your request has been sent to Embassy Administration for review.", ephemeral=True)

    async def finalize_request(self, interaction: discord.Interaction, request_id: str, approved: bool):
        from bson import ObjectId
        request = await self.db.requests.find_one({"_id": ObjectId(request_id)})
        if not request:
            await interaction.response.send_message("Request no longer exists.", ephemeral=True)
            return
        if not approved:
            await self.db.requests.update_one({"_id": request["_id"]}, {"$set": {"status": "rejected", "rejected_by": interaction.user.id, "updated_at": datetime.now(timezone.utc)}})
            await self.db.audit_event("request_rejected", interaction.user.id, request["discord_user_id"], {"request_id": request_id})
            await interaction.response.send_message("Request rejected.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        embassy = await self.db.embassies.find_one({"country_code": request.get("country_code")}) if request.get("country_code") else None
        await self._grant_existing_or_create(interaction, request, embassy)

    async def _grant_existing_or_create(self, interaction: discord.Interaction, request: dict, embassy: dict | None):
        guild = interaction.guild
        member = guild.get_member(request["discord_user_id"])
        if not member:
            await interaction.followup.send("Applicant is no longer in the server.", ephemeral=True)
            return

        diplomat_role = guild.get_role(settings.role_foreign_diplomat_id)
        if diplomat_role and diplomat_role not in member.roles:
            await member.add_roles(diplomat_role, reason="Embassy verification approved")

        if embassy:
            channel = guild.get_channel(embassy["channel_id"])
            if isinstance(channel, discord.TextChannel):
                await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
                await self.db.embassies.update_one({"_id": embassy["_id"]}, {"$addToSet": {"active_diplomats": member.id}})
                await self.db.requests.update_one({"_id": request["_id"]}, {"$set": {"status": "approved", "channel_id": channel.id, "updated_at": datetime.now(timezone.utc)}})
                await self.db.audit_event("embassy_access_granted", interaction.user.id, member.id, {"channel_id": channel.id, "request_id": str(request["_id"])})
                await interaction.followup.send(f"Approved. {member.mention} now has access to {channel.mention}.", ephemeral=True)
                return

        category_id = settings.category_embassy_1_id if guild.get_channel(settings.category_embassy_1_id) else settings.category_embassy_2_id
        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("Embassy category is not configured correctly.", ephemeral=True)
            return

        name = (request.get("country") or request.get("country_code") or "embassy").lower().replace(" ", "-")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        for role_id in (settings.role_president_id, settings.role_vice_president_id, settings.role_nsa_id, settings.role_minister_id, settings.role_eam_id, settings.role_foreign_secretary_id, settings.role_ambassador_id):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel = await guild.create_text_channel(name=f"embassy-{name}"[:95], category=category, overwrites=overwrites, reason="Create embassy through Embassy Bot")
        embassy_doc = {
            "country": request.get("country"),
            "country_code": request.get("country_code"),
            "channel_id": channel.id,
            "active_diplomats": [member.id],
            "created_at": datetime.now(timezone.utc),
            "created_by": interaction.user.id,
        }
        await self.db.embassies.update_one({"country_code": request.get("country_code")}, {"$set": embassy_doc}, upsert=True)
        await self.db.requests.update_one({"_id": request["_id"]}, {"$set": {"status": "approved", "channel_id": channel.id, "updated_at": datetime.now(timezone.utc)}})
        await self.db.audit_event("embassy_created_and_access_granted", interaction.user.id, member.id, {"channel_id": channel.id, "request_id": str(request["_id"])})
        await interaction.followup.send(f"Approved. Created {channel.mention} and granted access to {member.mention}.", ephemeral=True)


class CountryTypeView(discord.ui.View):
    def __init__(self, cog: EmbassyCog, request_id: str):
        super().__init__(timeout=900)
        self.cog = cog
        self.request_id = request_id

    @discord.ui.button(label="My own country", style=discord.ButtonStyle.primary)
    async def own(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.process_country_choice(interaction, self.request_id, "own_country")

    @discord.ui.button(label="Another country", style=discord.ButtonStyle.secondary)
    async def other(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.process_country_choice(interaction, self.request_id, "other_country")
