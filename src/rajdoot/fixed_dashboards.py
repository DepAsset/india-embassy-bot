from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

import discord

from rajdoot.database import Database
from rajdoot.dashboards import GovernmentEmbassyView
from rajdoot.embassy_workflow import PersistentApprovalView, profile_embed
from rajdoot.ui import embassy_directory_embed
from rajdoot.workflow_store import WorkflowStore


class PreapprovalModal(discord.ui.Modal, title="Pre-Approve WarEra Visitor"):
    profile = discord.ui.TextInput(
        label="WarEra profile URL or ID",
        placeholder="https://app.warera.io/user/...",
        max_length=300,
        required=True,
    )
    hours = discord.ui.TextInput(label="Expiry (hours)", placeholder="72", default="72", max_length=4, required=True)
    reason = discord.ui.TextInput(label="Reason", placeholder="Optional visit reason", max_length=300, required=False)

    def __init__(self, database: Database, embassy: dict) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.embassy = embassy

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        match = re.search(r"/user/([A-Za-z0-9_-]+)", str(self.profile.value).strip())
        if not match:
            raw = str(self.profile.value).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
                await interaction.response.send_message("❌ Enter a valid WarEra profile URL or user ID.", ephemeral=True)
                return
            warera_user_id = raw
        else:
            warera_user_id = match.group(1)
        try:
            hours = int(str(self.hours.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Expiry must be a whole number of hours.", ephemeral=True)
            return
        if hours < 1 or hours > 720:
            await interaction.response.send_message("❌ Expiry must be between 1 and 720 hours.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        store = WorkflowStore(self.database)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        row = await store.create_preapproval(
            embassy_id=str(self.embassy["id"]),
            diplomat_discord_id=interaction.user.id,
            visitor_warera_id=warera_user_id,
            visitor_profile_url=str(self.profile.value).strip(),
            expires_at=expires_at,
            reason=str(self.reason.value).strip() or None,
        )
        await store.log_audit(
            actor=interaction.user.id,
            action="PREAPPROVAL_CREATED",
            target_type="preapproval",
            target_id=str(row["id"]),
            embassy_id=str(self.embassy["id"]),
            result="SUCCESS",
            metadata={"visitor_warera_id": warera_user_id, "expires_at": expires_at.isoformat()},
        )
        await interaction.followup.send(
            f"✅ Pre-approval created for `{warera_user_id}` in **{self.embassy['country_name']} Embassy**.\n"
            f"Expires <t:{int(expires_at.timestamp())}:R>.",
            ephemeral=True,
        )


class PreapprovalEmbassyView(discord.ui.View):
    def __init__(self, database: Database, embassies: list[dict]) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.embassies = {str(e["id"]): e for e in embassies}
        options = [
            discord.SelectOption(label=str(e["country_name"])[:100], value=str(e["id"]))
            for e in embassies[:25]
        ]
        select = discord.ui.Select(placeholder="Choose an embassy", min_values=1, max_values=1, options=options)
        select.callback = self._select
        self.add_item(select)

    async def _select(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        select = self.children[0]
        assert isinstance(select, discord.ui.Select)
        embassy = self.embassies.get(select.values[0])
        if not embassy:
            await interaction.response.send_message("❌ Embassy not found.", ephemeral=True)
            return
        allowed = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        if not any(str(a["embassy_id"]) == str(embassy["id"]) for a in allowed):
            await interaction.response.send_message("🔐 You can only pre-approve visitors for your own embassy assignments.", ephemeral=True)
            return
        await interaction.response.send_modal(PreapprovalModal(self.database, embassy))


class FixedGovernmentDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    async def _open(self, interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View | None = None) -> None:
        if view is None:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Pending Requests", emoji="📥", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:government:requests")
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("🔐 Government authorization required.", ephemeral=True)
            return
        requests = await self.database.fetch_pending_government_requests()
        if not requests:
            await interaction.response.send_message("📭 There are no requests waiting for government approval.", ephemeral=True)
            return
        for index, request in enumerate(requests[:10]):
            embed = profile_embed(request.get("warera_profile_snapshot") or {}, "🏛️ Government Approval Request")
            embed.add_field(name="Request", value=f"`{request['id']}`", inline=False)
            embed.add_field(name="Embassy", value=str(request.get("country_name") or "Unknown"), inline=True)
            embed.add_field(name="Applicant", value=f"<@{request['applicant_discord_id']}> (`{request['applicant_discord_id']}`)", inline=True)
            view = PersistentApprovalView(self.database, str(request["id"]), int(request["applicant_discord_id"]), own_country=False)
            if index == 0:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        if len(requests) > 10:
            await interaction.followup.send(f"📚 Showing the first 10 of {len(requests)} pending government requests.", ephemeral=True)

    @discord.ui.button(label="Manage Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:government:embassies")
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=await embassy_directory_embed(self.database), view=GovernmentEmbassyView(self.database), ephemeral=True)

    @discord.ui.button(label="Manage Diplomats", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:government:diplomats")
    async def diplomats(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("🔐 Government authorization required.", ephemeral=True)
            return
        members = await self.database.fetch_all_active_embassy_members()
        diplomats = [m for m in members if m.get("member_type") == "foreign_diplomat"]
        ambassadors = [m for m in members if m.get("member_type") == "indian_ambassador"]
        embed = discord.Embed(title="👥 Embassy Personnel", colour=discord.Colour.blurple())
        embed.add_field(name="Foreign Diplomats", value=str(len(diplomats)), inline=True)
        embed.add_field(name="Indian Ambassadors", value=str(len(ambassadors)), inline=True)
        lines = [f"• **{m['country_name']}** — {m['discord_username']} — {m['member_type'].replace('_', ' ').title()}" for m in members[:40]]
        embed.add_field(name="Current Registry", value="\n".join(lines)[:1024] or "No members.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Statistics", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:government:statistics")
    async def statistics(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("🔐 Government authorization required.", ephemeral=True)
            return
        embassies = await self.database.fetch_active_embassies()
        members = await self.database.fetch_embassy_member_registry_counts()
        requests = await self.database.fetch_request_statistics()
        embed = discord.Embed(title="📊 Government Statistics", colour=discord.Colour.blurple())
        embed.add_field(name="Embassies", value=str(len(embassies)), inline=True)
        embed.add_field(name="Foreign Diplomats", value=str(members["foreign_diplomats"]), inline=True)
        embed.add_field(name="Indian Ambassadors", value=str(members["indian_ambassadors"]), inline=True)
        embed.add_field(name="Requests Total", value=str(requests["total"]), inline=True)
        embed.add_field(name="Pending", value=str(requests["pending"]), inline=True)
        embed.add_field(name="Approved", value=str(requests["approved"]), inline=True)
        embed.add_field(name="Rejected", value=str(requests["rejected"]), inline=True)
        embed.add_field(name="Verified", value=str(requests["verified"]), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:government:logs")
    async def logs(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("🔐 Government authorization required.", ephemeral=True)
            return
        logs = await self.database.fetch_recent_audit_logs(15)
        lines = []
        for row in logs:
            when = row.get("created_at")
            stamp = f"<t:{int(when.timestamp())}:R>" if when else ""
            actor = f"<@{row['actor_discord_id']}>" if row.get("actor_discord_id") else "SYSTEM"
            lines.append(f"• {stamp} — **{row['action']}** — {actor} — `{row.get('result') or 'N/A'}`")
        embed = discord.Embed(title="📜 Recent RAJDOOT Logs", description="\n".join(lines)[:4000] or "No audit events yet.", colour=discord.Colour.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


class FixedDiplomatDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    async def _open(self, interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View | None = None) -> None:
        if view is None:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="My Profile", emoji="👤", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:diplomat:profile")
    async def profile(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        request = await self.database.fetch_latest_request_for_applicant(interaction.user.id)
        assignments = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        embed = profile_embed((request or {}).get("warera_profile_snapshot") or {}, "👤 My Diplomatic Profile")
        embed.add_field(name="Active Embassies", value="\n".join(a["country_name"] for a in assignments) or "None", inline=False)
        embed.add_field(name="Assignment Types", value="\n".join(a["assignment_type"].replace('_', ' ').title() for a in assignments) or "None", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:diplomat:embassies")
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        assignments = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        if not assignments:
            await interaction.response.send_message("📭 You have no active embassy assignments.", ephemeral=True)
            return
        lines = [f"• **{a['country_name']} Embassy** — <#{a['channel_id']}> — {a['assignment_type'].replace('_', ' ').title()}" for a in assignments]
        await interaction.response.send_message(embed=discord.Embed(title="🏛️ My Embassies", description="\n".join(lines), colour=discord.Colour.blurple()), ephemeral=True)

    @discord.ui.button(label="Pending Requests", emoji="📥", style=discord.ButtonStyle.success, custom_id="rajdoot:fixed:diplomat:requests")
    async def pending_requests(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        requests = await self.database.fetch_pending_requests_for_member(interaction.user.id)
        if not requests:
            await interaction.response.send_message("📭 You have no embassy access requests waiting for approval.", ephemeral=True)
            return
        for index, request in enumerate(requests[:10]):
            embed = profile_embed(request.get("warera_profile_snapshot") or {}, "📨 Embassy Access Request")
            embed.add_field(name="Request", value=f"`{request['id']}`", inline=False)
            embed.add_field(name="Embassy", value=str(request.get("country_name") or "Unknown"), inline=True)
            view = PersistentApprovalView(self.database, str(request["id"]), int(request["applicant_discord_id"]), own_country=True)
            if index == 0:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Embassy Members", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:diplomat:members")
    async def members(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        assignments = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        if not assignments:
            await interaction.response.send_message("📭 You have no embassy assignments.", ephemeral=True)
            return
        lines = []
        for assignment in assignments[:10]:
            members = await self.database.fetch_embassy_members(str(assignment["embassy_id"]))
            lines.append(f"**{assignment['country_name']} Embassy**\n" + ("\n".join(f"• {m['discord_username']} — {m['member_type'].replace('_', ' ').title()}" for m in members[:20]) or "• No members"))
        await interaction.response.send_message(embed=discord.Embed(title="👥 Embassy Members", description="\n\n".join(lines)[:4000], colour=discord.Colour.blurple()), ephemeral=True)

    @discord.ui.button(label="Embassy Information", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:diplomat:information")
    async def information(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        assignments = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        if not assignments:
            await interaction.response.send_message("📭 You have no embassy assignments.", ephemeral=True)
            return
        lines = []
        for a in assignments:
            lines.append(f"**{a['country_name']} Embassy**\nChannel: <#{a['channel_id']}>\nAssignment: {a['assignment_type'].replace('_', ' ').title()}")
        await interaction.response.send_message(embed=discord.Embed(title="📋 Embassy Information", description="\n\n".join(lines), colour=discord.Colour.blurple()), ephemeral=True)

    @discord.ui.button(label="Pre-Approve Visitor", emoji="🤝", style=discord.ButtonStyle.success, custom_id="rajdoot:fixed:diplomat:preapproval")
    async def preapproval(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        assignments = await WorkflowStore(self.database).active_assignments_for_user(interaction.user.id)
        if not assignments:
            await interaction.response.send_message("📭 You have no embassy assignments to pre-approve visitors for.", ephemeral=True)
            return
        embassies = [await self.database.fetch_embassy(str(a["embassy_id"])) for a in assignments]
        embassies = [e for e in embassies if e]
        await interaction.response.send_message("🤝 Select the embassy for the visitor pre-approval:", view=PreapprovalEmbassyView(self.database, embassies), ephemeral=True)

    @discord.ui.button(label="My Activity", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is only available inside the embassy server.", ephemeral=True)
            return
        logs = await self.database.fetch_user_audit_logs(interaction.user.id, 20)
        lines = []
        for row in logs:
            when = row.get("created_at")
            stamp = f"<t:{int(when.timestamp())}:R>" if when else ""
            lines.append(f"• {stamp} — **{row['action']}** — `{row.get('result') or 'N/A'}`")
        await interaction.response.send_message(embed=discord.Embed(title="📜 My Diplomatic Activity", description="\n".join(lines)[:4000] or "No recorded activity yet.", colour=discord.Colour.blurple()), ephemeral=True)
