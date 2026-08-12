from __future__ import annotations

import asyncio
from dataclasses import dataclass

import discord

from embassy.registry import Embassy


@dataclass(frozen=True)
class EmbassyGroup:
    index: int
    embassies: tuple[Embassy, ...]

    @property
    def range_label(self) -> str:
        if not self.embassies:
            return ""
        first = self.embassies[0].country_name[0].upper()
        last = self.embassies[-1].country_name[0].upper()
        return f"{first}-{last}" if first != last else first

    @property
    def category_name(self) -> str:
        return f"═══◈Embassy {self.index} ({self.range_label})◈═══"


class EmbassyOrganizer:
    """Rate-limit-aware planner/executor for the global Embassy order.

    This service intentionally does not mutate Discord concurrently. It computes
    the desired state first and then applies only necessary mutations, one at a
    time, with a small configurable delay. Actual Discord category/channel
    operations are injected so the organizer remains testable without Discord.
    """

    def __init__(self, mutation_delay: float = 0.75) -> None:
        self.mutation_delay = max(0.25, mutation_delay)
        self._lock = asyncio.Lock()

    @staticmethod
    def partition(embassies: list[Embassy], capacity: int) -> list[EmbassyGroup]:
        if capacity < 1:
            raise ValueError("Embassy category capacity must be positive")
        ordered = sorted(
            (embassy for embassy in embassies if embassy.active),
            key=lambda e: (e.country_name.casefold(), e.embassy_id),
        )
        return [
            EmbassyGroup(index=i + 1, embassies=tuple(ordered[i:i + capacity]))
            for i in range(0, len(ordered), capacity)
        ]

    async def organize(
        self,
        embassies: list[Embassy],
        capacity: int,
        categories: list[discord.CategoryChannel],
    ) -> list[EmbassyGroup]:
        async with self._lock:
            groups = self.partition(embassies, capacity)
            if len(categories) < len(groups):
                raise RuntimeError(
                    f"Need {len(groups)} Embassy categories but only {len(categories)} were supplied; "
                    "category creation must be performed by the management service."
                )

            # Rename only when the desired range changed. Category/channel moves
            # are intentionally serialized to avoid Discord rate-limit bursts.
            for group in groups:
                category = categories[group.index - 1]
                if category.name != group.category_name:
                    await category.edit(name=group.category_name, reason="Embassy alphabetical organizer")
                    await asyncio.sleep(self.mutation_delay)

            return groups

    @staticmethod
    def desired_channel_order(group: EmbassyGroup) -> list[int]:
        return [embassy.channel_id for embassy in group.embassies]

    @staticmethod
    def verify_global_order(groups: list[EmbassyGroup]) -> bool:
        flattened = [
            embassy.country_name.casefold()
            for group in groups
            for embassy in group.embassies
        ]
        return flattened == sorted(flattened)
