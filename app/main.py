import asyncio
import logging

import discord
from discord.ext import commands

from .config import settings
from .health import start_health_server
from core.database import Database
from migration.embassy_seed import seed_legacy_embassies

# Apply Embassy-flow fixes before any user-facing extensions are loaded.
import app.embassy_patches  # noqa: F401,E402
import app.integration_patches  # noqa: F401,E402
import app.embassy_user_fixes  # noqa: F401,E402
import app.safety_patches  # noqa: F401,E402
import app.integration_completion  # noqa: F401,E402
import app.otp_ui_fix  # noqa: F401,E402
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

    async def setup_hook(self) -> None:
        # Bind Render's health port first so the Web Service has a live listener
        # even while MongoDB and Discord extensions are initializing.
        self.health_runner = await start_health_server(settings.health_host, settings.health_port)

        await self.database.initialize()

        # Restore the one-use welcome surprise buttons that belong to existing
        # accepted diplomats. Used surprises are registered as disabled views.
        await restore_surprise_views(self)

        # Load the dependency container first, then the user-facing request
        # controls, then durable post-verification and recovery handlers.
        # Dashboard wiring is intentionally kept in the real cog/view modules;
        # do not import legacy dashboard monkey-patch modules at startup.
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
                        "Legacy Embassy migration completed: inserted=%s updated=%s missing_channels=%s",
                        result["inserted"], result["updated"], result["missing_channels"],
                    )
            except Exception:
                logger.exception("Legacy Embassy migration failed")

    async def close(self) -> None:
        if self.health_runner is not None:
            await self.health_runner.cleanup()
        await self.database.close()
        await super().close()


async def run() -> None:
    bot = EmbassyBot()
    async with bot:
        await bot.start(settings.discord_token)
