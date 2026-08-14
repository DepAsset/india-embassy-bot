from __future__ import annotations

from datetime import datetime, timezone

import discord

from access.models import AccessSource, AssignmentType
from access.projector import AccessProjector
from access.service import AccessService
from app.config import settings
from approval.workflow import ApprovalWorkflow, Decision, Route
from embassy.registry import EmbassyRegistry


def _government(member: discord.Member) -> bool:
    allowed = {
        settings.role_president_id,
        settings.role_vice_president_id,
        settings.role_nsa_id,
        settings.role_minister_id,
        settings.role_eam_id,
    }
    return member.guild_permissions.administrator or any(role.id in allowed for role in member.roles)


def _diplomat(member: discord.Member) -> bool:
    return any(role.id == settings.role_foreign_diplomat_id for role in member.roles)


def _warera_link(username: str | None, user_id: str | None) -> str:
    if not user_id:
        return "Unavailable"
    name = discord.utils.escape_markdown(username or user_id)
    return f"[{name}](https://app.warera.io/user/{user_id})"


class PreApprovalModal(discord.ui.Modal, title="Create Embassy Pre-Approval"):
    embassy_id = discord.ui.TextInput(label="Embassy ID", placeholder="Use the Embassy ID shown in My Embassies", required=True, max_length=100)
    warera_user_id = discord.ui.TextInput(label="Applicant WarEra User ID", required=True, max_length=100)
    expiry_hours = discord.ui.TextInput(label="Expiry (hours)", default="72", required=False, max_length=4)
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, required=False, max_length=500)

    def __init__(self, bot: discord.Client):
        super().__init__(timeout=300)
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is guild-only.", ephemeral=True)
            return
        embassy_id = self.embassy_id.value.strip()
        access = AccessService(self.bot.database)
        if not await access.has_access(interaction.user.id, embassy_id):
            await interaction.response.send_message("You can only pre-approve visitors for an Embassy where you currently have access.", ephemeral=True)
            return
        try:
            hours = int(self.expiry_hours.value.strip() or "72")
        except ValueError:
            await interaction.response.send_message("Expiry must be a whole number of hours.", ephemeral=True)
            return
        if not 1 <= hours <= 720:
            await interaction.response.send_message("Expiry must be between 1 and 720 hours.", ephemeral=True)
            return
        workflow = ApprovalWorkflow(self.bot.database)
        expires = workflow.default_preapproval_expiry(hours)
        preapproval_id = await workflow.create_preapproval(
            embassy_id=embassy_id,
            diplomat_id=interaction.user.id,
            applicant_warera_id=self.warera_user_id.value.strip(),
            expires_at=expires,
            reason=self.reason.value.strip() or None,
        )
        await interaction.response.send_message(
            f"✅ Pre-approval created.\n\n**ID:** `{preapproval_id}`\n**Embassy:** `{embassy_id}`\n**WarEra:** `{self.warera_user_id.value.strip()}`\n**Expires:** <t:{int(expires.timestamp())}:R>",
            ephemeral=True,
        )


class RequestDetailView(discord.ui.View):
    def __init__(self, bot: discord.Client, request_id: str):
        super().__init__(timeout=900)
        self.bot = bot
        self.request_id = request_id

    async def _decide(self, interaction: discord.Interaction, decision: Decision) -> None:
        request = await self.bot.database.collection("requests").find_one({"request_id": self.request_id, "active": True})
        if not request:
            await interaction.response.send_message("This request has already been handled.", ephemeral=True)
            return
        route = Route(str(request.get("approval_route") or Route.GOVERNMENT_REVIEW.value))
        await __import__("app.cogs.embassy_flow", fromlist=["EmbassyFlow"]).EmbassyFlow(self.bot).decide(interaction, self.request_id, decision, route)

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._decide(interaction, Decision.APPROVED)

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._decide(interaction, Decision.DECLINED)

    @discord.ui.button(label="View Thread", emoji="🧵", style=discord.ButtonStyle.secondary)
    async def thread(self, interaction: discord.Interaction, _: discord.ui.Button):
        request = await self.bot.database.collection("requests").find_one({"request_id": self.request_id})
        if not request:
            await interaction.response.send_message("Request not found.", ephemeral=True)
            return
        channel = interaction.guild.get_thread(int(request["thread_id"])) if interaction.guild else None
        await interaction.response.send_message(channel.jump_url if isinstance(channel, discord.Thread) else "Thread unavailable.", ephemeral=True)


class PendingRequestSelect(discord.ui.View):
    def __init__(self, bot: discord.Client):
        super().__init__(timeout=900)
        self.bot = bot
        select = discord.ui.Select(placeholder="Select a pending request...", custom_id="embassy:dashboard:request-select")
        self.select = select
        select.callback = self.selected
        self.add_item(select)

    async def refresh(self) -> None:
        rows = await self.bot.database.collection("requests").find({"active": True}).sort("created_at", 1).limit(25).to_list(25)
        self.select.options = [
            discord.SelectOption(
                label=str(row.get("verified_country_name") or "Unknown")[:100],
                description=f"{row.get('state', 'UNKNOWN')} • {row.get('discord_user_id', '')}"[:100],
                value=str(row["request_id"]),
            )
            for row in rows
        ]
        self.select.disabled = not rows

    async def selected(self, interaction: discord.Interaction) -> None:
        request_id = self.select.values[0]
        request = await self.bot.database.collection("requests").find_one({"request_id": request_id, "active": True})
        if not request:
            await interaction.response.send_message("That request is no longer pending.", ephemeral=True)
            return
        registry = EmbassyRegistry(self.bot.database)
        embassy = await registry.get_by_id(str(request.get("requested_embassy_id") or ""))
        embed = discord.Embed(title="📨 Request Details", color=discord.Color.orange())
        embed.add_field(name="Applicant", value=f"<@{request.get('discord_user_id')}>", inline=True)
        embed.add_field(name="WarEra", value=_warera_link(request.get("warera_username"), request.get("warera_user_id")), inline=True)
        embed.add_field(name="Country", value=str(request.get("verified_country_name") or "Unknown"), inline=True)
        embed.add_field(name="Requested Embassy", value=embassy.country_name if embassy else "Unknown", inline=True)
        embed.add_field(name="Verification", value=str(request.get("state") or "Unknown"), inline=True)
        embed.add_field(name="Route", value=str(request.get("approval_route") or "Unknown"), inline=True)
        embed.add_field(name="Government Status", value=str(request.get("official_flags") or "None"), inline=False)
        await interaction.response.send_message(embed=embed, view=RequestDetailView(self.bot, request_id), ephemeral=True)


class EmbassyDirectoryView(discord.ui.View):
    def __init__(self, bot: discord.Client, page: int = 0, filter_name: str = "all"):
        super().__init__(timeout=900)
        self.bot = bot
        self.page = page
        self.filter_name = filter_name
        select = discord.ui.Select(
            placeholder="Filter Embassy Directory",
            options=[
                discord.SelectOption(label="All", value="all", default=filter_name == "all"),
                discord.SelectOption(label="Active", value="active", default=filter_name == "active"),
                discord.SelectOption(label="No Diplomats", value="empty", default=filter_name == "empty"),
                discord.SelectOption(label="Pending Requests", value="pending", default=filter_name == "pending"),
            ],
            custom_id="embassy:dashboard:directory-filter",
            row=0,
        )
        select.callback = self.filter
        self.add_item(select)
        prev = discord.ui.Button(label="Previous", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:directory-prev", row=1)
        nxt = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:directory-next", row=1)
        prev.callback = lambda i: self.turn(i, -1)
        nxt.callback = lambda i: self.turn(i, 1)
        self.add_item(prev)
        self.add_item(nxt)
        self.prev = prev
        self.next = nxt

    async def _data(self):
        registry = EmbassyRegistry(self.bot.database)
        embassies = await registry.get_active()
        access = AccessService(self.bot.database)
        result = []
        for embassy in embassies:
            diplomats = await access.active_for_embassy(embassy.embassy_id)
            pending = await self.bot.database.collection("requests").count_documents({"active": True, "requested_embassy_id": embassy.embassy_id})
            if self.filter_name == "empty" and diplomats:
                continue
            if self.filter_name == "pending" and not pending:
                continue
            result.append((embassy, len(diplomats), pending))
        return result

    async def render(self, interaction: discord.Interaction) -> None:
        rows = await self._data()
        pages = max(1, (len(rows) + 24) // 25)
        self.page = max(0, min(self.page, pages - 1))
        chunk = rows[self.page * 25:(self.page + 1) * 25]
        embed = discord.Embed(title="📋 Embassy Directory", color=discord.Color.blurple())
        embed.description = "\n".join(f"**{e.country_name}** {'🟢' if e.active else '⚪'} • {count} diplomat(s) • {pending} pending" for e, count, pending in chunk) or "No Embassies match this filter."
        embed.set_footer(text=f"Page {self.page + 1}/{pages}")
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= pages - 1
        await interaction.response.edit_message(embed=embed, view=self)

    async def filter(self, interaction: discord.Interaction) -> None:
        self.filter_name = self.children[0].values[0]
        self.page = 0
        await self.render(interaction)

    async def turn(self, interaction: discord.Interaction, delta: int) -> None:
        self.page += delta
        await self.render(interaction)


class ManageDiplomatsView(discord.ui.View):
    def __init__(self, bot: discord.Client, mode: str):
        super().__init__(timeout=900)
        self.bot = bot
        self.mode = mode
        user = discord.ui.UserSelect(placeholder="Select an Ambassador", custom_id=f"embassy:dashboard:{mode}:user")
        user.callback = self.user_selected
        self.add_item(user)

    async def user_selected(self, interaction: discord.Interaction) -> None:
        member = interaction.guild.get_member(self.children[0].values[0].id) if interaction.guild else None
        ambassador_role = interaction.guild.get_role(settings.role_ambassador_id) if interaction.guild else None
        if not member or not ambassador_role or ambassador_role not in member.roles:
            await interaction.response.send_message("The selected user must have the **Ambassador** role.", ephemeral=True)
            return
        embassies = await EmbassyRegistry(self.bot.database).get_active()
        select = discord.ui.Select(
            placeholder="Select one or more Embassies",
            min_values=1,
            max_values=min(25, len(embassies)),
            options=[discord.SelectOption(label=e.country_name[:100], value=e.embassy_id) for e in embassies[:25]],
            custom_id=f"embassy:dashboard:{self.mode}:embassies",
        )
        confirm = discord.ui.Button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"embassy:dashboard:{self.mode}:confirm")
        view = discord.ui.View(timeout=900)
        view.add_item(select)
        view.add_item(confirm)

        async def apply(i: discord.Interaction) -> None:
            service = AccessService(self.bot.database)
            projector = AccessProjector(self.bot.database)
            changed = failed = 0
            for embassy_id in select.values:
                try:
                    if self.mode == "assign":
                        await service.assign(member.id, embassy_id, AssignmentType.AMBASSADOR, AccessSource.GOVERNMENT_OVERRIDE, assigned_by=i.user.id)
                        await projector.grant(i.guild, member.id, embassy_id, i.user.id, "Embassy Dashboard assignment")
                        changed += 1
                    else:
                        result = await service.revoke(member.id, embassy_id, revoked_by=i.user.id, reason="Embassy Dashboard revocation", assignment_type=AssignmentType.AMBASSADOR)
                        if result.revoked:
                            await projector.revoke(i.guild, member.id, embassy_id, i.user.id, "Embassy Dashboard revocation")
                            changed += 1
                except Exception:
                    failed += 1
            await projector.reconcile_member(i.guild, member.id)
            await i.response.send_message(f"✅ Completed **{changed}** • Failed **{failed}**", ephemeral=True)

        confirm.callback = apply
        await interaction.response.send_message("Choose Embassy access, then confirm.", view=view, ephemeral=True)


class EmbassyManagementView(discord.ui.View):
    """Persistent EAM/Admin dashboard. Every top-level control has a stable custom_id."""

    def __init__(self, bot: discord.Client, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not _government(interaction.user):
            await interaction.response.send_message("You are not authorized to use Embassy Management.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pending Requests", emoji="📨", style=discord.ButtonStyle.primary, custom_id="embassy:mgmt:requests", row=0)
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = PendingRequestSelect(self.bot)
        await view.refresh()
        count = await self.bot.database.collection("requests").count_documents({"active": True})
        embed = discord.Embed(title="📨 Pending Requests", description=f"Pending Requests: **{count}**\n\nSelect a request below to review its verification, government status and requested Embassy.", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Manage Embassies", emoji="🏛️", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:embassies", row=0)
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = EmbassyDirectoryView(self.bot)
        await interaction.response.send_message(embed=discord.Embed(title="🏛️ Manage Embassies", description="Embassy directory and live Embassy status.", color=discord.Color.blurple()), view=view, ephemeral=True)
        msg = await interaction.original_response()
        await view.render(await _fake_edit_interaction(msg, interaction)) if False else None

    @discord.ui.button(label="Manage Diplomats", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:diplomats", row=0)
    async def diplomats(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = discord.ui.View(timeout=900)
        assign = discord.ui.Button(label="Assign Embassy Access", emoji="➕", style=discord.ButtonStyle.success, custom_id="embassy:mgmt:diplomats:assign")
        remove = discord.ui.Button(label="Remove Embassy Access", emoji="➖", style=discord.ButtonStyle.danger, custom_id="embassy:mgmt:diplomats:remove")
        profile = discord.ui.Button(label="View Diplomat", emoji="🔎", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:diplomats:profile")
        assign.callback = lambda i: i.response.send_message("Select an Ambassador:", view=ManageDiplomatsView(self.bot, "assign"), ephemeral=True)
        remove.callback = lambda i: i.response.send_message("Select an Ambassador:", view=ManageDiplomatsView(self.bot, "remove"), ephemeral=True)
        profile.callback = lambda i: i.response.send_message("Use the diplomat profile dashboard command from the menu.", ephemeral=True)
        for item in (assign, remove, profile):
            view.add_item(item)
        await interaction.response.send_message("👤 **Manage Diplomats**", view=view, ephemeral=True)

    @discord.ui.button(label="Embassy Directory", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:directory", row=1)
    async def directory(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(embed=discord.Embed(title="📋 Embassy Directory", description="Use the filters below to browse all active Embassies.", color=discord.Color.blurple()), view=EmbassyDirectoryView(self.bot), ephemeral=True)

    @discord.ui.button(label="Statistics", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:stats", row=1)
    async def stats(self, interaction: discord.Interaction, _: discord.ui.Button):
        db = self.bot.database
        total = await db.collection("embassies").count_documents({})
        active = await db.collection("embassies").count_documents({"active": True})
        diplomats = await db.collection("embassy_assignments").count_documents({"active": True})
        pending = await db.collection("requests").count_documents({"active": True})
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        approved = await db.collection("approval_decisions").count_documents({"decision": "APPROVED", "decided_at": {"$gte": today}})
        declined = await db.collection("approval_decisions").count_documents({"decision": "DECLINED", "decided_at": {"$gte": today}})
        embed = discord.Embed(title="📊 Diplomatic Statistics", color=discord.Color.blurple())
        embed.add_field(name="Total Embassies", value=str(total), inline=True)
        embed.add_field(name="Active Embassies", value=str(active), inline=True)
        embed.add_field(name="Inactive Embassies", value=str(total - active), inline=True)
        embed.add_field(name="Foreign Diplomats", value=str(diplomats), inline=True)
        embed.add_field(name="Pending Requests", value=str(pending), inline=True)
        embed.add_field(name="Approved Today", value=str(approved), inline=True)
        embed.add_field(name="Declined Today", value=str(declined), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:logs", row=1)
    async def logs(self, interaction: discord.Interaction, _: discord.ui.Button):
        events = await self.bot.database.collection("audit_logs").find({}).sort("created_at", -1).limit(15).to_list(15)
        embed = discord.Embed(title="📜 Embassy Logs", color=discord.Color.dark_grey())
        embed.description = "\n".join(f"`{e.get('action', 'UNKNOWN')}` • actor `{e.get('actor_id', 'system')}`" for e in events) or "No audit events recorded yet."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Migration / Reconcile", emoji="🔄", style=discord.ButtonStyle.danger, custom_id="embassy:mgmt:migration", row=2)
    async def migration(self, interaction: discord.Interaction, _: discord.ui.Button):
        states = await self.bot.database.collection("migration_state").find({}).sort("completed_at", -1).limit(10).to_list(10)
        assignments = await self.bot.database.collection("embassy_assignments").count_documents({"active": True})
        embed = discord.Embed(title="🔄 Migration & Access Health", color=discord.Color.orange())
        embed.description = "\n".join(f"`{x.get('migration_id')}` • inserted {x.get('inserted', 0)} • updated {x.get('updated', 0)} • missing channels {x.get('missing_channels', 0)}" for x in states) or "No migration record found."
        embed.add_field(name="Active assignments", value=str(assignments), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ForeignDiplomatView(discord.ui.View):
    """Persistent Foreign Diplomat dashboard restricted to the user's assignments."""

    def __init__(self, bot: discord.Client, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not _diplomat(interaction.user):
            await interaction.response.send_message("You need the global Foreign Diplomat role to use this portal.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="My Diplomatic Profile", emoji="👤", style=discord.ButtonStyle.primary, custom_id="embassy:diplomat:profile", row=0)
    async def profile(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        latest = await self.bot.database.collection("requests").find_one({"discord_user_id": interaction.user.id, "warera_user_id": {"$exists": True}}, sort=[("updated_at", -1)])
        embed = discord.Embed(title="🤝 Diplomat Profile", color=discord.Color.blurple())
        embed.add_field(name="Discord", value=interaction.user.mention, inline=True)
        embed.add_field(name="WarEra", value=_warera_link((latest or {}).get("warera_username"), (latest or {}).get("warera_user_id")), inline=True)
        embed.add_field(name="Country", value=str((latest or {}).get("verified_country_name") or "Unknown"), inline=True)
        embed.add_field(name="Position", value="Ambassador" if any(r.id == settings.role_ambassador_id for r in interaction.user.roles) else "Foreign Diplomat", inline=True)
        embed.add_field(name="Embassy Access", value="\n".join(f"• {(await EmbassyRegistry(self.bot.database).get_by_id(str(a['embassy_id']))).country_name}" for a in assignments if await EmbassyRegistry(self.bot.database).get_by_id(str(a['embassy_id']))) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Embassy Members", emoji="👥", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:members", row=0)
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        registry = EmbassyRegistry(self.bot.database)
        lines = []
        for assignment in assignments:
            embassy = await registry.get_by_id(str(assignment["embassy_id"]))
            if not embassy:
                continue
            people = await AccessService(self.bot.database).active_for_embassy(embassy.embassy_id)
            lines.append(f"**{embassy.country_name}** • {len(people)} active diplomat(s)")
        await interaction.response.send_message("\n".join(lines) or "You have no Embassy assignments.", ephemeral=True)

    @discord.ui.button(label="Pre-Approve Visitor", emoji="⚡", style=discord.ButtonStyle.success, custom_id="embassy:diplomat:preapprove", row=1)
    async def preapprove(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(PreApprovalModal(self.bot))

    @discord.ui.button(label="Embassy Information", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:info", row=1)
    async def info(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        registry = EmbassyRegistry(self.bot.database)
        lines = []
        for assignment in assignments:
            embassy = await registry.get_by_id(str(assignment["embassy_id"]))
            if embassy:
                lines.append(f"**{embassy.country_name} Embassy** • <#{embassy.channel_id}>")
        await interaction.response.send_message("\n".join(lines) or "No Embassy information available.", ephemeral=True)


async def ensure_dashboards(bot: discord.Client, guild: discord.Guild) -> None:
    """Create or refresh the two persistent dashboard messages on startup."""
    configs = [
        (settings.channel_embassy_management_id, "admin", "🏛️ EMBASSY MANAGEMENT", "Manage India's diplomatic missions, Embassy access and foreign diplomats.", EmbassyManagementView(bot, timeout=None)),
        (settings.channel_foreign_diplomat_dashboard_id, "diplomat", "🤝 DIPLOMATIC DASHBOARD", "Manage only the Embassies you have active access to.", ForeignDiplomatView(bot, timeout=None)),
    ]
    state = bot.database.collection("dashboard_state")
    for channel_id, key, title, description, view in configs:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        existing = await state.find_one({"key": key})
        message = None
        if existing and existing.get("message_id"):
            try:
                message = await channel.fetch_message(int(existing["message_id"]))
            except discord.HTTPException:
                message = None
        embed = discord.Embed(title=title, description=description, color=discord.Color.dark_red() if key == "admin" else discord.Color.blurple())
        if key == "admin":
            embed.add_field(name="📨 Pending Requests", value="Review Embassy applications and approvals.", inline=False)
            embed.add_field(name="🏛️ Manage Embassies", value="Directory, status and Embassy details.", inline=True)
            embed.add_field(name="👤 Manage Diplomats", value="Assign or revoke direct Embassy access.", inline=True)
            embed.add_field(name="📊 Statistics", value="Live diplomatic statistics.", inline=True)
            embed.add_field(name="📜 Logs", value="Audit trail of Embassy actions.", inline=True)
        else:
            embed.add_field(name="Your Access", value="Only your active Embassy assignments are available here.", inline=False)
            embed.add_field(name="Pre-Approve Visitor", value="Pre-approve visitors for your own Embassies only.", inline=True)
        if message:
            await message.edit(embed=embed, view=view)
        else:
            message = await channel.send(embed=embed, view=view)
        bot.add_view(view, message_id=message.id)
        await state.update_one({"key": key}, {"$set": {"message_id": message.id, "channel_id": channel.id, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
