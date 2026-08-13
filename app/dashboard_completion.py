from __future__ import annotations

import discord

from access.projector import AccessProjector
from access.service import AccessService
from app.cogs.dashboards import EmbassyManagementView, ForeignDiplomatView
from embassy.registry import EmbassyRegistry

_original_management_init = EmbassyManagementView.__init__


def _management_init(self, bot, *, timeout=None):
    _original_management_init(self, bot, timeout=timeout)
    reconcile = discord.ui.Button(label="Reconcile Access", emoji="🔧", style=discord.ButtonStyle.success, custom_id="embassy:mgmt:reconcile", row=1)
    reconcile.callback = self._reconcile
    self.add_item(reconcile)


async def _reconcile(self, interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    projector = AccessProjector(self.bot.database)
    assignments = await self.bot.database.collection("embassy_assignments").find({"active": True}, {"discord_user_id": 1}).limit(500).to_list(length=500)
    user_ids = sorted({int(item["discord_user_id"]) for item in assignments if item.get("discord_user_id") is not None})
    if interaction.guild is None:
        await interaction.followup.send("Guild is unavailable.", ephemeral=True)
        return
    reconciled = failed = 0
    for user_id in user_ids:
        try:
            await projector.reconcile_member(interaction.guild, user_id)
            reconciled += 1
        except Exception:
            failed += 1
    await interaction.followup.send(f"🔧 **Access reconciliation complete**\n\nUsers checked: **{len(user_ids)}**\nReconciled: **{reconciled}**\nFailed: **{failed}**", ephemeral=True)


EmbassyManagementView.__init__ = _management_init
EmbassyManagementView._reconcile = _reconcile


async def _diplomat_access(self, interaction: discord.Interaction, button):
    assignments = await AccessService(self.bot.database).active_for_user(interaction.user.id)
    registry = EmbassyRegistry(self.bot.database)
    if not assignments:
        await interaction.response.send_message("You have no active Embassy assignments.", ephemeral=True)
        return
    lines = []
    for item in assignments:
        embassy = await registry.get_by_id(str(item["embassy_id"]))
        name = embassy.country_name if embassy else str(item["embassy_id"])
        lines.append(f"• **{name}** | `{item.get('assignment_type', 'UNKNOWN')}` | `{item.get('source', 'UNKNOWN')}`")
    await interaction.response.send_message("🔐 **Your Embassy Access**\n\n" + "\n".join(lines), ephemeral=True)


ForeignDiplomatView.access = _diplomat_access

import app.dashboard_overhaul  # noqa: E402,F401
import app.cogs.dashboards as _dashboards  # noqa: E402
from app.dashboard_overhaul import AdminView, ForeignView  # noqa: E402

# Make the replacement Views the public dashboard classes before EmbassyRequestsCog loads.
_dashboards.EmbassyManagementView = AdminView
_dashboards.ForeignDiplomatView = ForeignView
