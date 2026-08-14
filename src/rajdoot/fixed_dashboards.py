from __future__ import annotations

import discord

from rajdoot.database import Database
from rajdoot.ui import GovernmentEmbassyView, embassy_directory_embed


class FixedGovernmentDashboardView(discord.ui.View):
    """Persistent top-level government dashboard.

    This view never edits its own message. Every top-level control opens a
    separate response message underneath the fixed dashboard.
    """

    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    async def _open(self, interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View | None = None) -> None:
        await interaction.response.send_message(embed=embed, view=view)

    @discord.ui.button(
        label="Pending Requests",
        emoji="📥",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:government:requests",
    )
    async def requests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="📥 Pending Requests",
                description=(
                    "Pending diplomatic requests will appear here.\n\n"
                    "This is a separate working message; the Government Control Center remains fixed above."
                ),
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="Manage Embassies",
        emoji="🏛️",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:government:embassies",
    )
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await embassy_directory_embed(self.database),
            view=GovernmentEmbassyView(self.database),
        )

    @discord.ui.button(
        label="Manage Diplomats",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:government:diplomats",
    )
    async def diplomats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="👥 Manage Diplomats",
                description=(
                    "Diplomat profiles, assignments and access management will be handled here.\n\n"
                    "The Government Control Center remains fixed above."
                ),
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="Statistics",
        emoji="📊",
        style=discord.ButtonStyle.secondary,
        custom_id="rajdoot:fixed:government:statistics",
    )
    async def statistics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="📊 Government Statistics",
                description="Government and embassy statistics will be presented here without replacing the fixed dashboard.",
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="Logs",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        custom_id="rajdoot:fixed:government:logs",
    )
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="📜 RAJDOOT Logs",
                description="Operational history and audit information will appear here as a separate working message.",
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="Migration / Reconcile",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="rajdoot:fixed:government:migration",
    )
    async def migration(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="🔄 Migration / Reconcile",
                description=(
                    "Embassy reconciliation tools are available from this separate working message.\n\n"
                    "The fixed Government Control Center will not be replaced by the workflow."
                ),
                colour=discord.Colour.blurple(),
            ),
        )


class FixedDiplomatDashboardView(discord.ui.View):
    """Persistent top-level diplomat dashboard with separate working messages."""

    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    async def _open(self, interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View | None = None) -> None:
        await interaction.response.send_message(embed=embed, view=view)

    @discord.ui.button(
        label="My Profile",
        emoji="👤",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:diplomat:profile",
    )
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="👤 My Diplomatic Profile",
                description="Your verified WarEra identity and RAJDOOT diplomatic access will be shown here.",
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="My Embassies",
        emoji="🏛️",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:diplomat:embassies",
    )
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            embed=await embassy_directory_embed(self.database),
            view=discord.ui.View(timeout=300),
        )

    @discord.ui.button(
        label="Embassy Members",
        emoji="👥",
        style=discord.ButtonStyle.primary,
        custom_id="rajdoot:fixed:diplomat:members",
    )
    async def members(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="👥 Embassy Members",
                description="Embassy members and their diplomatic profiles will be shown here.",
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="Embassy Information",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="rajdoot:fixed:diplomat:information",
    )
    async def information(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="📋 Embassy Information",
                description="Embassy information, contacts and related diplomatic records will be presented here.",
                colour=discord.Colour.blurple(),
            ),
        )

    @discord.ui.button(
        label="Pre-Approve Visitor",
        emoji="🤝",
        style=discord.ButtonStyle.success,
        custom_id="rajdoot:fixed:diplomat:preapproval",
    )
    async def preapproval(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="🤝 Pre-Approve Visitor",
                description="Visitor pre-approval will guide you through the embassies you are authorized to manage.",
                colour=discord.Colour.green(),
            ),
        )

    @discord.ui.button(
        label="My Activity",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        custom_id="rajdoot:fixed:diplomat:activity",
    )
    async def activity(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._open(
            interaction,
            embed=discord.Embed(
                title="📜 My Diplomatic Activity",
                description="Your embassy activity and related history will appear here as a separate working message.",
                colour=discord.Colour.blurple(),
            ),
        )
