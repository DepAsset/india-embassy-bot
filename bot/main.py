import asyncio
import logging

import discord
from discord.ext import commands
from fastapi import FastAPI
import uvicorn

from .config import settings
from .db import Database
from .embassy import EmbassyCog
from .warera import WarEraClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("india-embassy-bot")

app = FastAPI(title="India Embassy Bot")


@app.get("/health")
async def health():
    return {"status": "ok"}


class EmbassyBot(commands.Bot):
    def __init__(self, db: Database, warera: WarEraClient):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.db = db
        self.warera = warera

    async def setup_hook(self) -> None:
        await self.db.ensure_indexes()
        await self.add_cog(EmbassyCog(self, self.db, self.warera))
        guild = discord.Object(id=settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        log.info("Synced embassy commands to guild %s", settings.discord_guild_id)

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")


async def run_web() -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=10000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def run_bot() -> None:
    db = Database()
    warera = WarEraClient()
    bot = EmbassyBot(db, warera)
    try:
        await bot.start(settings.discord_token)
    finally:
        await db.close()


async def main() -> None:
    await asyncio.gather(run_bot(), run_web())


if __name__ == "__main__":
    asyncio.run(main())
