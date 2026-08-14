from __future__ import annotations

from dataclasses import dataclass

import discord


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    embassy_id: str
    country_name: str
    channel_id: int
    category_index: int
    position: int


class EmbassyLayoutPlanner:
    """Calculates the desired Discord embassy layout without touching Discord."""

    MAX_PER_CATEGORY = 50

    @classmethod
    def plan(cls, embassies: list[dict]) -> list[LayoutEntry]:
        active = [e for e in embassies if e.get("status") == "active" and e.get("channel_id")]
        active.sort(key=lambda e: str(e["country_name"]).casefold())

        groups: list[list[dict]] = []
        for embassy in active:
            letter = str(embassy["country_name"]).strip()[:1].casefold()
            if not groups or groups[-1][0]["_letter"] != letter:
                groups.append([])
            item = dict(embassy)
            item["_letter"] = letter
            groups[-1].append(item)

        categories: list[list[dict]] = []
        current: list[dict] = []
        for group in groups:
            if current and len(current) + len(group) > cls.MAX_PER_CATEGORY:
                categories.append(current)
                current = []
            current.extend(group)
        if current:
            categories.append(current)

        result: list[LayoutEntry] = []
        for category_index, category in enumerate(categories, start=1):
            for position, embassy in enumerate(category):
                result.append(
                    LayoutEntry(
                        embassy_id=str(embassy["id"]),
                        country_name=str(embassy["country_name"]),
                        channel_id=int(embassy["channel_id"]),
                        category_index=category_index,
                        position=position,
                    )
                )
        return result

    @staticmethod
    def category_name(index: int, entries: list[LayoutEntry]) -> str:
        if not entries:
            return f"Embassy {index}"
        letters = [e.country_name.strip()[:1].upper() for e in entries]
        return f"Embassy {index} ({letters[0]}-{letters[-1]})"


class EmbassyDiscordOrganizer:
    """Applies only required Discord changes and avoids needless mutations."""

    async def apply_category_moves(
        self,
        moves: list[tuple[discord.TextChannel, discord.CategoryChannel]],
    ) -> int:
        changed = 0
        for channel, category in moves:
            if channel.category_id == category.id:
                continue
            await channel.edit(category=category, reason="RAJDOOT embassy layout")
            changed += 1
        return changed

    async def bulk_reorder(
        self,
        guild: discord.Guild,
        positions: dict[discord.abc.GuildChannel, int],
    ) -> None:
        if positions:
            await guild.edit_channel_positions(
                positions=positions,
                reason="RAJDOOT embassy alphabetical layout",
            )
