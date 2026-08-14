from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from app.legacy_access_cleanup import cleanup_legacy_direct_access

log = logging.getLogger("india-embassy-bot")

GOVERNMENT_ROLE_IDS = {
    settings.role_president_id,
    settings.role_vice_president_id,
    settings.role_nsa_id,
    settings.role_minister_id,
    settings.role_eam_id,
}


def authorized(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or any(r.id in GOVERNMENT_ROLE_IDS for r in member.roles)


class LegacyCleanupConfirmView(discord.ui.View):
    def __init__(self, bot: commands.Bot, requester_id: int) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.requester_id = requester_id
        self.running = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("Only the administrator who started this cleanup can confirm it.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not authorized(interaction.user):
            await interaction.response.send_message("Government Embassy authority required.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Cleanup", emoji="🧹", style=discord.ButtonStyle.danger, custom_id="embassy:legacy-cleanup:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.running:
            await interaction.response.send_message("Cleanup is already running.", ephemeral=True)
            return
        self.running = True
        button.disabled = True
        await interaction.response.defer(ephemeral=True)
        try:
            result = await cleanup_legacy_direct_access(interaction.guild)
            await interaction.followup.send(
                "🧹 **Legacy Embassy Access Cleanup Complete**\n\n"
                f"Embassy channels scanned: **{result.channels_scanned}**\n"
                f"Legacy member overrides found: **{result.member_overrides_found}**\n"
                f"Overrides removed: **{result.overrides_removed}**\n"
                f"Failures: **{result.failures}**\n\n"
                "The old direct-access migration remains retired and will not recreate these permissions.",
                ephemeral=True,
            )
        except Exception:
            log.exception("Legacy Embassy access cleanup failed")
            await interaction.followup.send("⚠️ Cleanup failed. Check Render logs before retrying.", ephemeral=True)
        finally:
            self.stop()

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary, custom_id="embassy:legacy-cleanup:cancel")
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_message("Cleanup cancelled. No permissions were changed.", ephemeral=True)
        self.stop()


class LegacyCleanupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="cleanup-legacy-access",
        description="One-time cleanup of legacy direct member access on Embassy channels.",
    )
    async def cleanup(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not authorized(interaction.user):
            await interaction.response.send_message("Government Embassy authority required.", ephemeral=True)
            return

        await interaction.response.send_message(
            "⚠️ **Legacy Embassy Access Cleanup**\n\n"
            "This will inspect the live Embassy channel permission overwrites and remove the old direct member access created by the legacy migration.\n\n"
            "It will **not** modify `@everyone` or role overwrites. Unrelated member permissions are preserved.\n\n"
            "This operation may take a few minutes because Discord rate-limits permission changes.\n\n"
            "**Do you want to continue?**",
            view=LegacyCleanupConfirmView(self.bot, interaction.user.id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LegacyCleanupCog(bot))
