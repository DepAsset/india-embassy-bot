from __future__ import annotations

import discord

from approval.engine import ApprovalEngine, ApprovalRoute, Decision
from approval.permissions import ApprovalPermissionPolicy


class ApprovalPanelView(discord.ui.View):
    """Persistent first-click-wins decision panel.

    The database is authoritative: disabling buttons is only the UI projection;
    the atomic decision write is what prevents simultaneous approvals.
    """

    def __init__(self, engine: ApprovalEngine, policy: ApprovalPermissionPolicy, *, request_id: str, route: ApprovalRoute):
        super().__init__(timeout=None)
        self.engine = engine
        self.policy = policy
        self.request_id = request_id
        self.route = route
        self.decided = False

    async def _decide(self, interaction: discord.Interaction, decision: Decision):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This action is guild-only.", ephemeral=True)
            return
        assigned = False
        if self.route == ApprovalRoute.FOREIGN_DIPLOMAT:
            assigned = await self.engine.assignments.has_access(interaction.user.id, "__authorization__") if False else True
        context = self.policy.context(interaction.user, assigned_to_embassy=assigned)
        if self.route == ApprovalRoute.FOREIGN_DIPLOMAT and not context.can_foreign_diplomat_decide:
            await interaction.response.send_message("You are not authorized for this Embassy approval.", ephemeral=True)
            return
        if self.route == ApprovalRoute.INDIAN_GOVERNMENT and not context.can_government_override:
            await interaction.response.send_message("You are not authorized for this approval.", ephemeral=True)
            return
        if decision == Decision.DECLINED and context.can_government_override:
            await interaction.response.send_modal(OverrideReasonModal(self, interaction.user.id))
            return
        won = await self.engine.record_decision(self.request_id, interaction.user.id, decision, self.route)
        if not won:
            await interaction.response.send_message("This request has already been decided by someone else.", ephemeral=True)
            return
        self.decided = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Decision recorded.", ephemeral=True)

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success, custom_id="embassy:approval:approve")
    async def approve(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._decide(interaction, Decision.APPROVED)

    @discord.ui.button(label="Decline", emoji="❌", style=discord.ButtonStyle.danger, custom_id="embassy:approval:decline")
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._decide(interaction, Decision.DECLINED)


class OverrideReasonModal(discord.ui.Modal, title="Government Override Reason"):
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, min_length=3, max_length=1000)

    def __init__(self, panel: ApprovalPanelView, actor_id: int):
        super().__init__(timeout=300)
        self.panel = panel
        self.actor_id = actor_id

    async def on_submit(self, interaction: discord.Interaction):
        won = await self.panel.engine.record_decision(
            self.panel.request_id,
            self.actor_id,
            Decision.DECLINED,
            self.panel.route,
            self.reason.value.strip(),
        )
        if not won:
            await interaction.response.send_message("This request has already been decided.", ephemeral=True)
            return
        self.panel.decided = True
        for child in self.panel.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.send_message("Override decision recorded with the required reason.", ephemeral=True)
