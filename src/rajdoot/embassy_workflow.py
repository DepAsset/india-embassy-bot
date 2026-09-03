from __future__ import annotations

import asyncio
import hashlib
import logging
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
from rajdoot.layout_service import EmbassyLayoutService
from rajdoot.warera import WarEraClient, detect_government_position
from rajdoot.workflow_store import WorkflowStore

logger = logging.getLogger(__name__)
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
        cid = value.get("_id") or value.get("id") or value.get("countryId")
        name = value.get("name") or value.get("countryName")
        return (str(cid) if cid else None, str(name) if name else None)
    cid = nested(profile, "countryId", "infos.countryId", "citizenshipId")
    return (str(cid) if cid else None, str(value) if value else None)


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


async def resolve_profile_country(profile: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    country_id, country_name = country(profile)
    if country_name or not country_id:
        return profile, country_id, country_name
    try:
        resolved = await asyncio.wait_for(WarEraClient(settings).get_country_by_id(country_id), timeout=10)
    except (asyncio.TimeoutError, Exception):
        logger.exception("Country lookup failed for country %s", country_id)
        return profile, country_id, None
    if isinstance(resolved, dict) and resolved.get("name"):
        canonical_id = str(resolved.get("_id") or resolved.get("id") or country_id)
        canonical_name = str(resolved["name"])
        profile = dict(profile)
        profile["country"] = {"id": canonical_id, "name": canonical_name}
        profile["countryName"] = canonical_name
        return profile, canonical_id, canonical_name
    return profile, country_id, None


class EmbassyStartView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, thread: discord.Thread) -> None:
        super().__init__(timeout=None)
        self.database, self.request_id, self.thread = database, request_id, thread
        button = discord.ui.Button(label="Submit WarEra Profile", emoji="🔗", style=discord.ButtonStyle.primary, custom_id=f"rajdoot:embassy:start_profile:{request_id}")
        button.callback = self.submit
        self.add_item(button)

    async def submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        request = await WorkflowStore(self.database).fetch_request(self.request_id)
        if not request or int(request["applicant_discord_id"]) != interaction.user.id:
            await interaction.response.send_message("🔐 This request does not belong to you.", ephemeral=True)
            return
        thread = interaction.channel if isinstance(interaction.channel, discord.Thread) else self.thread
        await interaction.response.send_modal(ProfileModal(self.database, self.request_id, thread))


class ProfileModal(discord.ui.Modal, title="WarEra Profile"):
    profile_url = discord.ui.TextInput(label="WarEra profile link", placeholder="https://app.warera.io/user/...", max_length=300, required=True)

    def __init__(self, database: Database, request_id: str, thread: discord.Thread) -> None:
        super().__init__(timeout=300)
        self.database, self.request_id, self.thread = database, request_id, thread

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        await interaction.response.send_message("🔄 Checking your WarEra profile…", ephemeral=True)
        progress = await interaction.original_response()
        user_id = warera_id(str(self.profile_url.value))
        if not user_id:
            await progress.edit(content="❌ Please paste a valid WarEra profile URL.")
            return
        try:
            profile = await asyncio.wait_for(WarEraClient(settings).get_full_profile(user_id), timeout=20)
        except asyncio.TimeoutError:
            await progress.edit(content="⏱️ WarEra took too long to respond. Please try again.")
            return
        except Exception:
            logger.exception("WarEra profile lookup failed for request %s", self.request_id)
            await progress.edit(content="⚠️ WarEra could not be reached. Please try again in a moment.")
            return
        if profile is None:
            await progress.edit(content="❌ That WarEra profile could not be found.")
            return
        store = WorkflowStore(self.database)
        request = await store.fetch_request(self.request_id)
        if request and request.get("flow_stage") == "company_verification" and request.get("otp_expires_at"):
            expires = request["otp_expires_at"]
            if expires > __import__("datetime").datetime.now(__import__("datetime").timezone.utc):
                await progress.edit(content="ℹ️ A company verification code is already active in this request. Use the existing verification controls below.")
                return
        code = otp()
        if not await store.issue_otp(self.request_id, otp_hash(code)):
            await progress.edit(content="⚠️ This request is no longer active. Please use the dashboard to start a new request.")
            return
        profile_raw, country_id, country_name = await resolve_profile_country(profile.raw)
        position = detect_government_position(profile_raw)
        await store.set_flow_state(self.request_id, "company_verification", warera_user_id=user_id, warera_profile_snapshot=profile_raw, government_position=position, government_country_id=country_id, target_country_id=country_id)
        embed = discord.Embed(title="🔐 WarEra Company Verification", description=("Rename **one of your WarEra companies** to this code:\n\n" f"```{code}```\n" "You have **5 verification attempts**. The controls stay active after a failed check."), colour=discord.Colour.blurple())
        await self.thread.send(embed=embed, view=CompanyView(self.database, self.request_id, interaction.user.id, user_id, code, str(self.profile_url.value).rstrip("/") + "/companies"))
        await self.thread.send(f"🔎 Profile loaded: **{nested(profile_raw, 'username', 'name', 'displayName') or 'WarEra player'}**\n🌍 Country detected: **{country_name or country_id or 'Unknown'}**\n🏛️ Official status: **{position or 'None'}**\n\nTake your time — diplomacy is one of the few places where renaming a company counts as paperwork. 😄")
        await progress.edit(content="✅ Profile verified. Continue inside your private request thread.")


class CompanyView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant_id: int, warera_user_id: str, code: str | None, companies_url: str) -> None:
        super().__init__(timeout=None)
        self.database, self.request_id, self.applicant_id, self.warera_user_id, self.code = database, request_id, applicant_id, warera_user_id, code
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
        text = f"```{self.code}```\n📋 Copy the code above." if self.code else "📋 The active OTP is displayed in the verification message above."
        await interaction.response.send_message(text, ephemeral=True)

    async def verify(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🔎 Checking your company…", ephemeral=True)
        progress = await interaction.original_response()
        try:
            store = WorkflowStore(self.database)
            request = await store.fetch_request(self.request_id)
            if not request:
                await progress.edit(content="This request could not be found.")
                return
            client = WarEraClient(settings)
            if self.code:
                matched = await asyncio.wait_for(client.verify_company_otp(self.warera_user_id, self.code), timeout=25)
            else:
                matched = await asyncio.wait_for(client.verify_company_otp_hash(self.warera_user_id, str(request.get("otp_hash") or "")), timeout=25)
            status, updated = await asyncio.wait_for(store.record_company_attempt(self.request_id, matched), timeout=10)
        except asyncio.TimeoutError:
            await progress.edit(content="⏱️ Verification timed out safely. No attempt was consumed; please try again.")
            return
        except Exception:
            logger.exception("Company verification failed for request %s", self.request_id)
            await progress.edit(content="⚠️ RAJDOOT could not finish verification. No attempt was consumed; please try again.")
            return
        if status == "verified":
            await progress.edit(content="✅ WarEra Company Verification Complete. Opening embassy selection below.")
            await send_embassy_selection(self.database, self.request_id, interaction.channel)
        elif status == "already_verified":
            await progress.edit(content="ℹ️ Company verification is already complete. Use the embassy selection already posted in this request.")
        elif status == "invalid":
            await progress.edit(content=f"❌ OTP not found in your companies. Attempt **{int((updated or {}).get('verification_attempts') or 0)}/5** used. Rename the company and try again.")
        elif status == "max_attempts":
            await progress.edit(content="🛑 Five attempts failed. The request is halted and EAM/Admin has been flagged.")
            if interaction.channel:
                await interaction.channel.send("🚨 **Embassy verification halted.** EAM/Admin review required.")
            await close_thread(interaction.channel)
        elif status == "expired":
            await progress.edit(content="⌛ The OTP expired. Submit your profile again in this request for a new code.")
        else:
            await progress.edit(content="This request is already closed.")


class EmbassySelectionView(discord.ui.View):
    PAGE_SIZE = 25

    def __init__(self, database: Database, request_id: str, applicant: discord.Member, profile: dict[str, Any]) -> None:
        super().__init__(timeout=None)
        self.database, self.request_id, self.applicant, self.profile = database, request_id, applicant, profile
        self.page = 0
        _, country_name = country(profile)
        own = discord.ui.Button(label=f"{country_name or 'Your Country'} Embassy"[:80], emoji="🏛️", style=discord.ButtonStyle.primary, custom_id=f"rajdoot:embassy:own:{request_id}")
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
        await interaction.response.defer(ephemeral=True)
        embassies = await self.database.fetch_active_embassies()
        country_id, country_name = await resolve_profile_country(dict(self.profile))
        own = next((e for e in embassies if str(e.get("country_id") or "").casefold() == str(country_id or "").casefold()), None)
        if own is None and country_name:
            own = next((e for e in embassies if str(e.get("country_name") or "").casefold() == country_name.casefold()), None)
        if own:
            if any(str(a["embassy_id"]) == str(own["id"]) for a in await WorkflowStore(self.database).active_assignments_for_user(self.applicant.id)):
                await interaction.followup.send(f"ℹ️ You already are a diplomat in **{own['country_name']} Embassy**. Choose another embassy if needed.", ephemeral=True)
                return
        await process_embassy_choice(self.database, self.request_id, self.applicant, self.profile, own, own_country=True, channel=interaction.channel)

    async def other(self, interaction: discord.Interaction) -> None:
        embassies = await self.database.fetch_active_embassies()
        if not embassies:
            await interaction.response.send_message("There are no active embassies to choose from.", ephemeral=True)
            return
        max_page = max(0, (len(embassies) - 1) // self.PAGE_SIZE)
        self.page = min(self.page, max_page)
        start = self.page * self.PAGE_SIZE
        page_embassies = embassies[start:start + self.PAGE_SIZE]
        select = discord.ui.Select(placeholder=f"Choose another embassy (page {self.page + 1}/{max_page + 1})", min_values=1, max_values=1, options=[discord.SelectOption(label=str(e["country_name"])[:100], value=str(e["id"])) for e in page_embassies])

        async def choose(inner: discord.Interaction) -> None:
            if inner.user.id != self.applicant.id:
                await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                return
            await inner.response.defer(ephemeral=True)
            embassy = next((e for e in page_embassies if str(e["id"]) == select.values[0]), None)
            if not embassy:
                await inner.followup.send("Embassy not found.", ephemeral=True)
                return
            await process_embassy_choice(self.database, self.request_id, self.applicant, self.profile, embassy, own_country=False, channel=inner.channel)

        select.callback = choose
        view = discord.ui.View(timeout=300)
        view.add_item(select)
        if max_page > 0:
            previous = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=self.page >= max_page)

            async def previous_callback(inner: discord.Interaction) -> None:
                if inner.user.id != self.applicant.id:
                    await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                    return
                self.page = max(0, self.page - 1)
                await inner.response.defer(ephemeral=True)
                await self._send_other_page(inner)

            async def next_callback(inner: discord.Interaction) -> None:
                if inner.user.id != self.applicant.id:
                    await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                    return
                self.page = min(max_page, self.page + 1)
                await inner.response.defer(ephemeral=True)
                await self._send_other_page(inner)

            previous.callback = previous_callback
            next_button.callback = next_callback
            view.add_item(previous)
            view.add_item(next_button)
        await interaction.response.send_message("🌍 Choose the embassy you want EAM/Admin to review:", view=view, ephemeral=True)

    async def _send_other_page(self, interaction: discord.Interaction) -> None:
        embassies = await self.database.fetch_active_embassies()
        max_page = max(0, (len(embassies) - 1) // self.PAGE_SIZE)
        self.page = min(self.page, max_page)
        start = self.page * self.PAGE_SIZE
        page_embassies = embassies[start:start + self.PAGE_SIZE]
        select = discord.ui.Select(placeholder=f"Choose another embassy (page {self.page + 1}/{max_page + 1})", min_values=1, max_values=1, options=[discord.SelectOption(label=str(e["country_name"])[:100], value=str(e["id"])) for e in page_embassies])

        async def choose(inner: discord.Interaction) -> None:
            if inner.user.id != self.applicant.id:
                await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                return
            await inner.response.defer(ephemeral=True)
            embassy = next((e for e in page_embassies if str(e["id"]) == select.values[0]), None)
            if not embassy:
                await inner.followup.send("Embassy not found.", ephemeral=True)
                return
            await process_embassy_choice(self.database, self.request_id, self.applicant, self.profile, embassy, own_country=False, channel=inner.channel)

        select.callback = choose
        view = discord.ui.View(timeout=300)
        view.add_item(select)
        if max_page > 0:
            previous = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=self.page >= max_page)

            async def previous_callback(inner: discord.Interaction) -> None:
                if inner.user.id != self.applicant.id:
                    await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                    return
                self.page = max(0, self.page - 1)
                await inner.response.defer(ephemeral=True)
                await self._send_other_page(inner)

            async def next_callback(inner: discord.Interaction) -> None:
                if inner.user.id != self.applicant.id:
                    await inner.response.send_message("This selection belongs to another applicant.", ephemeral=True)
                    return
                self.page = min(max_page, self.page + 1)
                await inner.response.defer(ephemeral=True)
                await self._send_other_page(inner)

            previous.callback = previous_callback
            next_button.callback = next_callback
            view.add_item(previous)
            view.add_item(next_button)
        await interaction.edit_original_response(content="🌍 Choose the embassy you want EAM/Admin to review:", view=view)


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
        try:
            applicant = await guild.fetch_member(int(request["applicant_discord_id"]))
        except discord.HTTPException:
            return
    profile = request.get("warera_profile_snapshot") or {}
    profile, country_id, country_name = await resolve_profile_country(dict(profile))
    if country_name and (not request.get("warera_profile_snapshot") or country_name != country(request.get("warera_profile_snapshot") or {})[1]):
        await store.set_flow_state(request_id, "embassy_selection", warera_profile_snapshot=profile, target_country_id=country_id)
    else:
        await store.set_flow_state(request_id, "embassy_selection")
    embed = profile_embed(profile)
    embed.title = "🏛️ Embassy Access"
    embed.description = f"Which Embassy would you like to join, {applicant.mention}?"
    await channel.send(embed=embed, view=EmbassySelectionView(database, request_id, applicant, profile))


async def ensure_embassy_base_category(guild: discord.Guild) -> discord.CategoryChannel:
    categories = EmbassyDiscordOrganizer.find_embassy_categories(guild)
    if categories:
        return categories[0]
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True)
    return await guild.create_category("Embassy 1", overwrites=overwrites, reason="RAJDOOT initial embassy category")


async def find_or_create_embassy(database: Database, guild: discord.Guild, country_id: str | None, country_name: str | None) -> dict[str, Any] | None:
    existing = await database.fetch_active_embassy_by_country(country_id, country_name)
    if existing:
        return existing
    if not country_name:
        return None

    existing_embassies = await database.fetch_active_embassies()
    placeholder = {"id": "pending-new-embassy", "country_name": country_name, "channel_id": -1, "status": "active"}
    plan = EmbassyLayoutPlanner.plan(existing_embassies + [placeholder])
    await ensure_embassy_base_category(guild)
    organizer = EmbassyDiscordOrganizer()
    categories = await organizer.ensure_categories(guild, plan)
    entry = next(e for e in plan.entries if e.embassy_id == placeholder["id"])
    target_category = next(c for c in categories if EmbassyLayoutPlanner.discord_category_number(c) == entry.category_index)
    if len(target_category.channels) >= organizer.MAX_CHANNELS_PER_CATEGORY:
        raise RuntimeError(f"{target_category.name} is full. RAJDOOT will not create an embassy channel until space is available.")

    channel = await guild.create_text_channel(EmbassyDiscordOrganizer.embassy_slug(country_name), category=target_category, reason="RAJDOOT new embassy creation", default_auto_archive_duration=10080)
    try:
        created = await database.create_embassy(country_id=country_id or country_name.casefold(), country_name=country_name, channel_id=channel.id, channel_name=channel.name, category_id=target_category.id)
    except Exception:
        try:
            await channel.delete(reason="RAJDOOT failed embassy registry creation")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        raise
    if int(created.get("channel_id") or 0) != channel.id:
        try:
            await channel.delete(reason="RAJDOOT duplicate embassy creation cleanup")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
        return created
    await EmbassyLayoutService(database).synchronize(guild)
    return created


async def process_embassy_choice(database: Database, request_id: str, applicant: discord.Member, profile: dict[str, Any], embassy: dict[str, Any] | None, *, own_country: bool, channel: discord.abc.Messageable | None) -> None:
    store = WorkflowStore(database)
    profile, country_id, country_name = await resolve_profile_country(dict(profile))
    position = detect_government_position(profile)
    if embassy is None and own_country:
        embassy = await find_or_create_embassy(database, applicant.guild, country_id, country_name)
        if embassy and channel:
            await channel.send(f"🏗️ **{embassy['country_name']} Embassy** is now active. Embassy layout has been synchronized.")
            await notify_government_roles(applicant.guild, channel, embassy)
        if embassy is None:
            await store.set_flow_state(request_id, "embassy_creation_pending", request_status="pending_approval")
            return
    if embassy is None:
        await store.set_flow_state(request_id, "embassy_selection_failed", request_status="failed")
        return
    await store.set_flow_state(request_id, "routing", target_country_id=str(embassy.get("country_id") or country_id or ""), target_embassy_id=str(embassy["id"]), government_position=position, government_country_id=country_id, verification_status="verified", request_status="created", warera_profile_snapshot=profile)
    request = await store.fetch_request(request_id)
    warera_user_id = str((request or {}).get("warera_user_id") or "")
    preapproval = await store.find_preapproval(str(embassy["id"]), warera_user_id) if warera_user_id else None
    if preapproval and await store.consume_preapproval(str(preapproval["id"]), request_id):
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
    if own_country and not await store.active_embassy_diplomats(str(embassy["id"])):
        await store.set_flow_state(request_id, "approved_unstaffed_embassy", request_status="approved", government_auto_approved=True)
        await EmbassyAccessService(database).grant(applicant.guild, applicant, embassy, actor_id=None, assignment_type="foreign_diplomat")
        await store.log_audit(actor=applicant.id, action="UNSTAFFED_EMBASSY_AUTO_APPROVED", target_type="request", target_id=request_id, embassy_id=str(embassy["id"]), result="APPROVED", metadata={"reason": "no_active_foreign_diplomats"})
        if channel:
            await channel.send(f"🟢 **{embassy['country_name']} Embassy access granted.** This embassy currently has no active diplomats, so no approval step was required.")
        await close_thread(channel)
        return
    await store.set_flow_state(request_id, "awaiting_embassy_approval" if own_country else "awaiting_government_approval", request_status="pending_approval")
    sent = await send_approval_card(database, request_id, applicant, profile, embassy, own_country=own_country)
    if own_country and not sent:
        await store.set_flow_state(request_id, "approved_unstaffed_embassy", request_status="approved", government_auto_approved=True)
        await EmbassyAccessService(database).grant(applicant.guild, applicant, embassy, actor_id=None, assignment_type="foreign_diplomat")
        await store.log_audit(actor=applicant.id, action="UNSTAFFED_EMBASSY_AUTO_APPROVED", target_type="request", target_id=request_id, embassy_id=str(embassy["id"]), result="APPROVED", metadata={"reason": "no_active_foreign_diplomats_at_dispatch"})
        if channel:
            await channel.send(f"🟢 **{embassy['country_name']} Embassy access granted.** There are currently no active diplomats available to approve this request.")
        await close_thread(channel)
        return
    if channel:
        await channel.send("📨 Your request has been sent for approval. You can leave this thread open; the approval controls remain active in the embassy.")


async def notify_government_roles(guild: discord.Guild, channel: discord.abc.Messageable, embassy: dict[str, Any]) -> None:
    mentions = []
    for name in [x.strip() for x in settings.government_notify_role_names.split(",") if x.strip()]:
        role = discord.utils.find(lambda r: r.name.casefold() == name.casefold(), guild.roles)
        if role:
            mentions.append(role.mention)
    if mentions:
        await channel.send(f"📣 **New Embassy Alert — {embassy['country_name']} Embassy**\n\n" + " ".join(mentions) + "\n\nA new mission has been created/revived and needs government attention.", allowed_mentions=discord.AllowedMentions(roles=True))


async def send_approval_card(database: Database, request_id: str, applicant: discord.Member, profile: dict[str, Any], embassy: dict[str, Any], *, own_country: bool) -> bool:
    channel = applicant.guild.get_channel(int(embassy["channel_id"]))
    if not isinstance(channel, discord.TextChannel):
        return False
    store = WorkflowStore(database)
    members = await store.active_embassy_diplomats(str(embassy["id"])) if own_country else []
    if own_country and not members:
        return False
    mentions = [member.mention for row in members if (member := applicant.guild.get_member(int(row["user_discord_id"]))) is not None]
    if not own_country:
        for name in [x.strip() for x in settings.government_notify_role_names.split(",") if x.strip()]:
            role = discord.utils.find(lambda r: r.name.casefold() == name.casefold(), applicant.guild.roles)
            if role:
                mentions.append(role.mention)
    embed = profile_embed(profile, "📨 Embassy Access Request")
    embed.add_field(name="Embassy", value=str(embassy["country_name"]), inline=True)
    embed.add_field(name="Approval", value="Embassy diplomats" if own_country else "EAM/Admin", inline=True)
    message = await channel.send(content=" ".join(dict.fromkeys(mentions)) or None, embed=embed, view=PersistentApprovalView(database, request_id, applicant.id, own_country=own_country), allowed_mentions=discord.AllowedMentions(users=True, roles=True))
    await store.set_flow_state(request_id, "awaiting_embassy_approval" if own_country else "awaiting_government_approval", approval_message_id=message.id)
    await store.log_audit(actor=applicant.id, action="EMBASSY_REQUEST_SENT", target_type="request", target_id=request_id, embassy_id=str(embassy["id"]), result="PENDING", metadata={"route": "diplomats" if own_country else "government"})
    return True


class PersistentApprovalView(discord.ui.View):
    def __init__(self, database: Database, request_id: str, applicant_id: int, *, own_country: bool) -> None:
        super().__init__(timeout=None)
        self.database, self.request_id, self.applicant_id, self.own_country = database, request_id, applicant_id, own_country
        approve = discord.ui.Button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"rajdoot:approve:{request_id}")
        decline = discord.ui.Button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"rajdoot:decline:{request_id}")
        approve.callback = self.approve
        decline.callback = self.decline
        self.add_item(approve)
        self.add_item(decline)

    async def authorized(self, member: discord.Member) -> bool:
        request = await WorkflowStore(self.database).fetch_request(self.request_id)
        if not request or request.get("request_status") != "pending_approval":
            return False
        if self.own_country:
            return any(str(a["embassy_id"]) == str(request.get("target_embassy_id")) and a.get("assignment_type") == "foreign_diplomat" for a in await WorkflowStore(self.database).active_assignments_for_user(member.id))
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
        await interaction.response.send_message("🔄 Recording your decision…", ephemeral=True)
        progress = await interaction.original_response()
        try:
            store = WorkflowStore(self.database)
            request = await store.fetch_request(self.request_id)
            if not request or request.get("request_status") != "pending_approval":
                await progress.edit(content="This request has already been decided.")
                return
            embassy_id = str(request.get("target_embassy_id") or "")
            embassy = await self.database.fetch_embassy(embassy_id)
            applicant = interaction.guild.get_member(self.applicant_id) or await interaction.guild.fetch_member(self.applicant_id)
            if not embassy:
                await progress.edit(content="⚠️ Embassy record missing; EAM/Admin should reconcile it.")
                return
            decision = "approved" if approved else "rejected"
            result = await self.database.decide_embassy_request(request_id=self.request_id, actor_discord_id=interaction.user.id, decision=decision, assignment_type="foreign_diplomat" if approved else None)
            if approved:
                await EmbassyAccessService(self.database).grant(interaction.guild, applicant, embassy, actor_id=interaction.user.id, assignment_type="foreign_diplomat")
                result_text = f"✅ **Approved by {interaction.user.mention}.** {applicant.mention} now has access to **{embassy['country_name']} Embassy**."
            else:
                result_text = f"❌ **Declined by {interaction.user.mention}.** {applicant.mention} was not granted access to **{embassy['country_name']} Embassy**."
            await store.log_audit(actor=interaction.user.id, action="EMBASSY_REQUEST_APPROVED" if approved else "EMBASSY_REQUEST_REJECTED", target_type="request", target_id=self.request_id, embassy_id=embassy_id, result=result["request_status"])
        except ValueError:
            await progress.edit(content="This request has already been decided by another action.")
            return
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.exception("Discord access projection failed for request %s", self.request_id)
            await progress.edit(content="⚠️ The decision was recorded, but Discord access could not be projected. EAM/Admin should reconcile the embassy membership.")
            return
        except Exception:
            logger.exception("Embassy approval decision failed for request %s", self.request_id)
            await progress.edit(content="⚠️ RAJDOOT could not finish recording this decision. Please try again.")
            return
        if interaction.message:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            await interaction.message.edit(content=result_text, view=self)
        await progress.edit(content="Decision recorded. These controls are now locked.")
        await close_thread(interaction.guild.get_thread(int(request["request_thread_id"]))) if request.get("request_thread_id") else None

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
        logger.exception("Could not close embassy request thread %s", thread.id)


class EmbassyRequestCommands(app_commands.Group):
    def __init__(self, database: Database) -> None:
        super().__init__(name="embassy", description="Embassy access request workflow")
        self.database, self.store = database, WorkflowStore(database)

    @app_commands.command(name="request", description="Start the Embassy Access Request verification flow")
    async def request(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is only available in the embassy server.", ephemeral=True)
            return
        existing = await self.store.fetch_open_for_applicant(interaction.user.id)
        if existing:
            thread = interaction.guild.get_thread(int(existing.get("request_thread_id"))) if existing.get("request_thread_id") else None
            if thread is not None and (thread.archived or thread.locked):
                await self.store.cancel_request(str(existing["id"]), reason="Request thread was closed before completion")
            else:
                suffix = f" Continue here: {thread.mention}" if thread else " Continue in your existing request thread."
                await interaction.response.send_message(f"⏳ You already have an active embassy request.{suffix}", ephemeral=True)
                return
        parent = interaction.guild.get_channel(settings.request_channel_id or 0)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message("⚠️ REQUEST_CHANNEL_ID is not configured to a text channel.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            request = await self.store.create_request(interaction.user.id)
            thread = await parent.create_thread(name=f"embassy-request-{interaction.user.display_name}"[:100], type=discord.ChannelType.private_thread, invitable=False, auto_archive_duration=10080, reason="RAJDOOT Embassy Access Request")
            await thread.add_user(interaction.user)
            await self.store.set_flow_state(str(request["id"]), "profile_pending", request_thread_id=thread.id)
            await thread.send(embed=discord.Embed(title="🏛️ Embassy Access Request", description="Welcome. This private request will verify your WarEra identity before embassy access is discussed.\n\nFirst, send your **WarEra in-game profile link**.", colour=discord.Colour.blurple()), view=EmbassyStartView(self.database, str(request["id"]), thread))
            await self.store.log_audit(actor=interaction.user.id, action="EMBASSY_REQUEST_STARTED", target_type="request", target_id=str(request["id"]), embassy_id=None, result="CREATED", metadata={"thread_id": thread.id})
            await interaction.followup.send(f"✅ Your private embassy request thread is ready: {thread.mention}", ephemeral=True)
        except Exception:
            logger.exception("Could not create embassy request for user %s", interaction.user.id)
            await interaction.followup.send("⚠️ RAJDOOT could not create the private request. Please try again.", ephemeral=True)

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
