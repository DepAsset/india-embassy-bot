from __future__ import annotations

import discord

from app.config import settings
from access.service import AccessService
from embassy.registry import EmbassyRegistry


def _government(member: discord.Member) -> bool:
    allowed = {
        settings.role_president_id,
        settings.role_vice_president_id,
        settings.role_nsa_id,
        settings.role_minister_id,
    }
    return member.guild_permissions.administrator or any(role.id in allowed for role in member.roles)


def _diplomat(member: discord.Member) -> bool:
    return any(role.id == settings.role_foreign_diplomat_id for role in member.roles)


class EmbassyManagementView(discord.ui.View):
    def __init__(self, bot: discord.Client, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not _government(interaction.user):
            await interaction.response.send_message("You are not authorized to use Embassy Management.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Requests", emoji="📨", style=discord.ButtonStyle.primary, custom_id="embassy:mgmt:requests")
    async def requests(self, interaction: discord.Interaction, _: discord.ui.Button):
        count = await self.bot.database.collection("requests").count_documents({"active": True})
        await interaction.response.send_message(f"**Pending requests:** {count}", ephemeral=True)

    @discord.ui.button(label="Embassies", emoji="🏛️", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:embassies")
    async def embassies(self, interaction: discord.Interaction, _: discord.ui.Button):
        registry = EmbassyRegistry(self.bot.database)
        active = await registry.get_active()
        await interaction.response.send_message(f"**Active Embassies:** {len(active)}", ephemeral=True)

    @discord.ui.button(label="Access", emoji="🔐", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:access")
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        count = await self.bot.database.collection("embassy_assignments").count_documents({"active": True})
        await interaction.response.send_message(f"**Active assignments:** {count}", ephemeral=True)

    @discord.ui.button(label="Migration", emoji="🔄", style=discord.ButtonStyle.danger, custom_id="embassy:mgmt:migration")
    async def migration(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Migration controls are safety-gated. Snapshot, dry-run, confirmation and rollback are required before live role changes.",
            ephemeral=True,
        )

    @discord.ui.button(label="Audit", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:mgmt:audit")
    async def audit(self, interaction: discord.Interaction, _: discord.ui.Button):
        latest = await self.bot.database.collection("audit_logs").find({}).sort("created_at", -1).limit(10).to_list(10)
        if not latest:
            text = "No audit events recorded yet."
        else:
            text = "\n".join(f"`{item.get('action', 'UNKNOWN')}` by `{item.get('actor_id', 'system')}`" for item in latest)
        await interaction.response.send_message(text, ephemeral=True)


class ForeignDiplomatView(discord.ui.View):
    def __init__(self, bot: discord.Client, *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member) or not _diplomat(interaction.user):
            await interaction.response.send_message("You need the global Foreign Diplomat role.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="embassy:diplomat:embassies")
    async def my_embassies(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        embassy_ids = [item["embassy_id"] for item in assignments]
        if not embassy_ids:
            text = "You have no active Embassy assignments."
        else:
            text = "**Your active Embassies:**\n" + "\n".join(f"• `{item}`" for item in embassy_ids)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Pre-Approve", emoji="⚡", style=discord.ButtonStyle.success, custom_id="embassy:diplomat:preapprove")
    async def preapprove(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_message(
            "Pre-approval is Embassy-specific. Select only an Embassy assigned to you, then provide the applicant's WarEra profile/ID and optional expiry.",
            ephemeral=True,
        )

    @discord.ui.button(label="Activity", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, _: discord.ui.Button):
        events = await self.bot.database.collection("audit_logs").find({"actor_id": interaction.user.id}).sort("created_at", -1).limit(10).to_list(10)
        text = "No activity recorded yet." if not events else "\n".join(f"`{e.get('action', 'UNKNOWN')}`" for e in events)
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Access", emoji="🔐", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:access")
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
        await interaction.response.send_message(f"You have **{len(assignments)}** active Embassy assignment(s).", ephemeral=True)
