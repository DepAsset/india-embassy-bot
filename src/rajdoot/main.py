import asyncio
import logging

import discord

from rajdoot.config import settings
from rajdoot.database import Database


logger = logging.getLogger("rajdoot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class RajdootBot(discord.Client):
    def __init__(self, database: Database) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self.database = database

    async def setup_hook(self) -> None:
        await self.database.connect()
        logger.info("Supabase PostgreSQL connection established")

    async def on_ready(self) -> None:
        guild = self.get_guild(settings.discord_guild_id)
        if guild is None:
            logger.error("Configured Discord guild was not found")
            return
        logger.info("Logged in as %s", self.user)
        logger.info("Connected to guild: %s (%s)", guild.name, guild.id)

    async def close(self) -> None:
        await self.database.close()
        await super().close()


async def run() -> None:
    database = Database(settings.database_url)
    bot = RajdootBot(database)
    try:
        await bot.start(settings.discord_token)
    finally:
        await database.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
