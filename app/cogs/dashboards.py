from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.config import settings
from embassy.assignments import AssignmentService


class DashboardView(discord.ui.View):
    def __init__(self, bot: commands.Bot, *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id == settings.discord_guild_id


class EmbassyManagementView(DashboardView):
    def _is_authorized(self, member: discord.Member) -> bool:
        allowed = {
            settings.role_president_id,
            settings.role_vice_president_id,
            settings.role_nsa_id,
            settings.role_minister_id,
        }
        return member.guild_permissions.administrator or any(
            role.id in allowed for role in member.roles
        )

    async def _guard(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not self._is_authorized(member):
            await interaction.response.send_message(
                "You are not authorized to use the Embassy Management Dashboard.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Requests", emoji="📨", style=discord.ButtonStyle.primary, custom_id="embassy:dashboard:requests")
    async def requests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(
            "Request management is connected to the persistent request state. The next dashboard slice will populate filters and actions.",
            ephemeral=True,
        )

    @discord.ui.button(label="Ambassadors", emoji="👤", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:ambassadors")
    async def ambassadors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(
            "Ambassador management is reserved for the Embassy Management Dashboard. Candidate search will use EAM → Foreign Secretary → Ambassador role order.",
            ephemeral=True,
        )

    @discord.ui.button(label="Foreign Diplomats", emoji="🌍", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:diplomats")
    async def diplomats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(
            "Foreign Diplomat management will be embassy-scoped and uses one global Foreign Diplomat role.",
            ephemeral=True,
        )

    @discord.ui.button(label="Embassies", emoji="🏛️", style=discord.ButtonStyle.secondary, custom_id="embassy:dashboard:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(
            "Embassy management will cover creation, archive/restore, permissions and alphabetical organization.",
            ephemeral=True,
        )

    @discord.ui.button(label="Migration / Rollback", emoji="🔄", style=discord.ButtonStyle.danger, custom_id="embassy:dashboard:migration")
    async def migration(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Migration and rollback require Discord Administrator permission.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            "Migration/rollback controls are restricted to administrators and will require explicit confirmation before destructive role changes.",
            ephemeral=True,
        )


class ForeignDiplomatView(DashboardView):
    def _is_diplomat(self, member: discord.Member) -> bool:
        return any(role.id == settings.role_foreign_diplomat_id for role in member.roles)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member) or not self._is_diplomat(member):
            await interaction.response.send_message(
                "You need the global Foreign Diplomat role to use this dashboard.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="embassy:diplomat:embassies")
    async def my_embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        service = AssignmentService(self.bot.database)
        assignments = await service.get_active(interaction.user.id)
        if not assignments:
            text = "You currently have no active embassy assignments."
        else:
            text = "\n".join(f"• `{a['embassy_id']}`" for a in assignments)
            text = f"Your active embassy assignments:\n{text}"
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Pre-Approve", emoji="⚡", style=discord.ButtonStyle.success, custom_id="embassy:diplomat:preapprove")
    async def preapprove(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(
            "Pre-approval starts here. The embassy selector will only contain embassies assigned to you; target identity will use a WarEra profile URL/ID and an expiry/reason.",
            ephemeral=True,
        )

    @discord.ui.button(label="My Access", emoji="🔑", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:access")
    async def my_access(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        service = AssignmentService(self.bot.database)
        assignments = await service.get_active(interaction.user.id)
        await interaction.response.send_message(
            f"You have **{len(assignments)}** active embassy assignment(s).", ephemeral=True
        )

    @discord.ui.button(label="My Activity", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="embassy:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._guard(interaction):
            return
        await interaction.response.send_message(
            "Your diplomat activity is recorded in the audit log. Activity filtering will be added with the audit dashboard slice.",
            ephemeral=True,
        )


class Dashboards(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.add_view(EmbassyManagementView(bot, timeout=None))
        self.bot.add_view(ForeignDiplomatView(bot, timeout=None))

    @app_commands.command(name="embassy-dashboard", description="Install/open the Embassy Management Dashboard.")
    async def embassy_dashboard(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        allowed = isinstance(member, discord.Member) and (
            member.guild_permissions.administrator
            or any(role.id in {
                settings.role_president_id,
                settings.role_vice_president_id,
                settings.role_nsa_id,
                settings.role_minister_id,
            } for role in member.roles)
        )
        if not allowed:
            await interaction.response.send_message("You are not authorized to install this dashboard.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🏛️ Embassy Management",
            description=(
                "Central management dashboard for Embassy requests, Ambassadors, Foreign Diplomats, "
                "embassies, access, migration and maintenance."
            ),
            color=discord.Color.dark_red(),
        )
        await interaction.response.send_message(embed=embed, view=EmbassyManagementView(self.bot, timeout=None))

    @app_commands.command(name="foreign-diplomat-dashboard", description="Open the Foreign Diplomat Dashboard.")
    async def foreign_diplomat_dashboard(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if not isinstance(member, discord.Member) or not any(
            role.id == settings.role_foreign_diplomat_id for role in member.roles
        ):
            await interaction.response.send_message("You need the Foreign Diplomat role to use this dashboard.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🌍 Foreign Diplomat Portal",
            description=(
                "Manage only your assigned embassies, create pre-approvals for those embassies, "
                "and review your activity."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=ForeignDiplomatView(self.bot, timeout=None), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Dashboards(bot))
