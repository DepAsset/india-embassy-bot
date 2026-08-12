import asyncio
import logging

import discord
from discord.ext import commands

from .config import settings
from .health import start_health_server
from core.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
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

    async def setup_hook(self) -> None:
        await self.database.initialize()
        self.health_runner = await start_health_server(settings.health_host, settings.health_port)
        await self.load_extension("app.cogs.complete")
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

    async def close(self) -> None:
        if self.health_runner is not None:
            await self.health_runner.cleanup()
        await self.database.close()
        await super().close()


async def run() -> None:
    bot = EmbassyBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(run())
