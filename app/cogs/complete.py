from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from access.models import AccessSource, AssignmentType
from access.projector import AccessProjector
from access.service import AccessService
from approval.workflow import ApprovalWorkflow, Decision, Route
from app.config import settings
from core.audit import AuditLogger
from core.state import RequestState
from embassy.manager import EmbassyManager
from embassy.registry import EmbassyRegistry
from migration.manager import MigrationManager
from verification.flow import VerificationFlow
from verification.warera_http import WarEraHTTPClient, WarEraAPIError

logger = logging.getLogger(__name__)


GOVERNMENT_ROLE_IDS = {
    settings.role_president_id,
    settings.role_vice_president_id,
    settings.role_nsa_id,
    settings.role_minister_id,
}


def is_government(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id in GOVERNMENT_ROLE_IDS for r in member.roles)


def embassy_category(guild: discord.Guild, category_id: int) -> discord.CategoryChannel:
    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        raise ValueError("Configured Embassy category is invalid")
    return category


class ProfileModal(discord.ui.Modal, title="Embassy Access Request"):
    profile = discord.ui.TextInput(label="WarEra Profile Link or ID", max_length=200, required=True)

    def __init__(self, cog: "CompleteEmbassyCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This can only be used in the India server.", ephemeral=True)
            return
        try:
            request = await self.cog.requests.find_one({"discord_user_id": interaction.user.id, "state": {"$nin": [RequestState.APPROVED.value, RequestState.DECLINED.value, RequestState.CLOSED.value]}})
            if request:
                thread = interaction.guild.get_thread(request.get("thread_id", 0))
                if thread:
                    await interaction.response.send_message(f"You already have an active request: {thread.mention}", ephemeral=True)
                    return
            request_id = await self.cog.create_request(interaction.guild, interaction.user, self.profile.value.strip())
            await interaction.response.send_message(f"Your Embassy request has been created. Request ID: `{request_id}`", ephemeral=True)
        except Exception:
            logger.exception("Failed to create Embassy request")
            await interaction.response.send_message("The request could not be created. Please contact Embassy Administration.", ephemeral=True)


class OTPModal(discord.ui.Modal, title="WarEra OTP Verification"):
    otp = discord.ui.TextInput(label="OTP shown in your verification instructions", min_length=6, max_length=12, required=True)

    def __init__(self, cog: "CompleteEmbassyCog", request_id: str) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.request_id = request_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Guild-only action.", ephemeral=True)
            return
        try:
            ok, attempts, lock_until = await self.cog.verification.verify_company_otp(self.request_id, self.otp.value, interaction.user.id)
            if ok:
                await interaction.response.send_message("OTP verified. Choose the Embassy you represent using the button below.", ephemeral=True)
                await self.cog.send_embassy_selector(interaction.user, self.request_id)
            elif lock_until:
                await interaction.response.send_message(f"Verification locked after {attempts} failed attempts. Try again after {lock_until:%H:%M UTC}.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Incorrect OTP/company verification. Attempt {attempts}/5.", ephemeral=True)
        except Exception:
            logger.exception("OTP verification failed")
            await interaction.response.send_message("Verification could not be completed right now.", ephemeral=True)


class EmbassySelect(discord.ui.Select):
    def __init__(self, cog: "CompleteEmbassyCog", request_id: str, embassies: list) -> None:
        self.cog = cog
        self.request_id = request_id
        options = [discord.SelectOption(label=e.country_name[:100], value=e.embassy_id, description=f"Embassy of {e.country_name}"[:100]) for e in embassies[:25]]
        super().__init__(placeholder="Select the Embassy you represent", min_values=1, max_values=1, options=options, custom_id=f"embassy:select:{request_id}")

    async def callback(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        await self.cog.select_embassy(interaction, self.request_id, self.values[0])


class EmbassySelectView(discord.ui.View):
    def __init__(self, cog: "CompleteEmbassyCog", request_id: str, embassies: list) -> None:
        super().__init__(timeout=300)
        self.add_item(EmbassySelect(cog, request_id, embassies))


class RequestActionsView(discord.ui.View):
    def __init__(self, cog: "CompleteEmbassyCog", request_id: str) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id

    @discord.ui.button(label="Start / Resolve Profile", style=discord.ButtonStyle.primary, custom_id="embassy:req:start")
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.start_verification(interaction, self.request_id)

    @discord.ui.button(label="Enter OTP", style=discord.ButtonStyle.success, custom_id="embassy:req:otp")
    async def otp(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        request = await self.cog.requests.find_one({"request_id": self.request_id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can verify this request.", ephemeral=True)
            return
        await interaction.response.send_modal(OTPModal(self.cog, self.request_id))


class ApprovalView(discord.ui.View):
    def __init__(self, cog: "CompleteEmbassyCog", request_id: str, route: Route) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id
        self.route = route

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="embassy:approval:approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self.cog.process_decision(interaction, self.request_id, self.route, Decision.APPROVED)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="embassy:approval:decline")
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(DecisionReasonModal(self.cog, self.request_id, self.route, Decision.DECLINED))


class DecisionReasonModal(discord.ui.Modal, title="Decision Reason"):
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, min_length=3, max_length=1000, required=True)

    def __init__(self, cog: "CompleteEmbassyCog", request_id: str, route: Route, decision: Decision) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.request_id = request_id
        self.route = route
        self.decision = decision

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_decision(interaction, self.request_id, self.route, self.decision, self.reason.value.strip())


class PreapprovalModal(discord.ui.Modal, title="Create Embassy Pre-Approval"):
    warera_id = discord.ui.TextInput(label="WarEra User ID / Profile", max_length=200, required=True)
    hours = discord.ui.TextInput(label="Expiry in hours", default="72", max_length=4, required=True)
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, max_length=500, required=False)

    def __init__(self, cog: "CompleteEmbassyCog", diplomat_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.diplomat_id = diplomat_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            hours = max(1, min(720, int(self.hours.value)))
            profile = await self.cog.warera.get_profile(self.warera_id.value.strip())
            assignments = await self.cog.access.active_for_user(self.diplomat_id)
            embassy_ids = [str(x["embassy_id"]) for x in assignments if x.get("assignment_type") == AssignmentType.FOREIGN_DIPLOMAT.value]
            if not embassy_ids:
                await interaction.response.send_message("You are not assigned to any embassy.", ephemeral=True)
                return
            await interaction.response.send_message("Select the Embassy for this pre-approval:", view=PreapprovalEmbassyView(self.cog, embassy_ids, profile.user_id, hours, self.reason.value.strip()), ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f"Pre-approval failed: {exc}", ephemeral=True)


class PreapprovalEmbassyView(discord.ui.View):
    def __init__(self, cog: "CompleteEmbassyCog", embassy_ids: list[str], warera_id: str, hours: int, reason: str) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.warera_id = warera_id
        self.hours = hours
        self.reason = reason
        self.add_item(PreapprovalEmbassySelect(cog, embassy_ids, warera_id, hours, reason))


class PreapprovalEmbassySelect(discord.ui.Select):
    def __init__(self, cog: "CompleteEmbassyCog", embassy_ids: list[str], warera_id: str, hours: int, reason: str) -> None:
        self.cog = cog
        self.warera_id = warera_id
        self.hours = hours
        self.reason = reason
        super().__init__(placeholder="Select assigned Embassy", options=[discord.SelectOption(label=e[:100], value=e) for e in embassy_ids[:25]])

    async def callback(self, interaction: discord.Interaction) -> None:
        expires = datetime.now(timezone.utc) + timedelta(hours=self.hours)
        pid = await self.cog.approvals.create_preapproval(embassy_id=self.values[0], diplomat_id=interaction.user.id, applicant_warera_id=self.warera_id, expires_at=expires, reason=self.reason or None)
        await interaction.response.send_message(f"Pre-approval created: `{pid}`", ephemeral=True)


class AmbassadorModal(discord.ui.Modal, title="Assign Ambassador"):
    discord_id = discord.ui.TextInput(label="Discord User ID", max_length=25, required=True)
    embassy_id = discord.ui.TextInput(label="Embassy ID / country key", max_length=100, required=True)

    def __init__(self, cog: "CompleteEmbassyCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            uid = int(self.discord_id.value)
            embassy = await self.cog.registry.get_by_id(self.embassy_id.value.strip().lower())
            if not embassy or not embassy.active:
                raise ValueError("Embassy not found")
            result = await self.cog.access.assign(uid, embassy.embassy_id, AssignmentType.AMBASSADOR, AccessSource.AMBASSADOR_ASSIGNMENT, assigned_by=interaction.user.id)
            await self.cog.projector.ensure_role(interaction.guild, uid, settings.role_ambassador_id, "Embassy Ambassador assignment")
            await self.cog.projector.grant(interaction.guild, uid, embassy.embassy_id, interaction.user.id, "Ambassador assignment")
            await interaction.response.send_message(f"Ambassador assignment {'created' if result.created else 'already existed'}.", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f"Ambassador assignment failed: {exc}", ephemeral=True)


class EmbassyCreateModal(discord.ui.Modal, title="Create Embassy"):
    country_key = discord.ui.TextInput(label="Country key", max_length=50, required=True)
    country_name = discord.ui.TextInput(label="Country name", max_length=100, required=True)

    def __init__(self, cog: "CompleteEmbassyCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            category = embassy_category(interaction.guild, settings.category_embassy_1_id)
            embassy = await self.cog.embassies.create_embassy(interaction.guild, country_key=self.country_key.value, country_name=self.country_name.value, category=category, actor_id=interaction.user.id)
            channel = interaction.guild.get_channel(embassy.channel_id)
            if isinstance(channel, discord.TextChannel):
                await channel.send(embed=discord.Embed(title=f"Embassy of {embassy.country_name}", description="Official Embassy channel managed by the India Embassy System."))
            await interaction.response.send_message(f"Embassy created: <#{embassy.channel_id}>", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f"Embassy creation failed: {exc}", ephemeral=True)


class MigrationModal(discord.ui.Modal, title="Legacy Role Migration Snapshot"):
    role_ids = discord.ui.TextInput(label="Role IDs (comma separated)", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, cog: "CompleteEmbassyCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            ids = [int(x.strip()) for x in self.role_ids.value.split(",") if x.strip()]
            snapshot = await self.cog.migration.snapshot_roles(interaction.guild, interaction.user.id, ids)
            await interaction.response.send_message(f"Migration snapshot created: `{snapshot}`. Nothing has been deleted.", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f"Snapshot failed: {exc}", ephemeral=True)


class FullManagementView(discord.ui.View):
    def __init__(self, cog: "CompleteEmbassyCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def guard(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("Government Embassy authority is required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Requests", emoji="📨", style=discord.ButtonStyle.primary, custom_id="embassy:mgmt:requests")
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        docs = await self.cog.requests.find({"state": {"$in": [RequestState.DIPLOMAT_REVIEW.value, RequestState.GOVERNMENT_REVIEW.value]}}).sort("created_at", -1).limit(15).to_list(length=15)
        text = "\n".join(f"`{d['request_id']}` • {d.get('verified_country_name','?')} • {d.get('state')}" for d in docs) or "No pending requests."
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Ambassador", emoji="🎖️", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:ambassador")
    async def ambassador(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        await interaction.response.send_modal(AmbassadorModal(self.cog))

    @discord.ui.button(label="Embassies", emoji="🏛️", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:embassies")
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        embassies = await self.cog.registry.get_active()
        text = "\n".join(f"• **{e.country_name}** `{e.embassy_id}` <#{e.channel_id}>" for e in embassies) or "No active embassies."
        await interaction.response.send_message(text[:1900], ephemeral=True)

    @discord.ui.button(label="Create Embassy", emoji="➕", style=discord.ButtonStyle.success, custom_id="embassy:mgmt:create")
    async def create(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        await interaction.response.send_modal(EmbassyCreateModal(self.cog))

    @discord.ui.button(label="Organize", emoji="↕️", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:organize")
    async def organize(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        count = await self.cog.embassies.organize(interaction.guild, interaction.user.id)
        await interaction.response.send_message(f"Organized {count} active Embassy channels alphabetically.", ephemeral=True)

    @discord.ui.button(label="Migration Snapshot", emoji="📦", style=discord.ButtonStyle.danger, custom_id="embassy:mgmt:migration")
    async def migration(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Migration snapshots require Administrator.", ephemeral=True)
            return
        await interaction.response.send_modal(MigrationModal(self.cog))


class DiplomatView(discord.ui.View):
    def __init__(self, cog: "CompleteEmbassyCog") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    async def guard(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not any(r.id == settings.role_foreign_diplomat_id for r in interaction.user.roles):
            await interaction.response.send_message("You need the global Foreign Diplomat role.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="embassy:diplomat:my")
    async def my(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        assignments = await self.cog.access.active_for_user(interaction.user.id)
        rows = [f"• `{a['embassy_id']}`" for a in assignments if a.get('assignment_type') == AssignmentType.FOREIGN_DIPLOMAT.value]
        await interaction.response.send_message("Assigned embassies:\n" + ("\n".join(rows) or "None"), ephemeral=True)

    @discord.ui.button(label="Pre-Approve", emoji="⚡", style=discord.ButtonStyle.success, custom_id="embassy:diplomat:preapprove")
    async def preapprove(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        await interaction.response.send_modal(PreapprovalModal(self.cog, interaction.user.id))

    @discord.ui.button(label="Activity", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self.guard(interaction): return
        docs = await self.cog.audit.collection.find({"actor_id": interaction.user.id}).sort("timestamp", -1).limit(10).to_list(length=10)
        text = "\n".join(f"• {d.get('action')} • {d.get('request_id') or d.get('embassy_id') or ''}" for d in docs) or "No activity found."
        await interaction.response.send_message(text[:1900], ephemeral=True)


class CompleteEmbassyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.requests = bot.database.collection("requests")
        self.audit = AuditLogger(bot.database)
        self.warera = WarEraHTTPClient(settings.warera_api_base, settings.warera_api_profile_path)
        self.verification = VerificationFlow(bot.database, self.warera)
        self.approvals = ApprovalWorkflow(bot.database)
        self.registry = EmbassyRegistry(bot.database)
        self.embassies = EmbassyManager(bot.database)
        self.access = AccessService(bot.database)
        self.projector = AccessProjector(bot.database)
        self.migration = MigrationManager(bot.database)
        self.reconcile.start()

    def cog_unload(self) -> None:
        self.reconcile.cancel()

    @tasks.loop(minutes=15)
    async def reconcile(self) -> None:
        guild = self.bot.get_guild(settings.discord_guild_id)
        if not guild:
            return
        docs = await self.access.collection.find({"active": True}).distinct("discord_user_id")
        for uid in docs[:200]:
            try:
                await self.projector.reconcile_member(guild, int(uid))
            except Exception:
                logger.exception("Access reconciliation failed for %s", uid)

    @reconcile.before_loop
    async def before_reconcile(self) -> None:
        await self.bot.wait_until_ready()

    async def create_request(self, guild: discord.Guild, applicant: discord.Member, profile_input: str) -> str:
        import uuid
        request_id = str(uuid.uuid4())
        parent = guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(parent, discord.TextChannel):
            raise ValueError("Request parent channel is invalid")
        thread = await parent.create_thread(name=f"embassy-{applicant.id}", type=discord.ChannelType.private_thread, invitable=False, reason="Embassy application")
        await thread.add_user(applicant)
        now = datetime.now(timezone.utc)
        await self.requests.insert_one({"request_id": request_id, "discord_user_id": applicant.id, "thread_id": thread.id, "profile_input": profile_input, "state": RequestState.SUBMITTED.value, "created_at": now, "updated_at": now})
        await thread.send(embed=discord.Embed(title="🇮🇳 Embassy Access Request", description="Your application is now in the verification queue.\n\n1. Resolve your WarEra profile\n2. Receive a six-character OTP\n3. Rename a WarEra company to the OTP\n4. Verify it here\n5. Select the Embassy you represent\n6. Approval is routed automatically."), view=RequestActionsView(self, request_id))
        await self.audit.log(action="REQUEST_CREATED", actor_id=applicant.id, request_id=request_id, target_id=str(applicant.id), metadata={"thread_id": thread.id, "profile_input": profile_input})
        return request_id

    async def start_verification(self, interaction: discord.Interaction, request_id: str) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        request = await self.requests.find_one({"request_id": request_id})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can continue this request.", ephemeral=True)
            return
        try:
            profile = await self.verification.resolve_profile(request_id, request.get("profile_input", ""), interaction.user.id)
            otp = await self.verification.issue_company_otp(request_id, interaction.user.id)
            await interaction.response.send_message(f"Profile resolved as **{profile.user_id}** ({profile.country_name}).\n\nYour OTP is `{otp}`. Rename one of your WarEra companies to exactly this code, then press **Enter OTP**.\n\nThe code is intentionally not stored in plaintext.", ephemeral=True)
        except WarEraAPIError as exc:
            await interaction.response.send_message(f"WarEra profile lookup failed: {exc}", ephemeral=True)
        except Exception as exc:
            logger.exception("Verification start failed")
            await interaction.response.send_message(f"Verification could not start: {exc}", ephemeral=True)

    async def send_embassy_selector(self, member: discord.Member, request_id: str) -> None:
        embassies = await self.registry.get_active()
        if not embassies:
            await member.send("No active Embassy channels are currently configured. Please contact Embassy Administration.")
            return
        try:
            await member.send("Select the country you represent:", view=EmbassySelectView(self, request_id, embassies))
        except discord.Forbidden:
            request = await self.requests.find_one({"request_id": request_id})
            if request:
                thread = member.guild.get_thread(request.get("thread_id", 0))
                if thread:
                    await thread.send("Select your Embassy:", view=EmbassySelectView(self, request_id, embassies))

    async def select_embassy(self, interaction: discord.Interaction, request_id: str, embassy_id: str) -> None:
        request = await self.requests.find_one({"request_id": request_id})
        embassy = await self.registry.get_by_id(embassy_id)
        if not request or not embassy or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("This Embassy selection is invalid.", ephemeral=True)
            return
        await self.requests.update_one({"request_id": request_id, "state": RequestState.VERIFIED.value}, {"$set": {"requested_embassy_id": embassy_id, "state": RequestState.EMBASSY_SELECTION.value, "updated_at": datetime.now(timezone.utc)}})
        route = await self.approvals.route(request_id, embassy_country_id=embassy.country_key)
        if route is Route.PREAPPROVED:
            await self.approvals.auto_approve_preapproved(request_id)
            await self.finalize_access(interaction.guild, request_id, AccessSource.PRE_APPROVAL, interaction.user.id)
            await interaction.response.send_message("Pre-approval matched. Your Embassy access has been approved automatically.", ephemeral=True)
            return
        review_state = RequestState.DIPLOMAT_REVIEW.value if route is Route.FOREIGN_DIPLOMAT else RequestState.GOVERNMENT_REVIEW.value
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": review_state, "approval_route": route.value, "updated_at": datetime.now(timezone.utc)}})
        await self.send_approval_panel(interaction.guild, request_id, embassy, route)
        await interaction.response.send_message(f"Your request has been routed to **{route.value}** for approval.", ephemeral=True)

    async def send_approval_panel(self, guild: discord.Guild, request_id: str, embassy, route: Route) -> None:
        target = guild.get_channel(embassy.channel_id) if route is Route.FOREIGN_DIPLOMAT else guild.get_channel(settings.channel_embassy_management_id)
        if not isinstance(target, discord.TextChannel):
            return
        role = guild.get_role(settings.role_foreign_diplomat_id) if route is Route.FOREIGN_DIPLOMAT else None
        mention = role.mention if role else "Embassy Government Authority"
        request = await self.requests.find_one({"request_id": request_id})
        embed = discord.Embed(title="Embassy Access Approval", description=f"Request: `{request_id}`\nApplicant: <@{request['discord_user_id']}>\nWarEra ID: `{request.get('warera_user_id')}`\nCountry: **{request.get('verified_country_name')}**\nRoute: **{route.value}**", color=discord.Color.dark_red())
        await target.send(content=mention, embed=embed, view=ApprovalView(self, request_id, route))

    async def process_decision(self, interaction: discord.Interaction, request_id: str, route: Route, decision: Decision, reason: str | None = None) -> None:
        if not isinstance(interaction.user, discord.Member):
            return
        request = await self.requests.find_one({"request_id": request_id})
        if not request:
            await interaction.response.send_message("Request not found.", ephemeral=True)
            return
        embassy_id = str(request.get("requested_embassy_id") or "")
        allowed = is_government(interaction.user) if route is not Route.FOREIGN_DIPLOMAT else (any(r.id == settings.role_foreign_diplomat_id for r in interaction.user.roles) and await self.access.has_access(interaction.user.id, embassy_id))
        if not allowed:
            await interaction.response.send_message("You are not authorized for this approval route.", ephemeral=True)
            return
        if decision is Decision.DECLINED and not reason:
            await interaction.response.send_message("A decline reason is required.", ephemeral=True)
            return
        accepted = await self.approvals.decide(request_id, interaction.user.id, decision, route, reason)
        if not accepted:
            await interaction.response.send_message("This request has already been decided.", ephemeral=True)
            return
        if decision is Decision.APPROVED:
            await self.finalize_access(interaction.guild, request_id, AccessSource.DIPLOMAT_APPROVAL if route is Route.FOREIGN_DIPLOMAT else AccessSource.GOVERNMENT_OVERRIDE, interaction.user.id)
        await interaction.response.send_message(f"Request **{decision.value.lower()}**.", ephemeral=True)
        for child in self.bot.get_all_channels():
            if isinstance(child, discord.Thread) and child.id == request.get("thread_id"):
                await child.send(f"Embassy decision: **{decision.value}**" + (f"\nReason: {reason}" if reason else ""))
                break

    async def finalize_access(self, guild: discord.Guild, request_id: str, source: AccessSource, actor_id: int) -> None:
        request = await self.requests.find_one({"request_id": request_id})
        if not request:
            return
        embassy_id = str(request["requested_embassy_id"])
        uid = int(request["discord_user_id"])
        result = await self.access.assign(uid, embassy_id, AssignmentType.FOREIGN_DIPLOMAT, source, assigned_by=actor_id)
        await self.projector.grant(guild, uid, embassy_id, actor_id, "Embassy access approved")
        await self.projector.ensure_role(guild, uid, settings.role_foreigner_id, "Embassy access approved")
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.APPROVED.value, "assignment_id": result.assignment_id, "updated_at": datetime.now(timezone.utc)}})
        await self.audit.log(action="ACCESS_FINALIZED", actor_id=actor_id, request_id=request_id, target_id=str(uid), embassy_id=embassy_id, warera_id=str(request.get("warera_user_id") or ""), new_state=RequestState.APPROVED.value)

    @app_commands.command(name="embassy-setup", description="Post the Embassy access request panel.")
    async def setup_panel(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("Government authority required.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Request channel is invalid.", ephemeral=True)
            return
        await channel.send(embed=discord.Embed(title="🇮🇳 Embassy Access System", description="Foreign diplomats can request access to Indian Embassy channels here. Click the button to begin verification."), view=RequestPanelView(self))
        await interaction.response.send_message("Embassy panel posted.", ephemeral=True)

    @app_commands.command(name="embassy-dashboard", description="Open the full Embassy Management Dashboard.")
    async def dashboard(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("Government Embassy authority required.", ephemeral=True)
            return
        await interaction.response.send_message(embed=discord.Embed(title="🏛️ Embassy Management", description="Requests • Ambassadors • Embassies • Organizer • Migration"), view=FullManagementView(self))

    @app_commands.command(name="foreign-diplomat-dashboard", description="Open the Foreign Diplomat Portal.")
    async def diplomat_dashboard(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not any(r.id == settings.role_foreign_diplomat_id for r in interaction.user.roles):
            await interaction.response.send_message("You need the Foreign Diplomat role.", ephemeral=True)
            return
        await interaction.response.send_message(embed=discord.Embed(title="🌍 Foreign Diplomat Portal", description="Manage only your assigned Embassies and create pre-approvals."), view=DiplomatView(self), ephemeral=True)

    @app_commands.command(name="embassy-audit", description="View recent Embassy System audit events.")
    async def audit_command(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member) or not is_government(interaction.user):
            await interaction.response.send_message("Government authority required.", ephemeral=True)
            return
        docs = await self.audit.collection.find({}).sort("timestamp", -1).limit(20).to_list(length=20)
        text = "\n".join(f"`{d.get('action')}` • <t:{int(d['timestamp'].timestamp())}:R> • actor `{d.get('actor_id')}` • request `{d.get('request_id') or '-'}`" for d in docs) or "No audit events yet."
        await interaction.response.send_message(text[:4000], ephemeral=True)

    async def cog_load(self) -> None:
        self.bot.add_view(RequestPanelView(self))
        self.bot.add_view(ApprovalView(self, "persistent", Route.GOVERNMENT)) if False else None


class RequestPanelView(discord.ui.View):
    def __init__(self, cog: CompleteEmbassyCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Request Embassy Access", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="embassy:request-access")
    async def request(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ProfileModal(self.cog))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompleteEmbassyCog(bot))
