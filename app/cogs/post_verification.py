from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

from app.cogs.embassy_flow import EmbassyFlow, EmbassyApprovalView
from app.config import settings
from core.state import RequestState
from approval.workflow import Route

logger = logging.getLogger(__name__)


class EmbassyChoicePersistentView(discord.ui.View):
    """Persistent, request-specific Embassy choice controls."""

    def __init__(self, bot: commands.Bot, request_id: str, country_name: str | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        self.request_id = request_id
        embassy_label = f"{country_name} Embassy" if country_name else "Your Country Embassy"

        own = discord.ui.Button(
            label=embassy_label[:80],
            emoji="🏛️",
            style=discord.ButtonStyle.success,
            custom_id=f"embassy:choice:own:{request_id}",
        )
        other = discord.ui.Button(
            label="Want to join another Embassy",
            emoji="🌍",
            style=discord.ButtonStyle.primary,
            custom_id=f"embassy:choice:other:{request_id}",
        )
        own.callback = self._own
        other.callback = self._other
        self.add_item(own)
        self.add_item(other)

    async def _own(self, interaction: discord.Interaction) -> None:
        await EmbassyFlow(self.bot).process_choice(interaction, self.request_id, "own")

    async def _other(self, interaction: discord.Interaction) -> None:
        await EmbassyFlow(self.bot).process_choice(interaction, self.request_id, "other")


class PostVerificationCog(commands.Cog):
    """Bridges VERIFIED requests into the Embassy routing workflow.

    The verification cog deliberately owns WarEra verification only. This cog
    watches the durable request state and starts the Embassy-selection stage.
    That keeps a Discord restart from losing the next step: VERIFIED requests
    are recovered from MongoDB and their persistent controls are registered
    again on startup.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._processed_cache: set[str] = set()
        self.process_verified_requests.start()

    def cog_unload(self) -> None:
        self.process_verified_requests.cancel()

    async def cog_load(self) -> None:
        await self._restore_pending_controls()

    async def _restore_pending_controls(self) -> None:
        requests = self.bot.database.collection("requests")
        verified = requests.find({"state": RequestState.VERIFIED.value, "active": True})
        async for request in verified:
            request_id = str(request["request_id"])
            country_name = str(request.get("verified_country_name") or "Your Country")
            self.bot.add_view(EmbassyChoicePersistentView(self.bot, request_id, country_name))

        reviews = requests.find({"state": {"$in": [RequestState.DIPLOMAT_REVIEW.value, RequestState.GOVERNMENT_REVIEW.value]}, "active": True})
        async for request in reviews:
            route = str(request.get("approval_route") or "")
            if route in {Route.FOREIGN_DIPLOMAT.value, Route.GOVERNMENT_REVIEW.value}:
                self.bot.add_view(EmbassyApprovalView(self.bot, str(request["request_id"]), route))

    @tasks.loop(seconds=2.0)
    async def process_verified_requests(self) -> None:
        collection = self.bot.database.collection("requests")
        cursor = collection.find({"state": RequestState.VERIFIED.value, "active": True, "post_verification_sent": {"$ne": True}}).limit(10)
        async for request in cursor:
            request_id = str(request["request_id"])
            if request_id in self._processed_cache:
                continue

            # Claim the request atomically so a future multi-instance deployment
            # cannot post the Embassy selection twice.
            result = await collection.update_one(
                {"request_id": request_id, "state": RequestState.VERIFIED.value, "active": True, "post_verification_sent": {"$ne": True}},
                {"$set": {"post_verification_sent": True}},
            )
            if result.modified_count != 1:
                continue
            self._processed_cache.add(request_id)

            thread = self.bot.get_channel(int(request["thread_id"]))
            if not isinstance(thread, discord.Thread):
                try:
                    thread = await self.bot.fetch_channel(int(request["thread_id"]))
                except discord.HTTPException:
                    logger.exception("Unable to fetch Embassy request thread %s", request["thread_id"])
                    continue
            if not isinstance(thread, discord.Thread):
                continue

            country_name = str(request.get("verified_country_name") or "Your Country")
            embed = discord.Embed(
                title="🏛️ Embassy Access",
                description=(
                    "Your WarEra identity and company ownership have been successfully verified.\n\n"
                    f"**Verified Country:** {country_name}\n\n"
                    "Your verification is complete. Now tell us which Embassy you would like to join."
                ),
                color=discord.Color.green(),
            )
            view = EmbassyChoicePersistentView(self.bot, request_id, country_name)
            self.bot.add_view(view)
            await thread.send(embed=embed, view=view)

    @process_verified_requests.before_loop
    async def before_process(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PostVerificationCog(bot))
