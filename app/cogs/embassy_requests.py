from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from app.services.requests import EmbassyRequestService
from app.cogs.dashboards import EmbassyManagementView, ForeignDiplomatView
from verification.warera_http import WarEraAPIError

logger = logging.getLogger(__name__)


class WarEraProfileModal(discord.ui.Modal, title="Embassy Verification"):
    profile = discord.ui.TextInput(label="WarEra Profile Link or ID", placeholder="https://warera.io/profile/... or your WarEra User ID", min_length=1, max_length=200, required=True)

    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=300)
        self.service = service

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This application can only be started inside the India server.", ephemeral=True)
            return
        parent = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message("The Embassy request channel is not configured as a text channel. Please contact an administrator.", ephemeral=True)
            return
        try:
            request_id, thread, created = await self.service.create_private_request(channel=parent, applicant=interaction.user)
            if not created:
                await interaction.response.send_message(f"You already have an active Embassy request: {thread.mention}", ephemeral=True)
                return
            await self.service.database.collection("requests").update_one({"request_id": request_id}, {"$set": {"profile_input": self.profile.value.strip()}})
            await interaction.response.send_message(f"Your private Embassy request has been created: {thread.mention}", ephemeral=True)
            await thread.send(
                embed=discord.Embed(
                    title="🇮🇳 Embassy Access Request",
                    description=("Your request has been created successfully.\n\n**WarEra Profile:**\n" f"`{self.profile.value.strip()}`\n\n" "Click **Continue Verification** to resolve your WarEra identity and begin OTP verification."),
                    color=discord.Color.dark_red(),
                ),
                view=VerificationStartView(self.service),
            )
        except discord.Forbidden:
            message = "I cannot create the private request thread. Please contact an administrator."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("Discord API failure while creating embassy request")
            message = "Discord returned an error while creating your request. Please try again later."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)


class RequestPanelView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label="Request Embassy Access", style=discord.ButtonStyle.primary, emoji="🏛️", custom_id="embassy:request-access")
    async def request_access(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(WarEraProfileModal(self.service))


class OTPSubmitModal(discord.ui.Modal, title="Embassy OTP Verification"):
    otp = discord.ui.TextInput(label="Company OTP", placeholder="Enter the exact OTP company name", min_length=1, max_length=100, required=True)

    def __init__(self, service: EmbassyRequestService, request_id: str) -> None:
        super().__init__(timeout=300)
        self.service = service
        self.request_id = request_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This verification must be completed inside your request thread.", ephemeral=True)
            return
        request = await self.service.database.collection("requests").find_one({"request_id": self.request_id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("This verification request is not assigned to you.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        complete_cog = interaction.client.get_cog("CompleteEmbassyCog")
        if complete_cog is None:
            await interaction.followup.send("The verification service is temporarily unavailable. Please try again later.", ephemeral=True)
            return
        try:
            verified, attempts, lock_until = await complete_cog.verification.verify_company_otp(self.request_id, self.otp.value, interaction.user.id)
        except WarEraAPIError:
            logger.exception("WarEra API error during OTP verification for %s", self.request_id)
            await interaction.followup.send("WarEra could not be checked right now. Please try again later.", ephemeral=True)
            return
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if verified:
            await self.service.database.collection("requests").update_one({"request_id": self.request_id}, {"$set": {"status": "VERIFIED", "active": True}})
            await interaction.followup.send("✅ OTP verified successfully. Your WarEra identity and company ownership have been verified.", ephemeral=True)
            await interaction.channel.send(embed=discord.Embed(title="✅ WarEra Verification Complete", description="Your WarEra identity and company ownership have been verified.\n\nYour request can now proceed to embassy access review.", color=discord.Color.green()))
            return
        if lock_until and attempts >= 5:
            message = "🔒 Verification is temporarily locked after 5 failed attempts. Please use Retry Verification after the cooldown."
        else:
            message = f"❌ Verification failed. Attempt {attempts}/5."
        await interaction.followup.send(message, ephemeral=True)


class OTPSubmitView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService, request_id: str) -> None:
        super().__init__(timeout=None)
        self.service = service
        self.request_id = request_id

    @discord.ui.button(label="Submit OTP", style=discord.ButtonStyle.primary, emoji="🔑", custom_id="embassy:submit-otp")
    async def submit_otp(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        request = await self.service.database.collection("requests").find_one({"request_id": self.request_id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can submit this OTP.", ephemeral=True)
            return
        await interaction.response.send_modal(OTPSubmitModal(self.service, self.request_id))


class VerificationStartView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label="Continue Verification", style=discord.ButtonStyle.success, emoji="🔐", custom_id="embassy:continue-verification")
    async def continue_verification(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("This verification control must be used inside your request thread.", ephemeral=True)
            return
        request = await self.service.database.collection("requests").find_one({"thread_id": interaction.channel.id})
        if not request:
            await interaction.response.send_message("This request could not be found. Please contact an administrator.", ephemeral=True)
            return
        if request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can continue this verification.", ephemeral=True)
            return
        if request.get("state") == "VERIFIED":
            await interaction.response.send_message("This request has already been verified.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        complete_cog = interaction.client.get_cog("CompleteEmbassyCog")
        if complete_cog is None:
            await interaction.followup.send("The verification service is temporarily unavailable. Please try again later.", ephemeral=True)
            return
        try:
            profile_input = str(request.get("profile_input") or "").strip()
            if not profile_input:
                await interaction.followup.send("No WarEra profile was captured for this request. Please restart the request.", ephemeral=True)
                return
            profile = await complete_cog.verification.resolve_profile(request["request_id"], profile_input, interaction.user.id)
            otp = await complete_cog.verification.issue_company_otp(request["request_id"], interaction.user.id)
        except WarEraAPIError:
            logger.exception("WarEra API error while resolving embassy profile %s", request.get("request_id"))
            await interaction.followup.send("I could not resolve that WarEra profile. Please check the ID/link and try again.", ephemeral=True)
            return
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logger.exception("Unexpected verification error for %s", request.get("request_id"))
            await interaction.followup.send("An unexpected error occurred while starting verification. Please try again later.", ephemeral=True)
            return
        official_flags = []
        if profile.is_president:
            official_flags.append("President")
        if profile.is_vice_president:
            official_flags.append("Vice President")
        if profile.is_eam_or_mofa:
            official_flags.append("EAM / Foreign Affairs")
        official_text = ", ".join(official_flags) if official_flags else "None detected"
        embed = discord.Embed(
            title="🔐 WarEra Company Verification",
            description=(
                "Your WarEra identity has been resolved. Now create or rename one of your **owned companies** so its exact name matches the OTP below.\n\n"
                f"**Player:** {profile.username}\n**Country:** {profile.country_name}\n**Official status:** {official_text}\n\n"
                f"**Your OTP:** `{otp}`\n\n"
                "Once the company name matches the OTP, click **Submit OTP**. The bot will discover your company IDs with `company.getCompanies` and resolve every company through `company.getById` before accepting the match."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.channel.send(embed=embed, view=OTPSubmitView(self.service, request["request_id"]))
        await interaction.followup.send("Your WarEra profile was resolved and an OTP was issued. Follow the instructions in this request thread.", ephemeral=True)


class EmbassyRequestsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = EmbassyRequestService(bot.database)

    async def cog_load(self) -> None:
        self.bot.add_view(RequestPanelView(self.service))
        self.bot.add_view(VerificationStartView(self.service))
        self.bot.add_view(EmbassyManagementView(self.bot, timeout=None))
        self.bot.add_view(ForeignDiplomatView(self.bot, timeout=None))

    @app_commands.command(name="embassy-setup", description="Install or refresh the Embassy request panel.")
    async def embassy_setup(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is guild-only.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You need Manage Server to run this setup command.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("CHANNEL_REQUEST_PARENT_ID must point to a normal text channel.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await channel.send(embed=discord.Embed(title="🇮🇳 Embassy Access System", description="Need access to an Embassy? Click the button below to begin.\n\nYou will first provide your **WarEra profile link or ID**. The bot will then create a private request thread for the verification process.", color=discord.Color.dark_red()), view=RequestPanelView(self.service))
            await interaction.followup.send("Embassy request panel installed.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("I cannot send the Embassy request panel in that channel. Check View Channel and Send Messages permissions.", ephemeral=True)
        except discord.HTTPException:
            logger.exception("Discord API failure while installing Embassy request panel")
            await interaction.followup.send("Discord returned an error while installing the Embassy request panel. Please check the bot permissions and try again.", ephemeral=True)

    @app_commands.command(name="embassy-dashboard", description="Open the Embassy Management Dashboard.")
    async def embassy_dashboard(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return
        allowed_roles = {settings.role_president_id, settings.role_vice_president_id, settings.role_nsa_id, settings.role_minister_id}
        if not member.guild_permissions.administrator and not any(r.id in allowed_roles for r in member.roles):
            await interaction.response.send_message("You are not authorized to use this dashboard.", ephemeral=True)
            return
        embed = discord.Embed(title="🏛️ Embassy Management", description="Central management for requests, Ambassadors, Foreign Diplomats, embassies, access, migration and maintenance.", color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, view=EmbassyManagementView(self.bot, timeout=None))

    @app_commands.command(name="foreign-diplomat-dashboard", description="Open the Foreign Diplomat Dashboard.")
    async def foreign_diplomat_dashboard(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not any(r.id == settings.role_foreign_diplomat_id for r in member.roles):
            await interaction.response.send_message("You need the Foreign Diplomat role to use this dashboard.", ephemeral=True)
            return
        embed = discord.Embed(title="🌍 Foreign Diplomat Portal", description="Manage only your assigned embassies, create pre-approvals for those embassies, and review your activity.", color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, view=ForeignDiplomatView(self.bot, timeout=None), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbassyRequestsCog(bot))
