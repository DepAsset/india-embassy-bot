import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import discord
from discord import app_commands

from rajdoot.config import settings
from rajdoot.dashboards import DiplomatDashboardView, GovernmentEmbassyView
from rajdoot.database import Database
from rajdoot.embassy_members import EmbassyMemberImporter
from rajdoot.fixed_dashboards import FixedDiplomatDashboardView, FixedGovernmentDashboardView
from rajdoot.ui import HomeView, ensure_dashboard_message


logger = logging.getLogger("rajdoot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/health", "/healthz"):
            self.send_response(404)
            self.end_headers()
            return
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        if self.path not in ("/", "/health", "/healthz"):
            self.send_response(404)
            self.end_headers()
            return
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        logger.info("health | " + format, *args)


def start_health_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((settings.health_host, settings.health_port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    thread.start()
    logger.info("Health server listening on %s:%s", settings.health_host, settings.health_port)
    return server


class RajdootClient(discord.Client):
    def __init__(self, database: Database) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.database = database
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.database.connect()
        from rajdoot.dashboards import DiplomatDashboardView, GovernmentEmbassyView
        from rajdoot.fixed_dashboards import FixedDiplomatDashboardView, FixedGovernmentDashboardView
        from rajdoot.ui import HomeView

        self.add_view(HomeView(self.database))
        self.add_view(FixedGovernmentDashboardView(self.database))
        self.add_view(FixedDiplomatDashboardView(self.database))
        self.add_view(DiplomatDashboardView(self.database))
        self.add_view(GovernmentEmbassyView(self.database))

        guild = discord.Object(id=settings.discord_guild_id)

        async def show_government_dashboard(interaction: discord.Interaction) -> None:
            if not isinstance(interaction.user, discord.Member) or not (
                interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("🔐 Only authorized government/server managers can open the Government Control Center.", ephemeral=True)
                return
            await self._show_fixed_dashboard(interaction, "government")

        async def show_diplomat_dashboard(interaction: discord.Interaction) -> None:
            await self._show_fixed_dashboard(interaction, "diplomat")

        async def import_embassy_members(interaction: discord.Interaction) -> None:
            if not isinstance(interaction.user, discord.Member) or not (
                interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator
            ):
                await interaction.response.send_message("🔐 Only authorized server managers can freeze embassy assignments.", ephemeral=True)
                return
            if interaction.guild is None:
                await interaction.response.send_message("🌿 This command must be used inside the embassy server.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                # The first run discovers the legacy roles. After the registry is
                # frozen, this refresh is harmless and is used only to resolve
                # current guild members for direct permission overwrites.
                await interaction.guild.chunk(cache=True)
                result = await EmbassyMemberImporter().import_current_members(interaction.guild, self.database)
            except Exception:
                logger.exception("Embassy member import/hardcode failed")
                await interaction.followup.send(
                    "⚠️ I could not safely complete the embassy member hardcoding. "
                    "No embassy roles were deleted or modified. If the registry was not yet frozen, it remains retryable. "
                    "Please check the Render logs before trying again.",
                    ephemeral=True,
                )
                return

            status_title = "🔒 **Embassy Member Registry + Discord Access Frozen**"
            if result.already_frozen:
                status_title = "🔒 **Embassy Member Registry Verified + Discord Access Re-applied**"

            await interaction.followup.send(
                f"{status_title}\n\n"
                f"🏛️ Embassies scanned: **{result.embassies_scanned}**\n"
                f"🎟️ Embassy access roles discovered: **{result.access_roles_found}**\n"
                f"👥 Canonical assignments: **{result.assignments_seen}**\n"
                f"🌍 Foreign Diplomats: **{result.foreign_diplomats}**\n"
                f"🇮🇳 Indian Ambassadors: **{result.indian_ambassadors}**\n"
                f"♻️ Existing/merged assignments: **{result.unchanged}**\n"
                f"🔐 Direct Discord member permissions applied: **{result.permissions_applied}**\n"
                f"⚠️ Permission failures: **{result.permission_failures}**\n"
                f"⚠️ Embassies without a matched access role: **{result.unmatched_embassies}**\n\n"
                "Multiple legacy access roles for the same embassy are merged into one canonical member set. "
                "Classification is embassy access + Indian Citizen = Indian Ambassador; otherwise Foreign Diplomat. "
                "The Supabase registry is now the canonical baseline. Discord hardcoding is done with direct member channel permissions, so later removal/deletion of the old embassy access roles does NOT remove the stored members' embassy access. "
                "This command never deletes, removes, archives, or modifies the legacy embassy roles.",
                ephemeral=True,
            )

        government_command = app_commands.Command(
            name="government-dashboard",
            description="Jump to the fixed RAJDOOT Government Control Center.",
            callback=show_government_dashboard,
        )
        government_command.default_permissions = discord.Permissions(manage_guild=True)

        diplomat_command = app_commands.Command(
            name="diplomat-dashboard",
            description="Jump to the fixed RAJDOOT Diplomatic Center.",
            callback=show_diplomat_dashboard,
        )

        member_import_command = app_commands.Command(
            name="import-embassy-members",
            description="Capture, merge, freeze, and hardcode current embassy members without touching legacy roles.",
            callback=import_embassy_members,
        )
        member_import_command.default_permissions = discord.Permissions(manage_guild=True)

        self.tree.add_command(government_command, guild=guild)
        self.tree.add_command(diplomat_command, guild=guild)
        self.tree.add_command(member_import_command, guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Guild dashboard commands synchronized")
        logger.info("Supabase PostgreSQL connection established")

    async def on_ready(self) -> None:
        guild = self.get_guild(settings.discord_guild_id)
        if guild is None:
            logger.error("Configured Discord guild was not found")
            return
        logger.info("Logged in as %s", self.user)
        logger.info("Connected to guild: %s (%s)", guild.name, guild.id)

        government_message = await ensure_dashboard_message(
            guild,
            settings.government_dashboard_channel_id,
            "government",
            self.database,
        )
        logger.info("Government dashboard ready: %s", government_message.id)

        diplomat_message = await ensure_dashboard_message(
            guild,
            settings.diplomat_dashboard_channel_id,
            "diplomat",
            self.database,
        )
        logger.info("Diplomat dashboard ready: %s", diplomat_message.id)

    async def _show_fixed_dashboard(self, interaction: discord.Interaction, kind: str) -> None:
        channel_id = (
            settings.government_dashboard_channel_id
            if kind == "government"
            else settings.diplomat_dashboard_channel_id
        )
        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None
        if channel is None:
            await interaction.response.send_message("⚠️ Dashboard channel is not available.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"📌 Fixed {kind} dashboard: {channel.mention}",
            ephemeral=True,
        )


def main() -> None:
    start_health_server()
    database = Database(settings.database_url)
    client = RajdootClient(database)
    asyncio.run(client.start(settings.discord_token))
