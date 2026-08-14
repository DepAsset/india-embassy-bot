from __future__ import annotations

import discord

from rajdoot.database import Database
from rajdoot.discord_snapshot import DiscordSnapshotBuilder
from rajdoot.embassy_reconciliation import EmbassyReconciliationEngine, ReconciliationAction, ReconciliationReport
from rajdoot.ui import HomeView, NavigationView, embassy_directory_embed, home_embed


class GovernmentDashboardView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.database = database

    @discord.ui.button(label="Pending Requests", emoji="📥", style=discord.ButtonStyle.primary, custom_id="rajdoot:government:requests")
    async def requests(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("📥 Pending Requests is being prepared. We will keep the controls focused on requests you are authorized to review.", ephemeral=True)

    @discord.ui.button(label="Manage Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:government:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=GovernmentEmbassyView(self.database))

    @discord.ui.button(label="Manage Diplomats", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:government:diplomats")
    async def diplomats(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("👥 Diplomat management is coming together here. Assignments, profiles and access changes will all live in this dashboard.", ephemeral=True)

    @discord.ui.button(label="Statistics", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:statistics")
    async def statistics(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("📊 Statistics will be available here, with the important numbers presented clearly instead of burying you in raw data.", ephemeral=True)

    @discord.ui.button(label="Logs", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:logs")
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("📜 The dedicated Logs channel will hold the readable operational history. This dashboard will provide the filtered view.", ephemeral=True)

    @discord.ui.button(label="Migration / Reconcile", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="rajdoot:government:migration")
    async def migration(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("🔄 Migration and reconciliation tools will appear here once the legacy embassy registry is safely mapped.", ephemeral=True)


class ReconciliationReviewView(discord.ui.View):
    def __init__(self, database: Database, report: ReconciliationReport, page: int = 0) -> None:
        super().__init__(timeout=300)
        self.database = database
        self.report = report
        self.page = page
        self.page_size = 8

        self.previous_page.disabled = page <= 0
        self.next_page.disabled = (page + 1) * self.page_size >= len(report.actions)

    def _items(self) -> tuple[ReconciliationAction, ...]:
        start = self.page * self.page_size
        return self.report.actions[start:start + self.page_size]

    @staticmethod
    def _icon(kind: str) -> str:
        return {
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
        }.get(kind, "•")

    def embed(self) -> discord.Embed:
        total = len(self.report.actions)
        start = self.page * self.page_size + 1 if total else 0
        end = min((self.page + 1) * self.page_size, total)
        embed = discord.Embed(
            title="🔎 Embassy Reconciliation Plan",
            description=(
                "This is a **read-only preview**. Nothing has been changed in Discord.\n\n"
                "RAJDOOT is keeping execution locked until every important item has been reviewed."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="🛡️ Safety",
            value=(
                f"High-risk items: **{sum(1 for a in self.report.actions if a.risk == 'high')}**\n"
                "No Discord writes performed\n"
                "Execution remains locked"
            ),
            inline=True,
        )
        embed.add_field(
            name="📊 Plan",
            value=(
                f"Categories: **{len(self.report.category_actions)}**\n"
                f"Channels: **{len(self.report.channel_actions)}**\n"
                f"Archive: **{len(self.report.archive_actions)}**\n"
                f"Roles: **{len(self.report.role_actions)}**"
            ),
            inline=True,
        )

        if total:
            lines = []
            for action in self._items():
                risk = " ⚠️" if action.risk == "high" else ""
                lines.append(f"{self._icon(action.kind)} **{action.subject_name}**{risk}\n{action.detail}")
            embed.add_field(name=f"👀 Items {start}-{end} of {total}", value="\n\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="✨ Everything Looks Calm", value="The current Discord snapshot already matches the desired embassy layout.", inline=False)

        embed.set_footer(text="Use the arrows to inspect the complete plan. Nothing is executed from this screen.")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = (self.page + 1) * self.page_size >= len(self.report.actions)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = (self.page + 1) * self.page_size >= len(self.report.actions)
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="🔒 Execution Locked", style=discord.ButtonStyle.danger, disabled=True, row=1)
    async def execution_locked(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        pass

    @discord.ui.button(label="↩ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=await embassy_directory_embed(self.database), view=GovernmentEmbassyView(self.database))


class GovernmentEmbassyView(NavigationView):
    def __init__(self, database: Database) -> None:
        super().__init__(database)

    @discord.ui.button(label="Review Layout", emoji="🧭", style=discord.ButtonStyle.success, custom_id="rajdoot:government:embassies:review")
    async def review_layout(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("🔐 This is a management view, so only authorized server managers can review the reconciliation plan.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("🌿 I need the embassy server context to prepare the review.", ephemeral=True)
            return

        await interaction.response.defer()
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="🧭 Embassy Reconciliation Review",
                description="RAJDOOT is taking one read-only snapshot of Discord and comparing it with the embassy registry.\n\n☕ One moment. I am checking the diplomatic furniture carefully and will not change anything during this review.",
                colour=discord.Colour.blurple(),
            ),
            view=NavigationView(self.database),
        )
        try:
            embassies = await self.database.fetch_all_embassies()
            legacy_roles = await self.database.fetch_legacy_roles()
            snapshot = DiscordSnapshotBuilder.build(interaction.guild)
            report = EmbassyReconciliationEngine().build(interaction.guild, snapshot, embassies, legacy_roles)
        except Exception:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="🌿 The review needs a little more preparation",
                    description="RAJDOOT could not safely prepare the reconciliation review. No Discord changes were made. Please check the bot logs before trying again.",
                    colour=discord.Colour.orange(),
                ),
                view=NavigationView(self.database),
            )
            raise

        await interaction.edit_original_response(embed=self._summary_embed(report), view=ReconciliationReviewView(self.database, report))

    @staticmethod
    def _summary_embed(report: ReconciliationReport) -> discord.Embed:
        embed = discord.Embed(
            title="🔎 Embassy Reconciliation Plan",
            description="This is a **read-only preview**. Nothing has been changed in Discord.\n\nRAJDOOT has prepared the complete plan. Open **Detailed Review** to inspect every item before anything can ever be approved.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="🏛️ Desired Layout", value=f"**{len(report.layout.entries)}** active embassies\n**{len(report.layout.categories)}** Embassy categories\n" + "\n".join(f"• {c.name}" for c in report.layout.categories), inline=False)
        embed.add_field(name="📊 Planned Changes", value=f"Category changes: **{len(report.category_actions)}**\nChannel changes: **{len(report.channel_actions)}**\nArchive candidates: **{len(report.archive_actions)}**\nRole actions: **{len(report.role_actions)}**", inline=True)
        high_risk = sum(1 for action in report.actions if action.risk == "high")
        embed.add_field(name="🛡️ Safety", value=f"High-risk items: **{high_risk}**\nNo writes performed\nExecution remains locked", inline=True)
        return embed

    @discord.ui.button(label="Detailed Review", emoji="🔍", style=discord.ButtonStyle.success, custom_id="rajdoot:government:embassies:detailed-review")
    async def detailed_review(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("🔍 Please run **Review Layout** again to generate a fresh read-only plan before opening the detailed review.", ephemeral=True)

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
        await interaction.response.send_message("👤 Your diplomatic profile will gather your verified WarEra identity and RAJDOOT embassy access in one friendly place.", ephemeral=True)

    @discord.ui.button(label="My Embassies", emoji="🏛️", style=discord.ButtonStyle.primary, custom_id="rajdoot:diplomat:embassies")
    async def embassies(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await embassy_directory_embed(self.database), view=NavigationView(self.database))

    @discord.ui.button(label="Embassy Members", emoji="👥", style=discord.ButtonStyle.primary, custom_id="rajdoot:diplomat:members")
    async def members(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("👥 Embassy members will be shown here with direct links to their diplomatic profiles. No wandering around Discord needed. ✨", ephemeral=True)

    @discord.ui.button(label="Embassy Information", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="rajdoot:diplomat:information")
    async def information(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("📋 Embassy information will be presented here with quick links to members, requests and activity.", ephemeral=True)

    @discord.ui.button(label="Pre-Approve Visitor", emoji="🤝", style=discord.ButtonStyle.success, custom_id="rajdoot:diplomat:preapproval")
    async def preapproval(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("🤝 Pre-approval will guide you through your own embassies only, so you never have to worry about choosing the wrong embassy.", ephemeral=True)

    @discord.ui.button(label="My Activity", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="rajdoot:diplomat:activity")
    async def activity(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message("📜 Your embassy activity will appear here with friendly, readable history and direct links back to the related records.", ephemeral=True)
