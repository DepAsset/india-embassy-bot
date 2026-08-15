from __future__ import annotations

import hashlib
import re
import secrets
import string
from typing import Any

import discord
from discord import app_commands

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.embassy_access import EmbassyAccessService, is_government
from rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner
from rajdoot.warera import WarEraClient, detect_government_position
from rajdoot.workflow_store import WorkflowStore


OTP_ALPHABET = string.ascii_uppercase + string.digits


def otp() -> str:
    return "".join(secrets.choice(OTP_ALPHABET) for _ in range(6))


def otp_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def warera_id(url: str) -> str | None:
    match = re.search(r"/user/([A-Za-z0-9_-]+)", url.strip())
    return match.group(1) if match else None


def nested(profile: dict[str, Any], *paths: str) -> Any:
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


def country(profile: dict[str, Any]) -> tuple[str | None, str | None]:
    value = nested(profile, "country", "countryName", "infos.country", "citizenship")
    if isinstance(value, dict):
        return str(value.get("id") or value.get("countryId") or "") or None, str(value.get("name") or "") or None
    country_id = nested(profile, "countryId", "infos.countryId", "citizenshipId")
    return (str(country_id) if country_id else None, str(value) if value else None)


def profile_embed(profile: dict[str, Any], title: str = "WarEra Verification Complete") -> discord.Embed:
    country_id, country_name = country(profile)
    position = detect_government_position(profile) or "None"
    name = nested(profile, "username", "name", "displayName") or "Unknown"
    embed = discord.Embed(title=f"✅ {title}", colour=discord.Colour.green())
    embed.description = "Your WarEra identity and company ownership have been successfully verified."
    embed.add_field(name="Player", value=str(name), inline=True)
    embed.add_field(name="Country", value=str(country_name or country_id or "Unknown"), inline=True)
    embed.add_field(name="Official Status", value=position, inline=True)
    return embed


class EmbassyStartView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, thread: discord.Thread) -> None:
        super().__init__(timeout=None)
        self.database = database
        self.request_id = request_id
        self.thread = thread

    @discord.ui.button(label="Submit WarEra Profile", emoji="🔗", style=discord.ButtonStyle.primary, custom_id="rajdoot:embassy:start_profile")
    async def submit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ProfileModal(self.database, self.request_id, self.thread))


class ProfileModal(discord.ui.Modal, title="WarEra Profile"):
    profile_url = discord.ui.TextInput(
        label="WarEra profile link",
        placeholder="https://app.warera.io/user/...",
        max_length=300,
        required=True,
    )

    def __init__(self, database: Database, request_id: str, thread: discord.Thread) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.request_id = request_id
        self.thread = thread

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = warera_id(str(self.profile_url.value))
        if not user_id:
            await interaction.followup.send("❌ Please paste a valid WarEra profile URL.", ephemeral=True)
            return
        client = WarEraClient(settings)
        try:
            profile = await client.get_full_profile(user_id)
        except Exception:
            await interaction.followup.send("⚠️ WarEra could not be reached. Please try again in a moment.", ephemeral=True)
            return
        if profile is None:
            await interaction.followup.send("❌ That WarEra profile could not be found.", ephemeral=True)
            return

        code = otp()
        store = WorkflowStore(self.database)
        await store.issue_otp(self.request_id, otp_hash(code))
        country_id, country_name = country(profile.raw)
        position = detect_government_position(profile.raw)
        await store.set_flow_state(
            self.request_id,
            "company_verification",
            warera_user_id=user_id,
            warera_profile_snapshot=profile.raw,
            government_position=position,
            government_country_id=country_id,
            target_country_id=country_id,
        )
        companies_url = str(self.profile_url.value).rstrip("/") + "/companies"
        embed = discord.Embed(
            title="🔐 WarEra Company Verification",
            description=(
                "Rename **one of your WarEra companies** to this code:\n\n"
                f"```{code}```\n"
                "You have **5 verification attempts**. The controls stay active after a failed check."
            ),
            colour=discord.Colour.blurple(),
        )
        view = CompanyView(self.database, self.request_id, interaction.user.id, user_id, code, companies_url)
        await self.thread.send(embed=embed, view=view)
        await self.thread.send(
            f"🔎 Profile loaded: **{nested(profile.raw, 'username', 'name', 'displayName') or 'WarEra player'}**\n"
            f"🌍 Country detected: **{country_name or country_id or 'Unknown'}**\n"
            f"🏛️ Official status: **{position or 'None'}**\n\n"
            "Take your time — diplomacy is one of the few places where renaming a company counts as paperwork. 😄"
        )
        await interaction.followup.send("✅ Profile verified. Continue inside your private request thread.", ephemeral=True)


class CompanyView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant_id: int, warera_user_id: str, code: str, companies_url: str) -> None:
        super().__init__(timeout=1800)
        self.database = database
        self.request_id = request_id
        self.applicant_id = applicant_id
        self.warera_user_id = warera_user_id
        self.code = code
        self.add_item(discord.ui.Button(label="Open Your Companies", emoji="🏢", style=discord.ButtonStyle.link, url=companies_url))
        copy = discord.ui.Button(label="Copy OTP", emoji="📋", style=discord.ButtonStyle.secondary, custom_id=f"rajdoot:otp:copy:{request_id}")
        copy.callback = self.copy
        self.add_item(copy)
        verify = discord.ui.Button(label="Verify Companies", emoji="🔎", style=discord.ButtonStyle.success, custom_id=f"rajdoot:otp:verify:{request_id}")
        verify.callback = self.verify
        self.add_item(verify)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.applicant_id:
            await interaction.response.send_message("🔐 This verification belongs to another applicant.", ephemeral=True)
            return False
        return True

    async def copy(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"```{self.code}```\n📋 Copy the code above.", ephemeral=True)

    async def verify(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send("🔍 Checking your company... please give RAJDOOT a moment. ☕", ephemeral=True)
        try:
            matched = await WarEraClient(settings).verify_company_otp(self.warera_user_id, self.code)
        except Exception:
            await interaction.followup.send("⚠️ WarEra company data could not be checked. This attempt was not consumed.", ephemeral=True)
            return
        status, request = await WorkflowStore(self.database).record_company_attempt(self.request_id, matched)
        if status == "verified":
            await interaction.followup.send("✅ WarEra Company Verification Complete. Opening embassy selection below.", ephemeral=True)
            await send_embassy_selection(self.database, self.request_id, interaction.channel)
        elif status == "invalid":
            attempts = int((request or {}).get("verification_attempts") or 0)
            await interaction.followup.send(f"❌ OTP not found in your companies. Attempt **{attempts}/5** used. Rename the company and try again.", ephemeral=True)
        elif status == "max_attempts":
            await interaction.followup.send("🛑 Five attempts failed. The request is halted and EAM/Admin has been flagged.", ephemeral=True)
            await interaction.channel.send("🚨 **Embassy verification halted.** EAM/Admin review required.")
        elif status == "expired":
            await interaction.followup.send("⌛ The OTP expired. Start a fresh request for a new code.", ephemeral=True)
        else:
            await interaction.followup.send("This request is already closed.", ephemeral=True)


class EmbassySelectionView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant: discord.Member, profile: dict[str, Any]) -> None:
        super().__init__(timeout=None)
        self.database = database
        self.request_id = request_id
        self.applicant = applicant
        self.profile = profile
        _, country_name = country(profile)
        label = f"{country_name or 'Your Country'} Embassy"[:80]
        own = discord.ui.Button(label=label, emoji="🏛️", style=discord.ButtonStyle.primary, custom_id=f"rajdoot:embassy:own:{request_id}")
        own.callback = self.own
        self.add_item(own)
        other = discord.ui.Button(label="Want to Join another Embassy", emoji="🌍", style=discord.ButtonStyle.secondary, custom_id=f"rajdoot:embassy:other:{request_id}")
        other.callback = self.other
        self.add_item(other)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.applicant.id:
            await interaction.response.send_message("This embassy selection belongs to another applicant.", ephemeral=True)
            return False
        return True

    async def own(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        embassies = await self.database.fetch_active_embassies()
        country_id, country_name = country(self.profile)
        own = next((e for e in embassies if str(e.get("country_id") or "").casefold() == str(country_id or "").casefold() or str(e.get("country_name") or "").casefold() == str(country_name or "").casefold()), None)
        store = WorkflowStore(self.database)
        if own:
            assignments = await store.active_assignments_for_user(self.applicant.id)
            if any(str(a["embassy_id"]) == str(own["id"]) for a in assignments):
                await interaction.followup.send(f"ℹ️ You already are a diplomat in **{own['country_name']} Embassy**. I am keeping this request open so you can choose another embassy.", ephemeral=True)
                return
        await process_embassy_choice(self.database, self.request_id, self.applicant, self.profile, own, own_country=True, channel=interaction.channel)

    async def other(self, interaction: discord.Interaction) -> None:
        embassies = await self.database.fetch_active_embassies()
        if not embassies:
            await interaction.response.send_message("There are no active embassies to choose from.", ephemeral=True)
            return
        select = discord.ui.Select(
            placeholder="Choose another embassy",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=str(e["country_name"])[:100], value=str(e["id"])) for e in embassies[:25]],
        )
        async def choose(inner: discord.Interaction) -> None:
            if inner.user.id != self.applicant.id:
                await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                return
            await inner.response.defer(ephemeral=True, thinking=True)
            embassy = next((e for e in embassies if str(e["id"]) == select.values[0]), None)
            if not embassy:
                await inner.followup.send("Embassy not found.", ephemeral=True)
                return
            await process_embassy_choice(self.database, self.request_id, self.applicant, self.profile, embassy, own_country=False, channel=inner.channel)
        select.callback = choose
        view = discord.ui.View(timeout=300)
        view.add_item(select)
        await interaction.response.send_message("🌍 Choose the embassy you want EAM/Admin to review:", view=view, ephemeral=True)


async def send_embassy_selection(database: Database, request_id: str, channel: discord.abc.Messageable | None) -> None:
    if channel is None:
        return
    store = WorkflowStore(database)
    request = await store.fetch_request(request_id)
    if not request:
        return
    guild = getattr(channel, "guild", None)
    if guild is None:
        return
    applicant = guild.get_member(int(request["applicant_discord_id"]))
    if applicant is None:
        return
    profile = request.get("warera_profile_snapshot") or {}
    await store.set_flow_state(request_id, "embassy_selection")
    embed = profile_embed(profile)
    embed.title = "🏛️ Embassy Access"
    embed.description = f"Which Embassy would you like to join, {applicant.mention}?"
    await channel.send(embed=embed, view=EmbassySelectionView(database, request_id, applicant, profile))


async def find_or_create_embassy(database: Database, guild: discord.Guild, country_id: str | None, country_name: str | None) -> dict[str, Any] | None:
    embassies = await database.fetch_active_embassies()
    existing = next((e for e in embassies if str(e.get("country_id") or "").casefold() == str(country_id or "").casefold() or str(e.get("country_name") or "").casefold() == str(country_name or "").casefold()), None)
    if existing:
        return existing
    if not country_name:
        return None

    category = None
    for e in embassies:
        channel = guild.get_channel(int(e["channel_id"])) if e.get("channel_id") else None
        if isinstance(channel, discord.TextChannel) and channel.category:
            category = channel.category
            break
    if category is None:
        category = discord.utils.find(lambda c: c.name.casefold().startswith("embassy"), guild.categories)
    if category is None:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True)
        category = await guild.create_category("Embassy 1", overwrites=overwrites, reason="RAJDOOT new embassy")

    slug = re.sub(r"[^a-z0-9]+", "-", country_name.casefold()).strip("-")[:90] or "embassy"
    channel = await guild.create_text_channel(
        slug,
        category=category,
        reason="RAJDOOT new embassy creation",
        default_auto_archive_duration=10080,
    )

    connection = database._connection
    if connection is None:
        raise RuntimeError("Database connection unavailable")
    async with connection.transaction():
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                insert into embassies (country_id, country_name, channel_id, channel_name, category_id, status)
                values (%s, %s, %s, %s, %s, 'active') returning *
                """,
                (country_id, country_name, channel.id, channel.name, category.id),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Embassy record creation failed")
            created = dict(row)

    active_after = await database.fetch_active_embassies()
    plan = EmbassyLayoutPlanner.plan(active_after)
    await EmbassyDiscordOrganizer().apply_plan(guild, plan)
    return created


async def process_embassy_choice(database: Database, request_id: str, applicant: discord.Member,
                                 profile: dict[str, Any], embassy: dict[str, Any] | None,
                                 *, own_country: bool, channel: discord.abc.Messageable | None) -> None:
    store = WorkflowStore(database)
    country_id, country_name = country(profile)
    position = detect_government_position(profile)
    if embassy is None and own_country:
        embassy = await find_or_create_embassy(database, applicant.guild, country_id, country_name)
        if embassy and channel:
            await channel.send(f"🏗️ **{embassy['country_name']} Embassy** has been created/revived. EAM/Admin has been notified.")
            await notify_government_roles(applicant.guild, channel, embassy)
        if embassy is None:
            await store.set_flow_state(request_id, "embassy_creation_pending", request_status="pending_approval")
            return
    if embassy is None:
        await store.set_flow_state(request_id, "embassy_selection_failed", request_status="failed")
        return

    await store.set_flow_state(
        request_id,
        "awaiting_embassy_approval" if own_country else "awaiting_government_approval",
        target_country_id=str(embassy.get("country_id") or country_id or ""),
        target_embassy_id=str(embassy["id"]),
        government_position=position,
        government_country_id=country_id,
        verification_status="verified",
        request_status="pending_approval",
    )

    warera_user_id = str(request_profile_id(profile) or "")
    preapproval = await store.find_preapproval(str(embassy["id"]), warera_user_id) if warera_user_id else None
    if preapproval:
        await store.consume_preapproval(str(preapproval["id"]), request_id)
        await store.set_flow_state(request_id, "approved_preapproval", request_status="approved", government_auto_approved=True, preapproval_id=str(preapproval["id"]))
        await EmbassyAccessService(database).grant(applicant.guild, applicant, embassy, actor_id=int(preapproval["diplomat_discord_id"]), assignment_type="foreign_diplomat")
        await store.log_audit(actor=applicant.id, action="PREAPPROVAL_ACCESS_GRANTED", target_type="request", target_id=request_id, embassy_id=str(embassy["id"]), result="APPROVED")
        if channel:
            await channel.send("🤝 **Pre-approval matched!** Your access has been granted without another approval step.")
        await close_thread(channel)
        return

    if own_country and position in {"President", "Vice President", "Minister of Foreign Affairs"}:
        await store.set_flow_state(request_id, "approved_government_official", request_status="approved", government_auto_approved=True)
        await EmbassyAccessService(database).grant(applicant.guild, applicant, embassy, actor_id=None, assignment_type="foreign_diplomat")
        await store.log_audit(actor=applicant.id, action="GOVERNMENT_OFFICIAL_AUTO_APPROVED", target_type="request", target_id=request_id, embassy_id=str(embassy["id"]), result="APPROVED", metadata={"position": position})
        if channel:
            await channel.send(f"🟢 **Auto-approved.** Your verified **{position}** status grants immediate access to your own country's embassy.")
        await close_thread(channel)
        return

    if own_country:
        diplomats = await store.active_embassy_members(str(embassy["id"]))
        if not diplomats:
            await store.set_flow_state(
                request_id,
                "approved_new_or_unstaffed_embassy",
                request_status="approved",
                government_auto_approved=True,
                target_country_id=str(embassy.get("country_id") or country_id or ""),
                target_embassy_id=str(embassy["id"]),
            )
            await EmbassyAccessService(database).grant(
                applicant.guild,
                applicant,
                embassy,
                actor_id=None,
                assignment_type="foreign_diplomat",
            )
            await store.log_audit(
                actor=applicant.id,
                action="UNSTAFFED_EMBASSY_AUTO_APPROVED",
                target_type="request",
                target_id=request_id,
                embassy_id=str(embassy["id"]),
                result="APPROVED",
                metadata={"reason": "no_active_diplomats"},
            )
            if channel:
                await channel.send(
                    f"🟢 **{embassy['country_name']} Embassy access granted.** "
                    "This embassy currently has no active diplomats, so no approval step was required."
                )
            await close_thread(channel)
            return


    await send_approval_card(database, request_id, applicant, profile, embassy, own_country=own_country)
    if channel:
        await channel.send("📨 Your request has been sent for approval. You can leave this thread open; the approval controls remain active in the embassy.")


def request_profile_id(profile: dict[str, Any]) -> str | None:
    return str(nested(profile, "id", "userId") or "") or None


async def notify_government_roles(guild: discord.Guild, channel: discord.abc.Messageable, embassy: dict[str, Any]) -> None:
    mentions = []
    for name in [x.strip() for x in settings.government_notify_role_names.split(",") if x.strip()]:
        role = discord.utils.find(lambda r: r.name.casefold() == name.casefold(), guild.roles)
        if role:
            mentions.append(role.mention)
    if mentions:
        await channel.send(
            f"📣 **New Embassy Alert — {embassy['country_name']} Embassy**\n\n"
            + " ".join(mentions)
            + "\n\nA new mission has been created/revived and needs government attention.",
            allowed_mentions=discord.AllowedMentions(roles=True),
        )


async def send_approval_card(database: Database, request_id: str, applicant: discord.Member,
                             profile: dict[str, Any], embassy: dict[str, Any], *, own_country: bool) -> None:
    channel = applicant.guild.get_channel(int(embassy["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return
    store = WorkflowStore(database)
    members = await store.active_embassy_members(str(embassy["id"])) if own_country else []
    mentions: list[str] = []
    for row in members:
        member = applicant.guild.get_member(int(row["discord_user_id"]))
        if member:
            mentions.append(member.mention)
    if not own_country:
        for name in [x.strip() for x in settings.government_notify_role_names.split(",") if x.strip()]:
            role = discord.utils.find(lambda r: r.name.casefold() == name.casefold(), applicant.guild.roles)
            if role:
                mentions.append(role.mention)
    embed = profile_embed(profile, "📨 Embassy Access Request")
    embed.add_field(name="Embassy", value=str(embassy["country_name"]), inline=True)
    embed.add_field(name="Approval", value="Embassy diplomats" if own_country else "EAM/Admin", inline=True)
    view = PersistentApprovalView(database, request_id, applicant.id, own_country=own_country)
    message = await channel.send(
        content=" ".join(dict.fromkeys(mentions)) or None,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(users=True, roles=True),
    )
    await store.set_flow_state(request_id, "awaiting_embassy_approval" if own_country else "awaiting_government_approval", approval_message_id=message.id)
    await store.log_audit(actor=applicant.id, action="EMBASSY_REQUEST_SENT", target_type="request", target_id=request_id, embassy_id=str(embassy["id"]), result="PENDING", metadata={"route": "diplomats" if own_country else "government"})


class PersistentApprovalView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant_id: int, *, own_country: bool) -> None:
        super().__init__(timeout=None)
        self.database = database
        self.request_id = request_id
        self.applicant_id = applicant_id
        self.own_country = own_country
        approve = discord.ui.Button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"rajdoot:approve:{request_id}")
        decline = discord.ui.Button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"rajdoot:decline:{request_id}")
        approve.callback = self.approve
        decline.callback = self.decline
        self.add_item(approve)
        self.add_item(decline)

    async def authorized(self, member: discord.Member) -> bool:
        if self.own_country:
            request = await WorkflowStore(self.database).fetch_request(self.request_id)
            if not request or not request.get("target_embassy_id"):
                return False
            return any(str(a["embassy_id"]) == str(request["target_embassy_id"]) for a in await WorkflowStore(self.database).active_assignments_for_user(member.id))
        return is_government(member)

    async def decide(self, interaction: discord.Interaction, approved: bool) -> None:
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.response.send_message("This action is only available in the embassy server.", ephemeral=True)
            return
        if interaction.user.id == self.applicant_id:
            await interaction.response.send_message("🔐 The applicant cannot approve or decline their own embassy request.", ephemeral=True)
            return
        if not await self.authorized(interaction.user):
            await interaction.response.send_message("🔐 You are not authorized to decide this request.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        store = WorkflowStore(self.database)
        request = await store.fetch_request(self.request_id)
        if not request or request.get("request_status") != "pending_approval":
            await interaction.followup.send("This request has already been decided.", ephemeral=True)
            return
        embassy_id = str(request.get("target_embassy_id") or "")
        embassy = await self.database.fetch_embassy(embassy_id)
        applicant = interaction.guild.get_member(self.applicant_id)
        if applicant is None:
            applicant = await interaction.guild.fetch_member(self.applicant_id)
        if not embassy:
            await interaction.followup.send("⚠️ Embassy record missing; EAM/Admin should reconcile it.", ephemeral=True)
            return
        if approved:
            await store.set_flow_state(self.request_id, "approved", request_status="approved")
            await EmbassyAccessService(self.database).grant(interaction.guild, applicant, embassy, actor_id=interaction.user.id, assignment_type="foreign_diplomat")
            await store.log_audit(actor=interaction.user.id, action="EMBASSY_REQUEST_APPROVED", target_type="request", target_id=self.request_id, embassy_id=embassy_id, result="APPROVED")
            result_text = f"✅ **Approved by {interaction.user.mention}.** {applicant.mention} now has access to **{embassy['country_name']} Embassy**."
        else:
            await store.set_flow_state(self.request_id, "rejected", request_status="rejected")
            await store.log_audit(actor=interaction.user.id, action="EMBASSY_REQUEST_REJECTED", target_type="request", target_id=self.request_id, embassy_id=embassy_id, result="REJECTED")
            result_text = f"❌ **Declined by {interaction.user.mention}.** {applicant.mention} was not granted access to **{embassy['country_name']} Embassy**."
        if interaction.message:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.message.edit(content=result_text, view=self)
        await interaction.followup.send("Decision recorded. These controls are now locked.", ephemeral=True)
        if request.get("request_thread_id"):
            thread = interaction.guild.get_thread(int(request["request_thread_id"]))
            await close_thread(thread)

    async def approve(self, interaction: discord.Interaction) -> None:
        await self.decide(interaction, True)

    async def decline(self, interaction: discord.Interaction) -> None:
        await self.decide(interaction, False)


async def close_thread(thread: discord.Thread | discord.abc.Messageable | None) -> None:
    if not isinstance(thread, discord.Thread):
        return
    try:
        await thread.send("🔒 This embassy request is complete. Thank you for your patience.")
        await thread.edit(archived=True, locked=True, reason="RAJDOOT request completed")
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
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
            thread_id = existing.get("request_thread_id")
            thread = interaction.guild.get_thread(int(thread_id)) if thread_id else None
            suffix = f" Continue here: {thread.mention}" if thread else " Continue in your existing request thread."
            await interaction.response.send_message(f"⏳ You already have an active embassy request.{suffix}", ephemeral=True)
            return
        parent = interaction.guild.get_channel(settings.request_channel_id or 0)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message("⚠️ REQUEST_CHANNEL_ID is not configured to a text channel.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        request = await self.store.create_request(interaction.user.id)
        thread = await parent.create_thread(
            name=f"embassy-request-{interaction.user.display_name}"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
            auto_archive_duration=10080,
            reason="RAJDOOT Embassy Access Request",
        )
        await thread.add_user(interaction.user)
        await self.store.set_flow_state(str(request["id"]), "profile_pending", request_thread_id=thread.id)
        await thread.send(
            embed=discord.Embed(
                title="🏛️ Embassy Access Request",
                description="Welcome. This private request will verify your WarEra identity before embassy access is discussed.\n\nFirst, send your **WarEra in-game profile link**.",
                colour=discord.Colour.blurple(),
            ),
            view=EmbassyStartView(self.database, str(request["id"]), thread),
        )
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Open WarEra", emoji="🌐", style=discord.ButtonStyle.link, url="https://app.warera.io/user/"))
        await thread.send("Need the profile page? Open WarEra here:", view=view)
        await self.store.log_audit(actor=interaction.user.id, action="EMBASSY_REQUEST_STARTED", target_type="request", target_id=str(request["id"]), embassy_id=None, result="CREATED", metadata={"thread_id": thread.id})
        await interaction.followup.send(f"✅ Your private embassy request thread is ready: {thread.mention}", ephemeral=True)

    @app_commands.command(name="status", description="Show your current Embassy Access Request status")
    async def status(self, interaction: discord.Interaction) -> None:
        request = await self.store.fetch_open_for_applicant(interaction.user.id)
        if not request:
            await interaction.response.send_message("You do not have an active embassy request.", ephemeral=True)
            return
        embed = discord.Embed(title="📨 Embassy Request Status", colour=discord.Colour.blurple())
        embed.add_field(name="Stage", value=str(request.get("flow_stage", "unknown")).replace("_", " ").title(), inline=True)
        embed.add_field(name="Verification", value=str(request.get("verification_status", "pending")).title(), inline=True)
        embed.add_field(name="Company Checks", value=f"{request.get('verification_attempts', 0)}/5", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
