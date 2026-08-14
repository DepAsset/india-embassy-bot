from __future__ import annotations

import discord

from rajdoot.database import Database
from rajdoot.discord_snapshot import DiscordSnapshotBuilder
from rajdoot.embassy_reconciliation import EmbassyReconciliationEngine, ReconciliationReport
from rajdoot.layout_service import EmbassyLayoutService
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
        await interaction.edit_original_response(
            embed=await embassy_directory_embed(self.database),
            view=GovernmentEmbassyView(self.database),
        )

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

    @discord.ui.button(label="Review Layout", emoji="🧭", style=discord.ButtonStyle.success, custom_id="rajdoot:government:embassies:review")
    async def review_layout(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not (
            interaction.user.guild_permissions.manage_guild
            or interaction.user.guild_permissions.administrator
        ):
            await interaction.response.send_message(
                "🔐 This is a management view, so only authorized server managers can review the reconciliation plan.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "🌿 I need the embassy server context to prepare the review.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="🧭 Embassy Reconciliation Review",
                description=(
                    "RAJDOOT is taking one read-only snapshot of Discord and comparing it with the embassy registry.\n\n"
                    "☕ One moment. I am checking the diplomatic furniture carefully and will not change anything during this review."
                ),
                colour=discord.Colour.blurple(),
            ),
            view=NavigationView(self.database),
        )

        try:
            embassies = await self.database.fetch_all_embassies()
            legacy_roles = await self.database.fetch_legacy_roles()
            snapshot = DiscordSnapshotBuilder.build(interaction.guild)
            report = EmbassyReconciliationEngine().build(
                interaction.guild,
                snapshot,
                embassies,
                legacy_roles,
            )
        except Exception:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="🌿 The review needs a little more preparation",
                    description=(
                        "RAJDOOT could not safely prepare the reconciliation review. "
                        "No Discord changes were made. Please check the bot logs before trying again."
                    ),
                    colour=discord.Colour.orange(),
                ),
                view=NavigationView(self.database),
            )
            raise

        await interaction.edit_original_response(
            embed=self._report_embed(report),
            view=NavigationView(self.database),
        )

    @staticmethod
    def _report_embed(report: ReconciliationReport) -> discord.Embed:
        embed = discord.Embed(
            title="🔎 Embassy Reconciliation Plan",
            description=(
                "This is a **read-only preview**. Nothing has been changed in Discord.\n\n"
                "RAJDOOT will only execute a reviewed change set later, using the smallest possible number of Discord operations."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="🏛️ Desired Layout",
            value=(
                f"**{len(report.layout.entries)}** active embassies\n"
                f"**{len(report.layout.categories)}** Embassy categories\n"
                + "\n".join(f"• {category.name}" for category in report.layout.categories)
            ),
            inline=False,
        )
        embed.add_field(
            name="📊 Planned Changes",
            value=(
                f"Category changes: **{len(report.category_actions)}**\n"
                f"Channel changes: **{len(report.channel_actions)}**\n"
                f"Archive candidates: **{len(report.archive_actions)}**\n"
                f"Role actions: **{len(report.role_actions)}**"
            ),
            inline=True,
        )

        high_risk = sum(1 for action in report.actions if action.risk == "high")
        embed.add_field(
            name="🛡️ Safety",
            value=(
                f"High-risk items: **{high_risk}**\n"
                "No writes performed\n"
                "No roles deleted\n"
                "No channels moved"
            ),
            inline=True,
        )

        preview = report.actions[:8]
        if preview:
            lines = []
            for action in preview:
                icon = {
                    "category_rename": "✏️",
                    "category_create": "📁",
                    "channel_rename": "✏️",
                    "channel_move": "↪️",
                    "channel_reorder": "↕️",
                    "channel_missing": "❗",
                    "archive_channel": "🪦",
                    "archive_unmatched_channel": "⚠️",
                    "role_delete_candidate": "🗑️",
                    "role_rename_candidate": "✏️",
                    "role_missing": "❗",
                }.get(action.kind, "•")
                lines.append(f"{icon} **{action.subject_name}** • {action.detail}")
            embed.add_field(
                name="👀 First Items to Review",
                value="\n".join(lines)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="✨ Everything Looks Calm",
                value="The current Discord snapshot already matches the desired embassy layout.",
                inline=False,
            )

        if len(report.actions) > len(preview):
            embed.set_footer(text=f"Showing 8 of {len(report.actions)} planned items. Execution remains locked.")
        else:
            embed.set_footer(text="Execution remains locked until a separate reviewed action is approved.")
        return embed

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
