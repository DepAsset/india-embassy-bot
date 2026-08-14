from __future__ import annotations

import discord

from rajdoot.database import Database
from rajdoot.ui import HomeView, NavigationView, embassy_directory_embed, home_embed


class GovernmentDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(label="Pending Requests", emoji="📥", style=discord.ButtonStyle.primary, custom_id="rajdoot:government:requests")
    async def requests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "📥 Pending Requests is being prepared. We will keep the controls focused on requests you are authorized to review.",
            ephemeral=True,
        )

    @discord.ui.button(label="Manage Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:government:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=GovernmentEmbassyView(self.database))

    @discord.ui.button(label="Manage Diplomats", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:government:diplomats")
    async def diplomats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "👥 Diplomat management is coming together here. Assignments, profiles and access changes will all live in this dashboard.",
            ephemeral=True,
        )

    @discord.ui.button(label="Statistics", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:statistics")
    async def statistics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "📊 Statistics will be available here, with the important numbers presented clearly instead of burying you in raw data.",
            ephemeral=True,
        )

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:logs")
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "📜 The dedicated Logs channel will hold the readable operational history. This dashboard will provide the filtered view.",
            ephemeral=True,
        )

    @discord.ui.button(label="Migration / Reconcile", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:migration")
    async def migration(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "🔄 Migration and reconciliation tools will appear here once the legacy embassy registry is safely mapped.",
            ephemeral=True,
        )


class GovernmentEmbassyView(NavigationView):
    def __init__(self, database: Database) -> None:
        super().__init__(database, timeout=None)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:embassies:refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=self)


class DiplomatDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(label="My Profile", emoji="👤", style=discord.ButtonStyle.primary, custom_id="rajdoot:diplomat:profile")
    async def profile(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "👤 Your diplomatic profile will gather your verified WarEra identity and RAJDOOT embassy access in one friendly place.",
            ephemeral=True,
        )

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:diplomat:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=NavigationView(self.database))

    @discord.ui.button(label="Embassy Members", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:diplomat:members")
    async def members(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "👥 Embassy members will be shown here with direct links to their diplomatic profiles. No wandering around Discord needed. ✨",
            ephemeral=True,
        )

    @discord.ui.button(label="Embassy Information", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="rajdoot:diplomat:information")
    async def information(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "📋 Embassy information will be presented here with quick links to members, requests and activity.",
            ephemeral=True,
        )

    @discord.ui.button(label="Pre-Approve Visitor", emoji="🤝", style=discord.ButtonStyle.success, custom_id="rajdoot:diplomat:preapproval")
    async def preapproval(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "🤝 Pre-approval will guide you through your own embassies only, so you never have to worry about choosing the wrong embassy.",
            ephemeral=True,
        )

    @discord.ui.button(label="My Activity", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "📜 Your embassy activity will appear here with friendly, readable history and direct links back to the related records.",
            ephemeral=True,
        )
