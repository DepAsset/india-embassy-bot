from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from app.services.requests import EmbassyRequestService

logger = logging.getLogger(__name__)


class WarEraProfileModal(discord.ui.Modal, title="Embassy Verification"):
    profile = discord.ui.TextInput(
        label="WarEra Profile Link or ID",
        placeholder="https://warera.io/profile/... or your WarEra User ID",
        min_length=1,
        max_length=200,
        required=True,
    )

    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=300)
        self.service = service

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This application can only be started inside the India server.",
                ephemeral=True,
            )
            return

        parent = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(parent, discord.TextChannel):
            await interaction.response.send_message(
                "The Embassy request channel is not configured as a text channel. Please contact an administrator.",
                ephemeral=True,
            )
            return

        try:
            request_id, thread, created = await self.service.create_private_request(
                channel=parent,
                applicant=interaction.user,
            )
            if not created:
                await interaction.response.send_message(
                    f"You already have an active Embassy request: {thread.mention}",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"Your private Embassy request has been created: {thread.mention}",
                ephemeral=True,
            )

            await thread.send(
                embed=discord.Embed(
                    title="🇮🇳 Embassy Access Request",
                    description=(
                        "Your request has been created successfully.\n\n"
                        "**WarEra Profile:**\n"
                        f"`{self.profile.value}`\n\n"
                        "The bot will use this profile/ID to resolve your canonical WarEra identity "
                        "before continuing with OTP verification."
                    ),
                    color=discord.Color.dark_red(),
                ),
                view=VerificationStartView(request_id=request_id),
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I cannot create the private request thread. Please contact an administrator.",
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception("Discord API failure while creating embassy request")
            await interaction.response.send_message(
                "Discord returned an error while creating your request. Please try again later.",
                ephemeral=True,
            )


class RequestPanelView(discord.ui.View):
    def __init__(self, service: EmbassyRequestService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Request Embassy Access",
        style=discord.ButtonStyle.primary,
        emoji="🏛️",
        custom_id="embassy:request-access",
    )
    async def request_access(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(WarEraProfileModal(self.service))


class VerificationStartView(discord.ui.View):
    """Persistent placeholder for the next verification slice.

    The profile has already been captured into the private request thread.
    The next implementation slice wires this action to the concrete WarEra
    API adapter and OTP issuance service.
    """

    def __init__(self, request_id: str) -> None:
        super().__init__(timeout=None)
        self.request_id = request_id

    @discord.ui.button(
        label="Continue Verification",
        style=discord.ButtonStyle.success,
        emoji="🔐",
        custom_id="embassy:continue-verification",
    )
    async def continue_verification(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Your profile is captured. WarEra profile resolution and OTP verification are being connected next.",
            ephemeral=True,
        )


class EmbassyRequestsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.service = EmbassyRequestService(bot.database)

    async def cog_load(self) -> None:
        self.bot.add_view(RequestPanelView(self.service))

    @app_commands.command(name="embassy-setup", description="Install or refresh the Embassy request panel.")
    async def embassy_setup(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command is guild-only.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You need Manage Server to run this setup command.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(settings.channel_request_parent_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "CHANNEL_REQUEST_PARENT_ID must point to a normal text channel.",
                ephemeral=True,
            )
            return

        await channel.send(
            embed=discord.Embed(
                title="🇮🇳 Embassy Access System",
                description=(
                    "Need access to an Embassy? Click the button below to begin.\n\n"
                    "You will first provide your **WarEra profile link or ID**. "
                    "The bot will then create a private request thread for the rest of the verification process."
                ),
                color=discord.Color.dark_red(),
            ),
            view=RequestPanelView(self.service),
        )
        await interaction.response.send_message("Embassy request panel installed.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbassyRequestsCog(bot))
