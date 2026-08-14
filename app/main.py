import asyncio
import logging
import os

import discord
from discord.ext import commands

from .config import settings
from .health import start_health_server
from core.database import Database
from migration.embassy_seed import seed_legacy_embassies
from migration.legacy_access import LegacyAccessMigration
from migration.rollback_legacy_access import rollback_if_requested

# Apply Embassy-flow fixes before any user-facing extensions are loaded.
import app.embassy_patches  # noqa: F401,E402
import app.integration_patches  # noqa: F401,E402
import app.embassy_user_fixes  # noqa: F401,E402
import app.safety_patches  # noqa: F401,E402
import app.integration_completion  # noqa: F401,E402
import app.final_hardening  # noqa: F401,E402
import app.otp_ui_fix  # noqa: F401,E402
from app.cogs.dashboards import ensure_dashboards  # noqa: E402
from app.integration_completion import restore_surprise_views  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
logger = logging.getLogger("india-embassy-bot")


class EmbassyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.health_runner = None
        self.database = Database(settings.mongodb_uri, settings.mongodb_database)
        self.legacy_embassy_migration_done = False
        self.legacy_access_sync_done = False
        self.dashboards_initialized = False

    async def setup_hook(self) -> None:
        self.health_runner = await start_health_server(settings.health_host, settings.health_port)
        await self.database.initialize()
        await restore_surprise_views(self)

        await self.load_extension("app.cogs.complete")
        await self.load_extension("app.cogs.embassy_requests")
        await self.load_extension("app.cogs.post_verification")
        await self.load_extension("app.cogs.recovery")

        guild = discord.Object(id=settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Complete Embassy System loaded and guild commands synchronized")

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)
        guild = self.get_guild(settings.discord_guild_id)
        if guild is None:
            logger.error("Configured guild %s is not available", settings.discord_guild_id)
            return

        logger.info("Connected to guild: %s (%s)", guild.name, guild.id)

        if not self.legacy_embassy_migration_done:
            try:
                result = await seed_legacy_embassies(self.database, guild)
                self.legacy_embassy_migration_done = True
                if result["status"]:
                    logger.info(
                        "Legacy Embassy registry seeded: inserted=%s updated=%s missing_channels=%s",
                        result["inserted"], result["updated"], result["missing_channels"],
                    )
            except Exception:
                logger.exception("Legacy Embassy registry seed failed")

        # The old direct-permission migration is now retired. Never recreate
        # direct overrides on startup. If LEGACY_ACCESS_ROLLBACK is enabled in
        # Render, perform the one-shot restoration of legacy role membership and
        # remove only the migration-created per-member channel permissions.
        rollback_requested = os.getenv("LEGACY_ACCESS_ROLLBACK", "").strip().lower() in {"1", "true", "yes"}
        if rollback_requested:
            try:
                result = await rollback_if_requested(self.database, guild)
                logger.info("Legacy Embassy direct-access rollback result: %s", result)
            except Exception:
                logger.exception("Legacy Embassy direct-access rollback failed")
        elif not self.legacy_access_sync_done:
            logger.info("Legacy direct-access migration is retired; no direct permissions will be recreated")
            self.legacy_access_sync_done = True

        if not self.dashboards_initialized:
            try:
                await ensure_dashboards(self, guild)
                self.dashboards_initialized = True
                logger.info("Persistent Embassy dashboards initialized")
            except Exception:
                logger.exception("Dashboard initialization failed")

    async def close(self) -> None:
        if self.health_runner is not None:
            await self.health_runner.cleanup()
        await self.database.close()
        await super().close()


async def run() -> None:
    bot = EmbassyBot()
    async with bot:
        await bot.start(settings.discord_token)
