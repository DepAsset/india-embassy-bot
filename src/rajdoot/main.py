import asyncio
import logging

import discord

from rajdoot.config import settings
from rajdoot.database import Database
from rajdoot.dashboards import DiplomatDashboardView, GovernmentDashboardView
from rajdoot.ui import HomeView, ensure_dashboard_message, home_embed


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
        self.add_view(HomeView(self.database))
        self.add_view(GovernmentDashboardView(self.database))
        self.add_view(DiplomatDashboardView(self.database))
        logger.info("Supabase PostgreSQL connection established")

    async def on_ready(self) -> None:
        guild = self.get_guild(settings.discord_guild_id)
        if guild is None:
            logger.error("Configured Discord guild was not found")
            return

        logger.info("Logged in as %s", self.user)
        logger.info("Connected to guild: %s (%s)", guild.name, guild.id)
        await self._ensure_dashboards(guild)

    async def _ensure_dashboards(self, guild: discord.Guild) -> None:
        if settings.government_dashboard_channel_id:
            channel = guild.get_channel(settings.government_dashboard_channel_id)
            if isinstance(channel, discord.TextChannel):
                message = await ensure_dashboard_message(
                    channel=channel,
                    message_id=settings.government_dashboard_message_id,
                    embed=discord.Embed(
                        title="🏛️ RAJDOOT Government Control Center",
                        description=(
                            "Welcome back. 🌍\n\n"
                            "Everything important is gathered here so you can manage diplomacy "
                            "without hunting through commands or channels."
                        ),
                        colour=discord.Colour.blurple(),
                    ),
                    view=GovernmentDashboardView(self.database),
                )
                logger.info("Government dashboard ready: %s", message.id)
            else:
                logger.warning("Government dashboard channel is not a text channel")

        if settings.diplomat_dashboard_channel_id:
            channel = guild.get_channel(settings.diplomat_dashboard_channel_id)
            if isinstance(channel, discord.TextChannel):
                message = await ensure_dashboard_message(
                    channel=channel,
                    message_id=settings.diplomat_dashboard_message_id,
                    embed=discord.Embed(
                        title="🌍 RAJDOOT Diplomatic Center",
                        description=(
                            "Welcome, diplomat. ✨\n\n"
                            "Your embassies, profile and diplomatic tools are all connected here. "
                            "Choose what you need and let RAJDOOT handle the rest."
                        ),
                        colour=discord.Colour.blurple(),
                    ),
                    view=DiplomatDashboardView(self.database),
                )
                logger.info("Diplomat dashboard ready: %s", message.id)
            else:
                logger.warning("Diplomat dashboard channel is not a text channel")

        if settings.logs_channel_id:
            channel = guild.get_channel(settings.logs_channel_id)
            if not isinstance(channel, discord.TextChannel):
                logger.warning("Configured Logs channel is not a text channel")

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
