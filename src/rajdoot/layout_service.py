from __future__ import annotations

import discord

from rajdoot.database import Database
from rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner


class EmbassyLayoutService:
    """Coordinate the database layout plan with the live Discord structure."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.organizer = EmbassyDiscordOrganizer()

    async def synchronize(self, guild: discord.Guild) -> dict[str, int]:
        embassies = await self.database.fetch_active_embassies()
        plan = EmbassyLayoutPlanner.plan(embassies)
        result = await self.organizer.apply_plan(guild, plan)

        updates: list[tuple[str, int, int, int]] = []
        categories = self.organizer.find_embassy_categories(guild)
        categories_by_number = {
            number: category
            for category in categories
            if (number := EmbassyLayoutPlanner.discord_category_number(category)) is not None
        }

        for entry in plan.entries:
            category = categories_by_number.get(entry.category_index)
            if category is None:
                continue
            updates.append(
                (
                    entry.embassy_id,
                    category.id,
                    entry.channel_id,
                    entry.position,
                )
            )

        await self.database.update_embassy_layout_state(updates)
        return result
