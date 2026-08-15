from __future__ import annotations

import asyncio
import hashlib
import re
import secrets
import string
from typing import Any

import discord
from discord import app_commands

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.embassy_access import EmbassyAccessService, EMBASSY_PERMISSIONS, is_government
from rajdoot.warera import WarEraClient, detect_government_position
from rajdoot.workflow_store import WorkflowStore


OTP_ALPHABET = string.ascii_uppercase + string.digits


def make_otp() -> str:
    return "".join(secrets.choice(OTP_ALPHABET) for _ in range(6))


def hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def warera_user_id_from_url(value: str) -> str | None:
    match = re.search(r"/user/([A-Za-z0-9_-]+)", value.strip())
    return match.group(1) if match else None


def profile_value(profile: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value: Any = profile
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, ""):
            return value
    return None


def country_info(profile: dict[str, Any]) -> tuple[str | None, str | None]:
    country = profile_value(profile, "country", "countryName", "infos.country", "citizenship")
    if isinstance(country, dict):
        return str(country.get("id") or country.get("countryId") or "") or None, str(country.get("name") or "") or None
    country_id = profile_value(profile, "countryId", "infos.countryId", "citizenshipId")
    return (str(country_id) if country_id else None, str(country) if country else None)


def profile_embed(profile: dict[str, Any], *, title: str = "WarEra Verification Complete") -> discord.Embed:
    country_id, country_name = country_info(profile)
    position = detect_government_position(profile) or "None"
    username = profile_value(profile, "username", "name", "displayName") or "Unknown"
    embed = discord.Embed(title=f"✅ {title}", colour=discord.Colour.green())
    embed.add_field(name="Player", value=str(username), inline=True)
    embed.add_field(name="Country", value=str(country_name or country_id or "Unknown"), inline=True)
    embed.add_field(name="Official Status", value=position, inline=True)
    embed.description = "Your WarEra identity and company ownership have been successfully verified."
    return embed


class OpenWarEraView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Open WarEra", emoji="🌐", style=discord.ButtonStyle.link,
            url="https://app.warera.io/user/"
        ))
        self.add_item(discord.ui.Button(label="PC Tutorial", style=discord.ButtonStyle.secondary, custom_id="rajdoot:embassy:pc"))
        self.add_item(discord.ui.Button(label="Mobile Tutorial", style=discord.ButtonStyle.secondary, custom_id="rajdoot:embassy:mobile"))


class ProfileLinkModal(discord.ui.Modal, title="WarEra Profile"):
    profile = discord.ui.TextInput(
        label="WarEra profile link",
        placeholder="https://app.warera.io/user/...",
        required=True,
        max_length=300,
    )

    def __init__(self, database: Database, request_id: str, thread: discord.Thread) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.request_id = request_id
        self.thread = thread

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = warera_user_id_from_url(str(self.profile.value))
        if not user_id:
            await interaction.followup.send("❌ I could not read a WarEra user ID from that profile URL.", ephemeral=True)
            return
        store = WorkflowStore(self.database)
        warera = WarEraClient(settings)
        try:
            profile = await warera.get_full_profile(user_id)
        except Exception:
            await store.set_flow_state(self.request_id, "profile_failed", verification_status="failed", request_status="failed")
            await interaction.followup.send("⚠️ WarEra could not be reached right now. Please try again later.", ephemeral=True)
            return
        if profile is None:
            await interaction.followup.send("❌ That WarEra profile could not be found.", ephemeral=True)
            return

        otp = make_otp()
        await store.issue_otp(self.request_id, hash_otp(otp))
        country_id, country_name = country_info(profile.raw)
        position = detect_government_position(profile.raw)
        await store.set_flow_state(
            self.request_id,
            "company_verification",
            warera_user_id=profile.user_id,
            warera_profile_snapshot=profile.raw,
            government_position=position,
            government_country_id=country_id,
            target_country_id=country_id,
        )

        embed = discord.Embed(
            title="🔐 WarEra Company Verification",
            description=(
                "Rename **one of your WarEra companies** to the unique code below.\n\n"
                f"Your OTP is:\n```{otp}```\n"
                "You have **5 attempts**. The verification controls below stay active so you can retry."
            ),
            colour=discord.Colour.blurple(),
        )
        profile_url = str(self.profile.value).rstrip("/")
        companies_url = f"{profile_url}/companies"
        view = CompanyVerificationView(self.database, self.request_id, interaction.user.id, profile.user_id, otp, companies_url)
        await self.thread.send(embed=embed, view=view)
        await self.thread.send(
            f"🔎 I found **{profile_value(profile.raw, 'username', 'name', 'displayName') or 'your WarEra profile'}**. "
            f"Country detected: **{country_name or country_id or 'Unknown'}**.\n\n"
            "Take your time — diplomacy is one of the few jobs where changing a company name is considered paperwork. 😄",
        )
        await interaction.followup.send("✅ Profile received. The verification card is now in your request thread.", ephemeral=True)


class StartEmbassyFlowView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, thread: discord.Thread) -> None:
        super().__init__(timeout=None)
        self.database = database
        self.request_id = request_id
        self.thread = thread

    @discord.ui.button(label="Submit WarEra Profile", emoji="🔗", style=discord.ButtonStyle.primary)
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(ProfileLinkModal(self.database, self.request_id, self.thread))


class CompanyVerificationView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant_id: int, warera_user_id: str,
                 otp: str, companies_url: str) -> None:
        super().__init__(timeout=1800)
        self.database = database
        self.request_id = request_id
        self.applicant_id = applicant_id
        self.warera_user_id = warera_user_id
        self.otp = otp
        self.companies_url = companies_url
        self.add_item(discord.ui.Button(
            label="Open Your Companies", emoji="🏢", style=discord.ButtonStyle.link, url=companies_url
        ))
        self.add_item(discord.ui.Button(
            label="Copy OTP", emoji="📋", style=discord.ButtonStyle.secondary, custom_id=f"rajdoot:otp:copy:{request_id}"
        ))
        verify = discord.ui.Button(label="Verify Companies", emoji="🔎", style=discord.ButtonStyle.success)
        verify.callback = self.verify
        self.add_item(verify)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.applicant_id:
            await interaction.response.send_message("🔐 This verification belongs to another applicant.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        self.stop()

    async def verify(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send("🔍 Checking your company... diplomacy doesn't happen instantly — even bots need to make a few phone calls. ☕", ephemeral=True)
        warera = WarEraClient(settings)
        try:
            match = await warera.verify_company_otp(self.warera_user_id, self.otp)
        except Exception:
            await interaction.followup.send("⚠️ WarEra company data could not be checked right now. Your attempt was not consumed.", ephemeral=True)
            return
        status, request = await WorkflowStore(self.database).record_company_attempt(self.request_id, match)
        if status == "verified":
            await interaction.followup.send("✅ Company verified! I am opening the embassy selection below.", ephemeral=True)
            if interaction.message and interaction.message.channel:
                await embassy_selection_message(self.database, self.request_id, interaction.message.channel)
            return
        if status == "max_attempts":
            await interaction.followup.send("🛑 Five company checks failed. This embassy request is halted and must be reviewed by EAM/Admin.", ephemeral=True)
            if interaction.message and interaction.message.channel:
                await interaction.message.channel.send("🚨 **Embassy verification halted.** EAM/Admin attention is required for this request.")
            return
        if status == "expired":
            await interaction.followup.send("⌛ This OTP expired. Start a new embassy request to receive a fresh code.", ephemeral=True)
            return
        if status == "closed":
            await interaction.followup.send("This embassy request is already closed.", ephemeral=True)
            return
        attempts = int((request or {}).get("verification_attempts") or 0)
        await interaction.followup.send(f"❌ I could not find that OTP in your companies. Attempt **{attempts}/5** used. Rename the company and try again.", ephemeral=True)

    async def copy_otp(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"```{self.otp}```\nCopy the code above. 📋", ephemeral=True)


class EmbassySelectionView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant: discord.Member, profile: dict[str, Any]) -> None:
        super().__init__(timeout=None)
        self.database = database
        self.request_id = request_id
        self.applicant = applicant
        self.profile = profile
        self.store = WorkflowStore(database)
        country_id, country_name = country_info(profile)
        self.country_id = country_id
        self.country_name = country_name or "Your Country"
        self.add_item(discord.ui.Button(
            label=f"{self.country_name} Embassy"[:80], emoji="🏛️", style=discord.ButtonStyle.primary,
            custom_id=f"rajdoot:embassy:own:{request_id}"
        ))
        self.add_item(discord.ui.Button(
            label="Want to Join another Embassy", emoji="🌍", style=discord.ButtonStyle.secondary,
            custom_id=f"rajdoot:embassy:other:{request_id}"
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.applicant.id:
            await interaction.response.send_message("This embassy selection belongs to another applicant.", ephemeral=True)
            return False
        return True

    async def own(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        embassies = await self.database.fetch_active_embassies()
        own = next((e for e in embassies if self._matches_country(e)), None)
        if own is None:
            await interaction.followup.send(
                f"🏛️ **{self.country_name} Embassy** does not exist yet. I am escalating this as an embassy creation/revival case.", ephemeral=True
            )
            await route_own_country(self.database, self.request_id, self.applicant, self.profile, None, interaction.channel)
            return
        assignments = await self.store.active_assignments_for_user(self.applicant.id)
        if any(str(a["embassy_id"]) == str(own["id"]) for a in assignments):
            await interaction.followup.send(
                f"ℹ️ You already are a diplomat in **{own['country_name']} Embassy**. I have not closed this request — you can still choose another embassy.", ephemeral=True
            )
            return
        await route_own_country(self.database, self.request_id, self.applicant, self.profile, own, interaction.channel)

    def _matches_country(self, embassy: dict[str, Any]) -> bool:
        values = {str(embassy.get("country_id") or "").casefold(), str(embassy.get("country_name") or "").casefold()}
        return any(v and v in {str(self.country_id or "").casefold(), str(self.country_name).casefold()} for v in values)

    async def other(self, interaction: discord.Interaction) -> None:
        embassies = await self.database.fetch_active_embassies()
        options = [discord.SelectOption(label=str(e["country_name"])[:100], value=str(e["id"])) for e in embassies[:25]]
        select = discord.ui.Select(placeholder="Choose the embassy you want", options=options)

        async def callback(inner: discord.Interaction) -> None:
            if inner.user.id != self.applicant.id:
                await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                return
            await inner.response.defer(ephemeral=True, thinking=True)
            embassy = next((e for e in embassies if str(e["id"]) == select.values[0]), None)
            if embassy is None:
                await inner.followup.send("❌ Embassy not found.", ephemeral=True)
                return
            await route_other_country(self.database, self.request_id, self.applicant, self.profile, embassy, inner.channel)

        select.callback = callback
        view = discord.ui.View(timeout=300)
        view.add_item(select)
        await interaction.response.send_message("🌍 Choose the embassy you want to discuss with EAM/Admin:", view=view, ephemeral=True)


async def embassy_selection_message(database: Database, request_id: str, channel: discord.abc.Messageable) -> None:
    request = await WorkflowStore(database).fetch_request(request_id)
    if not request:
        return
    profile = request.get("warera_profile_snapshot") or {}
    guild = getattr(channel, "guild", None)
    applicant = guild.get_member(int(request["applicant_discord_id"])) if guild else None
    if applicant is None:
        return
    country_id, country_name = country_info(profile)
    await WorkflowStore(database).set_flow_state(request_id, "embassy_selection", target_country_id=country_id)
    embed = profile_embed(profile)
    embed.title = "🏛️ Embassy Access"
    embed.description = f"Which Embassy would you like to join, {applicant.mention}?"
    await channel.send(embed=embed, view=EmbassySelectionView(database, request_id, applicant, profile))


async def route_own_country(database: Database, request_id: str, applicant: discord.Member,
                            profile: dict[str, Any], embassy: dict[str, Any] | None,
                            channel: discord.abc.Messageable | None) -> None:
    store = WorkflowStore(database)
    country_id, country_name = country_info(profile)
    position = detect_government_position(profile)
    if embassy is None:
        await store.set_flow_state(request_id, "embassy_creation_pending", government_position=position, government_country_id=country_id)
        if channel:
            await channel.send("🏗️ **Embassy Creation Required**\n\nNo embassy exists for this country yet. EAM/Admin has been notified to review the new mission.")
        return
    await store.set_flow_state(
        request_id,
        "awaiting_embassy_approval",
        target_country_id=country_id,
        target_embassy_id=str(embassy["id"]),
        government_position=position,
        government_country_id=country_id,
        request_status="pending_approval",
        verification_status="verified",
    )
    preapproval = await store.find_preapproval(str(embassy["id"]), str(profile_value(profile, "id") or profile_value(profile, "userId") or ""))
    if preapproval:
        await store.consume_preapproval(str(preapproval["id"]), request_id)
        await store.set_flow_state(request_id, "auto_approved_preapproval", preapproval_id=str(preapproval["id"]), government_auto_approved=True, request_status="approved")
        await EmbassyAccessService(database).grant(applicant.guild, applicant, embassy, actor_id=int(preapproval["diplomat_discord_id"]), assignment_type="foreign_diplomat")
        if channel:
            await channel.send("🤝 **Pre-approval matched!** Your embassy access has been granted without another approval step.")
        await close_request_thread(channel, "Pre-approved embassy access granted.")
        return
    if position in {"President", "Vice President", "Minister of Foreign Affairs"}:
        await store.set_flow_state(request_id, "auto_approved_government_official", government_auto_approved=True, request_status="approved")
        await EmbassyAccessService(database).grant(applicant.guild, applicant, embassy, actor_id=None, assignment_type="foreign_diplomat")
        await store.log_audit(
            actor=applicant.id, action="GOVERNMENT_OFFICIAL_AUTO_APPROVED", target_type="request", target_id=request_id,
            embassy_id=str(embassy["id"]), result="SUCCESS", metadata={"position": position},
        )
        if channel:
            await channel.send(f"🟢 **Auto-approved.** Your verified position as **{position}** qualifies for immediate access to your own country's embassy.")
        await close_request_thread(channel, "Government official auto-approval completed.")
        return
    await post_embassy_approval_request(database, request_id, applicant, profile, embassy, channel, restricted_to_diplomats=True)


async def route_other_country(database: Database, request_id: str, applicant: discord.Member,
                              profile: dict[str, Any], embassy: dict[str, Any],
                              channel: discord.abc.Messageable | None) -> None:
    store = WorkflowStore(database)
    await store.set_flow_state(
        request_id,
        "awaiting_government_approval",
        target_country_id=str(embassy.get("country_id") or ""),
        target_embassy_id=str(embassy["id"]),
        request_status="pending_approval",
        verification_status="verified",
    )
    if channel:
        await channel.send(
            f"📨 Your request for **{embassy['country_name']} Embassy** is going to **EAM/Admin** review.\n\n"
            "Government approval is required for another country's embassy."
        )
    await post_embassy_approval_request(database, request_id, applicant, profile, embassy, channel, restricted_to_diplomats=False)


async def post_embassy_approval_request(database: Database, request_id: str, applicant: discord.Member,
                                        profile: dict[str, Any], embassy: dict[str, Any],
                                        channel: discord.abc.Messageable | None,
                                        restricted_to_diplomats: bool) -> None:
    discord_channel = applicant.guild.get_channel(int(embassy["channel_id"]))
    if not isinstance(discord_channel, discord.TextChannel):
        if channel:
            await channel.send("⚠️ The embassy channel is unavailable; EAM/Admin needs to reconcile this embassy.")
        return
    store = WorkflowStore(database)
    mentions: list[str] = []
    members = await store.active_embassy_members(str(embassy["id"])) if restricted_to_diplomats else []
    for member_row in members:
        member = applicant.guild.get_member(int(member_row["discord_user_id"]))
        if member:
            mentions.append(member.mention)
    if not restricted_to_diplomats:
        role_mentions = []
        for role_name in [x.strip() for x in settings.government_notify_role_names.split(",") if x.strip()]:
            role = discord.utils.find(lambda r: r.name.casefold() == role_name.casefold(), applicant.guild.roles)
            if role:
                role_mentions.append(role.mention)
        mentions.extend(role_mentions)
    embed = profile_embed(profile, title="📨 Embassy Access Request")
    embed.add_field(name="Embassy", value=str(embassy["country_name"]), inline=True)
    embed.add_field(name="Approval Route", value="Embassy diplomats" if restricted_to_diplomats else "EAM/Admin", inline=True)
    view = EmbassyApprovalView(database, request_id, applicant.id, restricted_to_diplomats=restricted_to_diplomats)
    message = await discord_channel.send(
        content=" ".join(dict.fromkeys(mentions)) or None,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
    )
    await store.set_flow_state(request_id, "awaiting_embassy_approval" if restricted_to_diplomats else "awaiting_government_approval",
                               approval_message_id=message.id, request_log_message_id=message.id)
    await store.log_audit(
        actor=applicant.id, action="EMBASSY_REQUEST_SENT", target_type="request", target_id=request_id,
        embassy_id=str(embassy["id"]), result="PENDING", metadata={"approval_route": "diplomats" if restricted_to_diplomats else "government"},
    )


class EmbassyApprovalView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant_id: int, *, restricted_to_diplomats: bool) -> None:
        super().__init__(timeout=None)
        self.database = database
        self.request_id = request_id
        self.applicant_id = applicant_id
        self.restricted_to_diplomats = restricted_to_diplomats

    async def _allowed(self, member: discord.Member) -> bool:
        if self.restricted_to_diplomats:
            request = await WorkflowStore(self.database).fetch_request(self.request_id)
            if not request or not request.get("target_embassy_id"):
                return False
            assignments = await WorkflowStore(self.database).active_assignments_for_user(member.id)
            return any(str(a["embassy_id"]) == str(request["target_embassy_id"]) for a in assignments)
        return is_government(member)

    async def _decide(self, interaction: discord.Interaction, approved: bool, reason: str | None = None) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("This action is only available in the embassy server.", ephemeral=True)
            return
        if not await self._allowed(interaction.user):
            await interaction.response.send_message("🔐 You are not authorized to decide this request.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        store = WorkflowStore(self.database)
        request = await store.fetch_request(self.request_id)
        if not request or request.get("request_status") not in {"pending_approval"}:
            await interaction.followup.send("This request has already been decided.", ephemeral=True)
            return
        embassy_id = str(request.get("target_embassy_id") or request.get("embassy_id") or "")
        embassy = await self.database.fetch_embassy(embassy_id)
        applicant = interaction.guild.get_member(int(request["applicant_discord_id"]))
        if applicant is None:
            try:
                applicant = await interaction.guild.fetch_member(int(request["applicant_discord_id"]))
            except (discord.NotFound, discord.HTTPException):
                applicant = None
        if not embassy or applicant is None:
            await interaction.followup.send("⚠️ The applicant or embassy could not be found. EAM/Admin should reconcile this request.", ephemeral=True)
            return
        if approved:
            await store.set_flow_state(self.request_id, "approved", request_status="approved", government_auto_approved=False)
            await EmbassyAccessService(self.database).grant(interaction.guild, applicant, embassy, actor_id=interaction.user.id, assignment_type="foreign_diplomat")
            await store.log_audit(
                actor=interaction.user.id, action="EMBASSY_REQUEST_APPROVED", target_type="request", target_id=self.request_id,
                embassy_id=embassy_id, result="APPROVED", metadata={"applicant_id": applicant.id},
            )
            message = f"✅ **Approved by {interaction.user.mention}.** {applicant.mention} now has access to **{embassy['country_name']} Embassy**."
        else:
            await store.set_flow_state(self.request_id, "rejected", request_status="rejected")
            await store.log_audit(
                actor=interaction.user.id, action="EMBASSY_REQUEST_REJECTED", target_type="request", target_id=self.request_id,
                embassy_id=embassy_id, result="REJECTED", metadata={"reason": reason},
            )
            message = f"❌ **Declined by {interaction.user.mention}.** {applicant.mention} was not granted access to **{embassy['country_name']} Embassy**."
        if interaction.message:
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True
            await interaction.message.edit(content=message, view=self)
        await interaction.followup.send("Decision recorded. The request controls are now locked.", ephemeral=True)

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id="rajdoot:request:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, True)

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger, custom_id="rajdoot:request:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._decide(interaction, False)


async def close_request_thread(channel: discord.abc.Messageable | None, note: str) -> None:
    if isinstance(channel, discord.Thread):
        await channel.send(f"🔒 {note}")
        try:
            await channel.edit(archived=True, locked=True, reason="RAJDOOT request completed")
        except (discord.Forbidden, discord.HTTPException):
            pass


class EmbassyRequestCommands(app_commands.Group):
    def __init__(self, database: Database) -> None:
        super().__init__(name="embassy", description="Embassy access request workflow")
        self.database = database
        self.store = WorkflowStore(database)

    @app_commands.command(name="request", description="Start the Embassy Access Request verification flow")
    async def request(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in the embassy server.", ephemeral=True)
            return
        existing = await self.store.fetch_open_for_applicant(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                f"⏳ You already have an active embassy request (`{existing['id']}`). Continue in your existing request thread.", ephemeral=True
            )
            return
        channel = interaction.guild.get_channel(settings.request_channel_id or 0)
        if not isinstance(channel, discord.TextChannel):
            if settings.request_category_id:
                category = interaction.guild.get_channel(settings.request_category_id)
                channel = next((c for c in getattr(category, "channels", []) if isinstance(c, discord.TextChannel)), None)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("⚠️ No request channel is configured. EAM/Admin must set REQUEST_CHANNEL_ID.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        request = await self.store.create_request(interaction.user.id)
        try:
            thread = await channel.create_thread(
                name=f"embassy-request-{interaction.user.display_name}"[:100],
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=10080,
                reason="RAJDOOT Embassy Access Request",
            )
            await thread.add_user(interaction.user)
        except Exception:
            await self.store.set_flow_state(str(request["id"]), "thread_creation_failed", request_status="failed")
            raise
        await self.store.set_flow_state(str(request["id"]), "profile_pending", request_thread_id=thread.id)
        await thread.send(
            embed=discord.Embed(
                title="🏛️ Embassy Access Request",
                description=(
                    "Welcome. This private request will verify your WarEra identity before we discuss embassy access.\n\n"
                    "First, send your **WarEra in-game profile link**."
                ),
                colour=discord.Colour.blurple(),
            ),
            view=StartEmbassyFlowView(self.database, str(request["id"]), thread),
        )
        await thread.send("🌐 Need the profile page? Use **Open WarEra** below. The tutorials are there too.", view=OpenWarEraView())
        await self.store.log_audit(
            actor=interaction.user.id, action="EMBASSY_REQUEST_STARTED", target_type="request", target_id=str(request["id"]),
            embassy_id=None, result="CREATED", metadata={"thread_id": thread.id},
        )
        await interaction.followup.send(f"✅ Your private embassy request thread is ready: {thread.mention}", ephemeral=True)

    @app_commands.command(name="status", description="Show your current Embassy Access Request status")
    async def status(self, interaction: discord.Interaction) -> None:
        request = await self.store.fetch_open_for_applicant(interaction.user.id)
        if request is None:
            request = await self.store.fetch_request(str((await self.database.fetch_latest_request_for_applicant(interaction.user.id) or {}).get("id", ""))) if await self.database.fetch_latest_request_for_applicant(interaction.user.id) else None
        if request is None:
            await interaction.response.send_message("You do not have an embassy request yet.", ephemeral=True)
            return
        embed = discord.Embed(title="📨 Embassy Request Status", colour=discord.Colour.blurple())
        embed.add_field(name="Stage", value=str(request.get("flow_stage", "unknown")).replace("_", " ").title(), inline=True)
        embed.add_field(name="Request", value=f"`{request['id']}`", inline=True)
        embed.add_field(name="Verification", value=str(request.get("verification_status", "pending")).title(), inline=True)
        attempts = request.get("verification_attempts") or 0
        embed.add_field(name="Company Checks", value=f"{attempts}/5", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
