from __future__ import annotations

import discord
from discord import app_commands

from rajdoot.database import Database
from rajdoot.embassy_requests import EmbassyRequestModal, request_status_embed


class EmbassyRequestCommands(app_commands.Group):
    def __init__(self, database: Database) -> None:
        super().__init__(name="embassy", description="Embassy access requests")
        self.database = database

    @app_commands.command(name="request", description="Request access to an embassy")
    @app_commands.describe(embassy_id="The Supabase embassy UUID")
    async def request(self, interaction: discord.Interaction, embassy_id: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command is only available in the embassy server.", ephemeral=True)
            return
        await interaction.response.send_modal(EmbassyRequestModal(self.database, embassy_id))

    @app_commands.command(name="status", description="Show your latest embassy request")
    async def status(self, interaction: discord.Interaction) -> None:
        request = await self.database.fetch_latest_request_for_applicant(interaction.user.id)
        if request is None:
            await interaction.response.send_message("You do not have an embassy request yet.", ephemeral=True)
            return
        await interaction.response.send_message(embed=request_status_embed(request), ephemeral=True)
