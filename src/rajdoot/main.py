import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import discord
from discord import app_commands

from rajdoot.config import settings
from rajdoot.dashboards import DiplomatDashboardView, GovernmentEmbassyView
from rajdoot.database import Database
from rajdoot.embassy_access import EmbassyManagementCommands
from rajdoot.embassy_members import EmbassyMemberImporter
from rajdoot.embassy_workflow import EmbassyRequestCommands, PersistentApprovalView
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
        # Render health probes are expected infrastructure traffic. Keep the
        # application log focused on bot/database events instead of emitting a
        # line every five seconds.
        return


def start_health_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((settings.health_host, settings.health_port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="rajdoot-health", daemon=True)
    thread.start()
    logger.info("Health server listening on %s:%s", settings.health_host, settings.health_port)
    return server


class RajdootBot(discord.Client):
    def __init__(self, database: Database) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.database = database
        self.tree = app_commands.CommandTree(self)

    async def _register_pending_approval_views(self) -> None:
        connection = self.database._connection
        if connection is None:
            return
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                select id, applicant_discord_id, flow_stage
                from embassy_requests
                where request_status = 'pending_approval'
                  and approval_message_id is not null
                  and target_embassy_id is not null
                """
            )
            rows = await cursor.fetchall()
        for row in rows:
            self.add_view(
                PersistentApprovalView(
                    self.database,
                    str(row["id"]),
                    int(row["applicant_discord_id"]),
                    own_country=row["flow_stage"] == "awaiting_embassy_approval",
                )
            )
        if rows:
            logger.info("Registered %s persistent embassy approval views", len(rows))

    async def setup_hook(self) -> None:
        await self.database.connect()
        self.add_view(HomeView(self.database))
        self.add_view(FixedGovernmentDashboardView(self.database))
        self.add_view(FixedDiplomatDashboardView(self.database))
        self.add_view(DiplomatDashboardView(self.database))
        self.add_view(GovernmentEmbassyView(self.database))
        await self._register_pending_approval_views()

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
                await interaction.guild.chunk(cache=True)
                result = await EmbassyMemberImporter().import_current_members(interaction.guild, self.database)
            except Exception:
                logger.exception("Embassy member import/hardcode failed")
                await interaction.followup.send(
                    "⚠️ I could not safely complete the embassy member hardcoding. No embassy roles were deleted or modified. "
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
                "The Supabase registry is the canonical baseline. Direct member permissions survive deletion of legacy embassy access roles. "
                "This command never deletes or modifies the legacy embassy roles.",
                ephemeral=True,
            )

        government_command = app_commands.Command(
            name="government-dashboard", description="Jump to the fixed RAJDOOT Government Control Center.", callback=show_government_dashboard
        )
        government_command.default_permissions = discord.Permissions(manage_guild=True)
        diplomat_command = app_commands.Command(
            name="diplomat-dashboard", description="Jump to the fixed RAJDOOT Diplomatic Center.", callback=show_diplomat_dashboard
        )
        member_import_command = app_commands.Command(
            name="import-embassy-members", description="Capture, merge, freeze, and hardcode current embassy members without touching legacy roles.", callback=import_embassy_members
        )
        member_import_command.default_permissions = discord.Permissions(manage_guild=True)

        self.tree.add_command(government_command, guild=guild)
        self.tree.add_command(diplomat_command, guild=guild)
        self.tree.add_command(member_import_command, guild=guild)
        self.tree.add_command(EmbassyRequestCommands(self.database), guild=guild)
        self.tree.add_command(EmbassyManagementCommands(self.database), guild=guild)
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
        await self._ensure_dashboards(guild)

    async def _show_fixed_dashboard(self, interaction: discord.Interaction, kind: str) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("🌿 This command must be used inside the embassy server.", ephemeral=True)
            return
        await self._ensure_dashboards(guild)
        config = await self.database.fetch_discord_configuration(guild.id) or {}
        if kind == "government":
            channel_id = settings.government_dashboard_channel_id or config.get("government_dashboard_channel_id")
            message_id = settings.government_dashboard_message_id or config.get("government_dashboard_message_id")
            label = "Government Control Center"
        else:
            channel_id = settings.diplomat_dashboard_channel_id or config.get("diplomat_dashboard_channel_id")
            message_id = settings.diplomat_dashboard_message_id or config.get("diplomat_dashboard_message_id")
            label = "Diplomatic Center"
        if not channel_id or not message_id:
            await interaction.response.send_message(f"⚠️ The fixed {label} could not be located.", ephemeral=True)
            return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("⚠️ The configured dashboard channel is no longer a text channel.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.HTTPException):
            await self._ensure_dashboards(guild)
            config = await self.database.fetch_discord_configuration(guild.id) or {}
            message_id = (settings.government_dashboard_message_id or config.get("government_dashboard_message_id")) if kind == "government" else (settings.diplomat_dashboard_message_id or config.get("diplomat_dashboard_message_id"))
            if not message_id:
                await interaction.response.send_message("⚠️ RAJDOOT could not restore the fixed dashboard.", ephemeral=True)
                return
            message = await channel.fetch_message(int(message_id))
        await interaction.response.send_message(f"📌 **{label}** is fixed and persistent: [Open dashboard]({message.jump_url})", ephemeral=True)

    async def _pin_dashboard(self, message: discord.Message, label: str) -> None:
        if message.pinned:
            return
        try:
            await message.pin(reason=f"RAJDOOT fixed {label} dashboard")
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Could not pin %s dashboard message %s: %s", label, message.id, exc)

    async def _ensure_dashboards(self, guild: discord.Guild) -> None:
        config = await self.database.fetch_discord_configuration(guild.id) or {}
        government_channel_id = settings.government_dashboard_channel_id or config.get("government_dashboard_channel_id")
        diplomat_channel_id = settings.diplomat_dashboard_channel_id or config.get("diplomat_dashboard_channel_id")
        logs_channel_id = settings.logs_channel_id or config.get("logs_channel_id")
        request_category_id = settings.request_category_id or config.get("request_category_id")
        government_message_id = settings.government_dashboard_message_id or config.get("government_dashboard_message_id")
        diplomat_message_id = settings.diplomat_dashboard_message_id or config.get("diplomat_dashboard_message_id")
        if government_channel_id:
            channel = guild.get_channel(int(government_channel_id))
            if isinstance(channel, discord.TextChannel):
                message = await ensure_dashboard_message(
                    channel=channel, message_id=int(government_message_id) if government_message_id else None,
                    embed=discord.Embed(title="🏛️ RAJDOOT Government Control Center", description="Welcome back. 🌍\n\nThis is the **fixed Government Control Center**. Its buttons open new messages below, so this dashboard never gets replaced or lost.\n\nUse **/government-dashboard** anytime to jump back here.", colour=discord.Colour.blurple()),
                    view=FixedGovernmentDashboardView(self.database),
                )
                government_message_id = message.id
                await self._pin_dashboard(message, "Government Control Center")
        if diplomat_channel_id:
            channel = guild.get_channel(int(diplomat_channel_id))
            if isinstance(channel, discord.TextChannel):
                message = await ensure_dashboard_message(
                    channel=channel, message_id=int(diplomat_message_id) if diplomat_message_id else None,
                    embed=discord.Embed(title="🌍 RAJDOOT Diplomatic Center", description="Welcome, diplomat. ✨\n\nThis is the **fixed Diplomatic Center**. Its buttons open new messages below, so the main dashboard stays in place.\n\nUse **/diplomat-dashboard** anytime to jump back here.", colour=discord.Colour.blurple()),
                    view=FixedDiplomatDashboardView(self.database),
                )
                diplomat_message_id = message.id
                await self._pin_dashboard(message, "Diplomatic Center")
        await self.database.upsert_discord_configuration(
            guild_id=guild.id,
            request_category_id=int(request_category_id) if request_category_id else None,
            logs_channel_id=int(logs_channel_id) if logs_channel_id else None,
            government_dashboard_channel_id=int(government_channel_id) if government_channel_id else None,
            government_dashboard_message_id=int(government_message_id) if government_message_id else None,
            diplomat_dashboard_channel_id=int(diplomat_channel_id) if diplomat_channel_id else None,
            diplomat_dashboard_message_id=int(diplomat_message_id) if diplomat_message_id else None,
        )


async def _run() -> None:
    database = Database(settings.database_url)
    health_server = start_health_server()
    bot = RajdootBot(database)
    try:
        await bot.start(settings.discord_token)
    finally:
        health_server.shutdown()
        await database.close()


def main() -> None:
    asyncio.run(_run())
