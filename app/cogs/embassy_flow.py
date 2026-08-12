from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import discord

from access.discord import DiscordAccessProvisioner
from access.models import AccessSource, AssignmentType
from app.config import settings
from approval.workflow import ApprovalWorkflow, Decision, Route
from core.audit import AuditLogger
from core.state import RequestState
from embassy.registry import Embassy, EmbassyRegistry
from access.service import AccessService

logger = logging.getLogger(__name__)


class EmbassyFlow:
    """Implements the post-WarEra-verification flow from the Embassy specification."""

    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.db = bot.database
        self.registry = EmbassyRegistry(self.db)
        self.access = AccessService(self.db)
        self.approvals = ApprovalWorkflow(self.db)
        self.audit = AuditLogger(self.db)

    async def show_embassy_choice(self, interaction: discord.Interaction, request: dict) -> None:
        country_name = str(request.get("verified_country_name") or "Unknown Country")
        embed = discord.Embed(
            title="🏛️ Embassy Access",
            description=(
                "Your WarEra identity and company ownership have been successfully verified.\n\n"
                f"**Verified Country:** 🇺🇳 {country_name}\n\n"
                "Which Embassy would you like to join?"
            ),
            color=discord.Color.green(),
        )
        await interaction.edit_original_response(embed=embed, content=None, view=EmbassyChoiceView(self.bot, str(request["request_id"])))

    async def process_choice(self, interaction: discord.Interaction, request_id: str, choice: str) -> None:
        request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
        if not request:
            await interaction.response.send_message("This Embassy request is no longer active.", ephemeral=True)
            return
        if request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("Only the applicant can choose the Embassy for this request.", ephemeral=True)
            return
        if request.get("state") != RequestState.VERIFIED.value:
            await interaction.response.send_message("This request is not ready for Embassy selection.", ephemeral=True)
            return

        if choice == "own":
            await interaction.response.defer()
            await self._handle_own_country(interaction, request)
            return

        # The specification requires an Embassy target for the alternate-country path.
        # We therefore present the active Embassy registry so the applicant can choose
        # the country they discussed with EAM/Admin.
        await interaction.response.defer(ephemeral=True)
        embassies = await self.registry.get_active()
        embassies = [e for e in embassies if e.country_key.lower() != str(request.get("verified_country_id") or "").lower() and e.country_name.lower() != str(request.get("verified_country_name") or "").lower()]
        if not embassies:
            await interaction.followup.send("There are currently no other active Embassies to request. Please contact EAM/Admin.", ephemeral=True)
            return
        options = [discord.SelectOption(label=e.country_name[:100], value=e.embassy_id, description=f"Request access to the {e.country_name} Embassy") for e in embassies[:25]]
        await interaction.followup.send(
            "Select the Embassy you want to join. This request will go to EAM/Admin for approval.",
            ephemeral=True,
            view=OtherEmbassySelectView(self.bot, request_id, options),
        )

    async def _handle_own_country(self, interaction: discord.Interaction, request: dict) -> None:
        country_id = str(request.get("verified_country_id") or "").strip()
        country_name = str(request.get("verified_country_name") or "").strip()
        embassy = await self.registry.get_by_country(country_id) if country_id else None
        if embassy is None:
            embassy = await self.registry.get_by_country(country_name)

        if embassy is None or not embassy.active:
            embassy = await self._create_embassy(interaction.guild, country_id or country_name, country_name, interaction.user.id)
            await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.SPECIAL_OFFICIAL)
            await self._finalize_direct(interaction, request, embassy, "Embassy did not previously exist. The applicant became the first active diplomat.")
            return

        active = await self.access.active_for_embassy(embassy.embassy_id)
        if not active:
            await self._set_review(request, embassy, Route.GOVERNMENT_REVIEW, reason="Embassy exists but has no active diplomats")
            await self._notify_government(interaction.guild, request, embassy, revival=True)
            await interaction.followup.send("The Embassy exists but has no active diplomats. EAM/Admin has been notified to review the revival request.", ephemeral=True)
            return

        preapproval = await self.approvals.find_preapproval(embassy.embassy_id, str(request.get("warera_user_id") or ""))
        if preapproval:
            approved = await self.approvals.auto_approve_preapproved(request["request_id"])
            if approved:
                await self._grant_access(interaction.guild, interaction.user.id, embassy, AccessSource.PRE_APPROVAL)
                await self._finalize_direct(interaction, request, embassy, "Valid Embassy pre-approval was found.", action="REQUEST_AUTO_APPROVED")
                await self.approvals.consume_preapproval(str(preapproval["preapproval_id"]))
                return

        await self._set_review(request, embassy, Route.FOREIGN_DIPLOMAT, reason="Awaiting approval from an active diplomat")
        await self._notify_diplomats(interaction.guild, request, embassy)
        await interaction.followup.send("Your request has been sent to the active diplomats of that Embassy. You will be notified here once a decision is made.", ephemeral=True)

    async def process_other_embassy(self, interaction: discord.Interaction, request_id: str, embassy_id: str) -> None:
        request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
        if not request or request.get("discord_user_id") != interaction.user.id:
            await interaction.response.send_message("This request is no longer available.", ephemeral=True)
            return
        embassy = await self.registry.get_by_id(embassy_id)
        if not embassy or not embassy.active:
            await interaction.response.send_message("That Embassy is no longer active. Please restart the Embassy selection.", ephemeral=True)
            return
        await interaction.response.defer()
        await self._set_review(request, embassy, Route.GOVERNMENT_REVIEW, reason="Applicant requested an Embassy outside their WarEra country")
        await self._notify_government(interaction.guild, request, embassy, revival=False)
        await interaction.followup.send("Your request has been sent to EAM/Admin for review. Please discuss the request with them while it is pending.", ephemeral=True)

    async def _set_review(self, request: dict, embassy: Embassy, route: Route, *, reason: str) -> None:
        state = RequestState.DIPLOMAT_REVIEW.value if route is Route.FOREIGN_DIPLOMAT else RequestState.GOVERNMENT_REVIEW.value
        await self.db.collection("requests").update_one(
            {"request_id": request["request_id"]},
            {"$set": {"requested_embassy_id": embassy.embassy_id, "approval_route": route.value, "state": state, "status": "PENDING_APPROVAL", "updated_at": datetime.now(timezone.utc)}},
        )
        await self.audit.log(action="REQUEST_SENT_FOR_APPROVAL", actor_id=int(request["discord_user_id"]), request_id=request["request_id"], embassy_id=embassy.embassy_id, route=route.value, reason=reason)
        await self._log_channel(
            f"📨 **Embassy Access Request**\n**Embassy:** {embassy.country_name}\n**Applicant:** <@{request['discord_user_id']}>\n**WarEra:** `{request.get('warera_user_id', 'unknown')}`\n**Route:** `{route.value}`\n**Status:** Awaiting approval",
        )

    async def _notify_diplomats(self, guild: discord.Guild, request: dict, embassy: Embassy) -> None:
        channel = guild.get_channel(embassy.channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Embassy channel is missing")
        assignments = await self.access.active_for_embassy(embassy.embassy_id)
        mentions = []
        for assignment in assignments:
            member = guild.get_member(int(assignment["discord_user_id"]))
            if member:
                mentions.append(member.mention)
        profile = request.get("warera_profile_url") or "Unavailable"
        content = " ".join(mentions) if mentions else ""
        embed = self._approval_embed(request, embassy, "Active Embassy diplomats must review this request.")
        message = await channel.send(content=content or "📨 Embassy access request", embed=embed, view=EmbassyApprovalView(self.bot, request["request_id"], Route.FOREIGN_DIPLOMAT.value), allowed_mentions=discord.AllowedMentions(users=True))
        await self.db.collection("requests").update_one({"request_id": request["request_id"]}, {"$set": {"approval_message_id": message.id}})

    async def _notify_government(self, guild: discord.Guild, request: dict, embassy: Embassy, *, revival: bool) -> None:
        channel = guild.get_channel(settings.channel_embassy_management_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Embassy management channel is missing")
        role = guild.get_role(settings.role_eam_id)
        mention = role.mention if role else "@EAM"
        reason = "Embassy exists but has no active diplomats" if revival else "Applicant requested an Embassy outside their WarEra country"
        embed = self._approval_embed(request, embassy, reason)
        message = await channel.send(content=mention, embed=embed, view=EmbassyApprovalView(self.bot, request["request_id"], Route.GOVERNMENT_REVIEW.value), allowed_mentions=discord.AllowedMentions(roles=True))
        await self.db.collection("requests").update_one({"request_id": request["request_id"]}, {"$set": {"approval_message_id": message.id}})

    def _approval_embed(self, request: dict, embassy: Embassy, reason: str) -> discord.Embed:
        embed = discord.Embed(title="🏛️ Embassy Access Request", color=discord.Color.orange())
        embed.add_field(name="Applicant", value=f"<@{request['discord_user_id']}> (`{request['discord_user_id']}`)", inline=False)
        embed.add_field(name="WarEra Profile", value=str(request.get("warera_profile_url") or "Unavailable"), inline=False)
        embed.add_field(name="WarEra Country", value=str(request.get("verified_country_name") or "Unknown"), inline=True)
        embed.add_field(name="Embassy Requested", value=embassy.country_name, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        return embed

    async def _create_embassy(self, guild: discord.Guild, country_key: str, country_name: str, actor_id: int) -> Embassy:
        key = re.sub(r"[^a-z0-9-]+", "-", (country_name or country_key).strip().lower()).strip("-") or "unknown"
        existing = await self.registry.get_by_country(country_key) or await self.registry.get_by_country(country_name)
        if existing and existing.active:
            return existing
        category = guild.get_channel(settings.category_embassy_1_id)
        if not isinstance(category, discord.CategoryChannel):
            category = guild.get_channel(settings.category_embassy_2_id)
        if not isinstance(category, discord.CategoryChannel):
            raise ValueError("No Embassy category is configured")

        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        for role_id in (settings.role_president_id, settings.role_vice_president_id, settings.role_nsa_id, settings.role_minister_id):
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        diplomat_role = guild.get_role(settings.role_foreign_diplomat_id)
        if diplomat_role:
            overwrites[diplomat_role] = discord.PermissionOverwrite(view_channel=False)

        channel = await guild.create_text_channel(
            name=f"{key}-embassy"[:100],
            category=category,
            topic=f"Official Embassy of {country_name} | Embassy System",
            overwrites=overwrites,
            reason=f"Create Embassy for {country_name} from access request {actor_id}",
        )
        embassy_id = str(country_key or key)
        embassy = Embassy(embassy_id=embassy_id, country_key=embassy_id.lower(), country_name=country_name, channel_id=channel.id, category_id=category.id, active=True)
        await self.registry.upsert(embassy)
        await self.audit.log(action="EMBASSY_CREATED", actor_id=actor_id, embassy_id=embassy.embassy_id, metadata={"channel_id": channel.id, "country_name": country_name})
        return embassy

    async def _grant_access(self, guild: discord.Guild, user_id: int, embassy: Embassy, source: AccessSource) -> None:
        member = guild.get_member(user_id)
        channel = guild.get_channel(embassy.channel_id)
        if not isinstance(member, discord.Member) or not isinstance(channel, discord.TextChannel):
            raise ValueError("Applicant or Embassy channel is unavailable")
        await self.access.assign(user_id, embassy.embassy_id, AssignmentType.FOREIGN_DIPLOMAT, source)
        provisioner = DiscordAccessProvisioner(foreign_diplomat_role_id=settings.role_foreign_diplomat_id)
        await provisioner.grant_embassy_access(member, channel, reason=f"Embassy access granted for {embassy.country_name}")
        role = guild.get_role(settings.role_foreign_diplomat_id)
        if role:
            await provisioner.ensure_role(member, role, reason="User received Embassy access")

    async def _finalize_direct(self, interaction: discord.Interaction, request: dict, embassy: Embassy, reason: str, action: str = "REQUEST_APPROVED") -> None:
        now = datetime.now(timezone.utc)
        await self.db.collection("requests").update_one({"request_id": request["request_id"]}, {"$set": {"requested_embassy_id": embassy.embassy_id, "state": RequestState.APPROVED.value, "status": "APPROVED", "decision": Decision.APPROVED.value, "decision_actor_id": interaction.user.id, "decision_reason": reason, "active": False, "updated_at": now}})
        await self.audit.log(action=action, actor_id=interaction.user.id, request_id=request["request_id"], embassy_id=embassy.embassy_id, reason=reason)
        await self._log_channel(f"✅ **Embassy Access Granted**\n**Embassy:** {embassy.country_name}\n**Applicant:** <@{request['discord_user_id']}>\n**Approved By:** <@{interaction.user.id}>\n**Reason:** {reason}")
        await self._close_request_thread(interaction.guild, request, f"Your Embassy access request has been **approved**.\n\n**Embassy:** {embassy.country_name}\n**Approved by:** {interaction.user.mention}\n\nYour Embassy access has been granted. Welcome, diplomat. 🇮🇳")

    async def decide(self, interaction: discord.Interaction, request_id: str, decision: Decision, route: Route) -> None:
        request = await self.db.collection("requests").find_one({"request_id": request_id, "active": True})
        if not request:
            await interaction.response.send_message("This request has already been decided or closed.", ephemeral=True)
            return
        if route is Route.FOREIGN_DIPLOMAT:
            if not await self.access.has_access(interaction.user.id, str(request.get("requested_embassy_id") or "")):
                await interaction.response.send_message("Only an active diplomat of this Embassy can decide this request.", ephemeral=True)
                return
        elif route is Route.GOVERNMENT_REVIEW:
            if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.administrator or any(r.id == settings.role_eam_id for r in interaction.user.roles)):
                await interaction.response.send_message("Only EAM or an Administrator can decide this request.", ephemeral=True)
                return
        await interaction.response.defer()
        ok = await self.approvals.decide(request_id, interaction.user.id, decision, route)
        if not ok:
            await interaction.followup.send("This request was already decided by someone else.", ephemeral=True)
            return
        embassy = await self.registry.get_by_id(str(request.get("requested_embassy_id") or ""))
        if embassy is None:
            await interaction.followup.send("The Embassy record could not be found. The decision was recorded; please contact an administrator.", ephemeral=True)
            return
        if decision is Decision.APPROVED:
            await self._grant_access(interaction.guild, int(request["discord_user_id"]), embassy, AccessSource.DIPLOMAT_APPROVAL if route is Route.FOREIGN_DIPLOMAT else AccessSource.GOVERNMENT_OVERRIDE)
            if route is Route.GOVERNMENT_REVIEW and not await self.access.has_access(int(request["discord_user_id"]), embassy.embassy_id):
                pass
            await self._log_channel(f"✅ **Embassy Access Approved**\n**Embassy:** {embassy.country_name}\n**Applicant:** <@{request['discord_user_id']}>\n**Approved By:** {interaction.user.mention}")
            await self._close_request_thread(interaction.guild, request, f"Your Embassy access request has been **approved**.\n\n**Embassy:** {embassy.country_name}\n**Approved by:** {interaction.user.mention}\n\nYour access has been granted. Welcome, diplomat. 🇮🇳")
        else:
            await self._log_channel(f"❌ **Embassy Access Declined**\n**Embassy:** {embassy.country_name}\n**Applicant:** <@{request['discord_user_id']}>\n**Declined By:** {interaction.user.mention}")
            await self._close_request_thread(interaction.guild, request, f"Your Embassy access request has been **declined**.\n\n**Embassy:** {embassy.country_name}\n**Decision by:** {interaction.user.mention}\n\nNo Embassy access has been granted.")
        try:
            if interaction.message:
                await interaction.message.edit(view=EmbassyApprovalView.disabled_view())
        except discord.HTTPException:
            pass

    async def _close_request_thread(self, guild: discord.Guild, request: dict, message: str) -> None:
        thread = guild.get_thread(int(request["thread_id"])) if hasattr(guild, "get_thread") else None
        if not isinstance(thread, discord.Thread):
            channel = guild.get_channel(int(request["thread_id"]))
            thread = channel if isinstance(channel, discord.Thread) else None
        if not isinstance(thread, discord.Thread):
            return
        try:
            await thread.send(message)
            await thread.edit(locked=True, archived=True, reason="Embassy request completed")
        except discord.HTTPException:
            logger.exception("Unable to close Embassy request thread %s", request.get("thread_id"))

    async def _log_channel(self, content: str) -> None:
        channel = self.bot.get_channel(settings.channel_embassy_request_logs_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(content, allowed_mentions=discord.AllowedMentions(users=True, roles=True))


class EmbassyChoiceView(discord.ui.View):
    def __init__(self, bot: discord.Client, request_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.request_id = request_id

    @discord.ui.button(label="My Country Embassy", emoji="🏛️", style=discord.ButtonStyle.success, custom_id="embassy:choice:own")
    async def own(self, interaction: discord.Interaction, _: discord.ui.Button):
        await EmbassyFlow(self.bot).process_choice(interaction, self.request_id, "own")

    @discord.ui.button(label="Want to join another Embassy", emoji="🌍", style=discord.ButtonStyle.primary, custom_id="embassy:choice:other")
    async def other(self, interaction: discord.Interaction, _: discord.ui.Button):
        await EmbassyFlow(self.bot).process_choice(interaction, self.request_id, "other")


class OtherEmbassySelectView(discord.ui.View):
    def __init__(self, bot: discord.Client, request_id: str, options: list[discord.SelectOption]):
        super().__init__(timeout=600)
        self.bot = bot
        self.request_id = request_id
        select = discord.ui.Select(placeholder="Select the Embassy you want to join...", options=options, custom_id=f"embassy:other-select:{request_id}")
        select.callback = self._selected
        self.add_item(select)

    async def _selected(self, interaction: discord.Interaction) -> None:
        select = self.children[0]
        await EmbassyFlow(self.bot).process_other_embassy(interaction, self.request_id, select.values[0])


class EmbassyApprovalView(discord.ui.View):
    def __init__(self, bot: discord.Client, request_id: str, route: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.request_id = request_id
        self.route = route
        approve = discord.ui.Button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"embassy:approve:{request_id}")
        decline = discord.ui.Button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"embassy:decline:{request_id}")
        approve.callback = self._approve
        decline.callback = self._decline
        self.add_item(approve)
        self.add_item(decline)

    @classmethod
    def disabled_view(cls):
        view = cls.__new__(cls)
        discord.ui.View.__init__(view, timeout=None)
        for label, emoji, style in (("Approved", "✅", discord.ButtonStyle.success), ("Declined", "❌", discord.ButtonStyle.danger)):
            button = discord.ui.Button(label=label, emoji=emoji, style=style, disabled=True, custom_id=f"embassy:closed:{label.lower()}")
            view.add_item(button)
        return view

    async def _approve(self, interaction: discord.Interaction):
        await EmbassyFlow(self.bot).decide(interaction, self.request_id, Decision.APPROVED, Route(self.route))

    async def _decline(self, interaction: discord.Interaction):
        await EmbassyFlow(self.bot).decide(interaction, self.request_id, Decision.DECLINED, Route(self.route))
