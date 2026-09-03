from __future__ import annotations

import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import discord
from discord import app_commands

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.dashboards import GovernmentEmbassyView
from rajdoot.embassy_workflow import EmbassySelectionView, EmbassyStartView, CompanyView, PersistentApprovalView
from rajdoot.fixed_dashboards import FixedDiplomatDashboardView, FixedGovernmentDashboardView
from rajdoot.ui import ensure_dashboard_message
from rajdoot.verification_dashboard import FixedVerificationDashboardView

logger = logging.getLogger("rajdoot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/health", "/healthz"):
            self.send_response(404); self.end_headers(); return
        body = b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        self.do_GET()

    def log_message(self, format: str, *args: object) -> None:
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
        self._dashboard_lock = asyncio.Lock()

    async def _register_pending_workflow_views(self) -> None:
        connection = self.database._connection
        if connection is None:
            return
        async with connection.cursor() as cursor:
            await cursor.execute(
                """
                select id, applicant_discord_id, flow_stage, request_thread_id, warera_user_id,
                       profile_url, warera_profile_snapshot, otp_expires_at, approval_message_id,
                       target_embassy_id
                from embassy_requests
                where request_status in ('created', 'verifying', 'pending_approval')
                  and request_thread_id is not null
                order by created_at asc
                """
            )
            rows = await cursor.fetchall()
        guild = self.get_guild(settings.discord_guild_id)
        if guild is None:
            return
        registered = 0
        for row in rows:
            thread = guild.get_thread(int(row["request_thread_id"]))
            if thread is None:
                continue
            applicant = guild.get_member(int(row["applicant_discord_id"]))
            if applicant is None:
                continue
            stage = row.get("flow_stage")
            request_id = str(row["id"])
            if stage == "profile_pending":
                self.add_view(EmbassyStartView(self.database, request_id, thread))
                registered += 1
            elif stage == "company_verification" and row.get("warera_user_id"):
                profile_url = str(row.get("profile_url") or "https://app.warera.io/user/" + str(row["warera_user_id"]))
                self.add_view(CompanyView(self.database, request_id, applicant.id, str(row["warera_user_id"]), None, profile_url.rstrip("/") + "/companies"))
                registered += 1
            elif stage == "embassy_selection":
                profile = row.get("warera_profile_snapshot") or {}
                self.add_view(EmbassySelectionView(self.database, request_id, applicant, profile))
                registered += 1
            if stage in {"awaiting_embassy_approval", "awaiting_government_approval"} and row.get("approval_message_id") and row.get("target_embassy_id"):
                self.add_view(PersistentApprovalView(self.database, request_id, applicant.id, own_country=stage == "awaiting_embassy_approval"))
                registered += 1
        if registered:
            logger.info("Registered %s persistent workflow views", registered)

    async def setup_hook(self) -> None:
        await self.database.connect()
        self.add_view(FixedVerificationDashboardView(self.database))
        self.add_view(FixedGovernmentDashboardView(self.database))
        self.add_view(FixedDiplomatDashboardView(self.database))
        self.add_view(GovernmentEmbassyView(self.database))
        await self._register_pending_workflow_views()

        guild = discord.Object(id=settings.discord_guild_id)

        async def show_verification_dashboard(interaction: discord.Interaction) -> None:
            await self._show_fixed_dashboard(interaction, "verification")

        async def show_government_dashboard(interaction: discord.Interaction) -> None:
            if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator):
                await interaction.response.send_message("🔐 Only authorized government/server managers can open the Government Control Center.", ephemeral=True)
                return
            await self._show_fixed_dashboard(interaction, "government")

        async def show_diplomat_dashboard(interaction: discord.Interaction) -> None:
            await self._show_fixed_dashboard(interaction, "diplomat")

        self.tree.add_command(app_commands.Command(name="verification-dashboard", description="Open the fixed RAJDOOT Verification & Access Request dashboard.", callback=show_verification_dashboard), guild=guild)
        government_command = app_commands.Command(name="government-dashboard", description="Open the fixed RAJDOOT Government Control Center.", callback=show_government_dashboard)
        government_command.default_permissions = discord.Permissions(manage_guild=True)
        self.tree.add_command(government_command, guild=guild)
        self.tree.add_command(app_commands.Command(name="diplomat-dashboard", description="Open the fixed RAJDOOT Diplomatic Center.", callback=show_diplomat_dashboard), guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Guild dashboard commands synchronized: verification, government, diplomat")

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
        if kind == "verification":
            channel_id = settings.verification_dashboard_channel_id or config.get("verification_dashboard_channel_id"); message_id = settings.verification_dashboard_message_id or config.get("verification_dashboard_message_id"); label = "Verification & Access Request"
        elif kind == "government":
            channel_id = settings.government_dashboard_channel_id or config.get("government_dashboard_channel_id"); message_id = settings.government_dashboard_message_id or config.get("government_dashboard_message_id"); label = "Government Control Center"
        else:
            channel_id = settings.diplomat_dashboard_channel_id or config.get("diplomat_dashboard_channel_id"); message_id = settings.diplomat_dashboard_message_id or config.get("diplomat_dashboard_message_id"); label = "Diplomatic Center"
        if not channel_id or not message_id:
            await interaction.response.send_message(f"⚠️ The fixed {label} could not be located.", ephemeral=True); return
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("⚠️ The configured dashboard channel is no longer a text channel.", ephemeral=True); return
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.HTTPException):
            await self._ensure_dashboards(guild)
            config = await self.database.fetch_discord_configuration(guild.id) or {}
            message_id = ((settings.verification_dashboard_message_id or config.get("verification_dashboard_message_id")) if kind == "verification" else (settings.government_dashboard_message_id or config.get("government_dashboard_message_id")) if kind == "government" else (settings.diplomat_dashboard_message_id or config.get("diplomat_dashboard_message_id")))
            if not message_id:
                await interaction.response.send_message("⚠️ RAJDOOT could not restore the fixed dashboard.", ephemeral=True); return
            message = await channel.fetch_message(int(message_id))
        await interaction.response.send_message(f"📌 **{label}** is fixed and persistent: [Open dashboard]({message.jump_url})", ephemeral=True)

    async def _pin_dashboard(self, message: discord.Message, label: str) -> None:
        if message.pinned: return
        try:
            await message.pin(reason=f"RAJDOOT fixed {label} dashboard")
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning("Could not pin %s dashboard message %s: %s", label, message.id, exc)

    async def _ensure_dashboards(self, guild: discord.Guild) -> None:
        async with self._dashboard_lock:
            config = await self.database.fetch_discord_configuration(guild.id) or {}
            government_channel_id = settings.government_dashboard_channel_id or config.get("government_dashboard_channel_id")
            diplomat_channel_id = settings.diplomat_dashboard_channel_id or config.get("diplomat_dashboard_channel_id")
            verification_channel_id = settings.verification_dashboard_channel_id or config.get("verification_dashboard_channel_id")
            logs_channel_id = settings.logs_channel_id or config.get("logs_channel_id")
            request_category_id = settings.request_category_id or config.get("request_category_id")
            government_message_id = settings.government_dashboard_message_id or config.get("government_dashboard_message_id")
            diplomat_message_id = settings.diplomat_dashboard_message_id or config.get("diplomat_dashboard_message_id")
            verification_message_id = settings.verification_dashboard_message_id or config.get("verification_dashboard_message_id")

            if verification_channel_id:
                channel = guild.get_channel(int(verification_channel_id))
                if isinstance(channel, discord.TextChannel):
                    from rajdoot.verification_dashboard import ensure_verification_dashboard
                    message = await ensure_verification_dashboard(channel, self.database, int(verification_message_id) if verification_message_id else None)
                    verification_message_id = message.id; await self._pin_dashboard(message, "Verification & Access Request")
            if government_channel_id:
                channel = guild.get_channel(int(government_channel_id))
                if isinstance(channel, discord.TextChannel):
                    message = await ensure_dashboard_message(channel=channel, message_id=int(government_message_id) if government_message_id else None, embed=discord.Embed(title="🏛️ RAJDOOT Government Control Center", description="Fixed Government Control Center. Use **/government-dashboard** to return here.", colour=discord.Colour.blurple()), view=FixedGovernmentDashboardView(self.database))
                    government_message_id = message.id; await self._pin_dashboard(message, "Government Control Center")
            if diplomat_channel_id:
                channel = guild.get_channel(int(diplomat_channel_id))
                if isinstance(channel, discord.TextChannel):
                    message = await ensure_dashboard_message(channel=channel, message_id=int(diplomat_message_id) if diplomat_message_id else None, embed=discord.Embed(title="🌍 RAJDOOT Diplomatic Center", description="Fixed Diplomatic Center. Use **/diplomat-dashboard** to return here.", colour=discord.Colour.blurple()), view=FixedDiplomatDashboardView(self.database))
                    diplomat_message_id = message.id; await self._pin_dashboard(message, "Diplomatic Center")

            await self.database.upsert_discord_configuration(guild_id=guild.id, request_category_id=int(request_category_id) if request_category_id else None, logs_channel_id=int(logs_channel_id) if logs_channel_id else None, government_dashboard_channel_id=int(government_channel_id) if government_channel_id else None, government_dashboard_message_id=int(government_message_id) if government_message_id else None, diplomat_dashboard_channel_id=int(diplomat_channel_id) if diplomat_channel_id else None, diplomat_dashboard_message_id=int(diplomat_message_id) if diplomat_message_id else None, verification_dashboard_channel_id=int(verification_channel_id) if verification_channel_id else None, verification_dashboard_message_id=int(verification_message_id) if verification_message_id else None)


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
