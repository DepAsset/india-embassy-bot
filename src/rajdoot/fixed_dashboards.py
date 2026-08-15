from __future__ import annotations

import discord

from rajdoot.database import Database
from rajdoot.dashboards import GovernmentEmbassyView
from rajdoot.embassy_approval import EmbassyApprovalView, approval_request_embed
from rajdoot.ui import embassy_directory_embed


class FixedGovernmentDashboardView(discord.ui.View):
    """Persistent top-level government dashboard.

    This view never edits its own message. Every top-level control opens a
    separate response message underneath the fixed dashboard.
    """

    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    async def _open(
        self,
        interaction: discord.Interaction,
        *,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> None:
        if view is None:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @discord.ui.button(label="Pending Requests", emoji="📥", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:government:requests")
    async def requests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="📥 Pending Requests", description="Pending diplomatic requests will appear here.\n\nThis is a separate working message; the Government Control Center remains fixed above.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="Manage Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:government:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=await embassy_directory_embed(self.database), view=GovernmentEmbassyView(self.database))

    @discord.ui.button(label="Manage Diplomats", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:government:diplomats")
    async def diplomats(self, interaction: discord.Interaction, button: discord.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="👥 Manage Diplomats", description="Diplomat profiles, assignments and access management will be handled here.\n\nThe Government Control Center remains fixed above.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="Statistics", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:government:statistics")
    async def statistics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="📊 Government Statistics", description="Government and embassy statistics will be presented here without replacing the fixed dashboard.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:government:logs")
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="📜 RAJDOOT Logs", description="Operational history and audit information will appear here as a separate working message.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="Migration / Reconcile", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:government:migration")
    async def migration(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="🔄 Migration / Reconcile", description="Embassy reconciliation tools are available from this separate working message.\n\nThe fixed Government Control Center will not be replaced by the workflow.", colour=discord.Colour.blurple()))


class FixedDiplomatDashboardView(discord.ui.View):
    """Persistent top-level diplomat dashboard with separate working messages."""

    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    async def _open(
        self,
        interaction: discord.Interaction,
        *,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> None:
        if view is None:
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(embed=embed, view=view)

    @discord.ui.button(label="My Profile", emoji="👤", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:diplomat:profile")
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="👤 My Diplomatic Profile", description="Your verified WarEra identity and RAJDOOT diplomatic access will be shown here.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:diplomat:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(embed=await embassy_directory_embed(self.database))

    @discord.ui.button(label="Pending Requests", emoji="📥", style=discord.ButtonStyle.success, custom_id="rajdoot:fixed:diplomat:requests")
    async def pending_requests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This dashboard action is only available inside the embassy server.", ephemeral=True)
            return
        requests = await self.database.fetch_pending_requests_for_member(interaction.user.id)
        if not requests:
            await interaction.response.send_message("📭 You have no embassy access requests waiting for approval.", ephemeral=True)
            return

        first = requests[0]
        await interaction.response.send_message(
            embed=approval_request_embed(first),
            view=EmbassyApprovalView(self.database, first),
            ephemeral=True,
        )
        for request in requests[1:10]:
            await interaction.followup.send(
                embed=approval_request_embed(request),
                view=EmbassyApprovalView(self.database, request),
                ephemeral=True,
            )
        if len(requests) > 10:
            await interaction.followup.send(
                f"📚 Showing the first 10 of {len(requests)} pending requests. Refresh the dashboard to load the current queue.",
                ephemeral=True,
            )

    @discord.ui.button(label="Embassy Members", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:fixed:diplomat:members")
    async def members(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="👥 Embassy Members", description="Embassy members and their diplomatic profiles will be shown here.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="Embassy Information", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:diplomat:information")
    async def information(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="📋 Embassy Information", description="Embassy information, contacts and related diplomatic records will be presented here.", colour=discord.Colour.blurple()))

    @discord.ui.button(label="Pre-Approve Visitor", emoji="🤝", style=discord.ButtonStyle.success, custom_id="rajdoot:fixed:diplomat:preapproval")
    async def preapproval(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="🤝 Pre-Approve Visitor", description="Visitor pre-approval will guide you through the embassies you are authorized to manage.", colour=discord.Colour.green()))

    @discord.ui.button(label="My Activity", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:fixed:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(interaction, embed=discord.Embed(title="📜 My Diplomatic Activity", description="Your embassy activity and related history will appear here as a separate working message.", colour=discord.Colour.blurple()))
