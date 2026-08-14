from __future__ import annotations

from dataclasses import dataclass
import re

import discord


@dataclass(frozen=True, slots=True)
class LayoutEntry:
    embassy_id: str
    country_name: str
    channel_id: int
    category_index: int
    position: int


@dataclass(frozen=True, slots=True)
class CategoryPlan:
    index: int
    entries: tuple[LayoutEntry, ...]
    name: str


@dataclass(frozen=True, slots=True)
class LayoutPlan:
    categories: tuple[CategoryPlan, ...]
    entries: tuple[LayoutEntry, ...]


class EmbassyLayoutPlanner:
    """Calculate the desired embassy layout without touching Discord."""

    MAX_PER_CATEGORY = 50
    CATEGORY_PATTERN = re.compile(r"^Embassy\s+(\d+)(?:\s+\([A-Z]-[A-Z]\))?$")

    @classmethod
    def plan(cls, embassies: list[dict]) -> LayoutPlan:
        active = [
            e
            for e in embassies
            if e.get("status") == "active" and e.get("channel_id")
        ]
        active.sort(key=lambda e: str(e["country_name"]).strip().casefold())

        groups: list[list[dict]] = []
        for embassy in active:
            name = str(embassy["country_name"]).strip()
            if not name:
                raise ValueError(f"Embassy {embassy.get('id')} has an empty country name")
            letter = name[0].upper()
            if not groups or groups[-1][0]["_letter"] != letter:
                groups.append([])
            item = dict(embassy)
            item["_letter"] = letter
            groups[-1].append(item)

        for group in groups:
            if len(group) > cls.MAX_PER_CATEGORY:
                raise ValueError(
                    f"The {group[0]['_letter']} group contains {len(group)} embassies, "
                    f"which exceeds the category limit of {cls.MAX_PER_CATEGORY}."
                )

        categories: list[list[dict]] = []
        current: list[dict] = []
        for group in groups:
            if current and len(current) + len(group) > cls.MAX_PER_CATEGORY:
                categories.append(current)
                current = []
            current.extend(group)
        if current:
            categories.append(current)

        entries: list[LayoutEntry] = []
        category_plans: list[CategoryPlan] = []
        total_categories = len(categories)
        for category_index, category in enumerate(categories, start=1):
            category_entries: list[LayoutEntry] = []
            for position, embassy in enumerate(category):
                entry = LayoutEntry(
                    embassy_id=str(embassy["id"]),
                    country_name=str(embassy["country_name"]).strip(),
                    channel_id=int(embassy["channel_id"]),
                    category_index=category_index,
                    position=position,
                )
                entries.append(entry)
                category_entries.append(entry)
            category_plans.append(
                CategoryPlan(
                    index=category_index,
                    entries=tuple(category_entries),
                    name=cls.category_name(
                        category_index,
                        category_entries,
                        is_final=(category_index == total_categories),
                    ),
                )
            )

        return LayoutPlan(categories=tuple(category_plans), entries=tuple(entries))

    @staticmethod
    def category_name(
        index: int,
        entries: list[LayoutEntry] | tuple[LayoutEntry, ...],
        *,
        is_final: bool = False,
    ) -> str:
        if not entries:
            return f"Embassy {index}"
        first = entries[0].country_name.strip()[0].upper()
        last = "Z" if is_final else entries[-1].country_name.strip()[0].upper()
        return f"Embassy {index} ({first}-{last})"

    @classmethod
    def discord_category_number(cls, category: discord.CategoryChannel) -> int | None:
        match = cls.CATEGORY_PATTERN.fullmatch(category.name)
        return int(match.group(1)) if match else None


class EmbassyDiscordOrganizer:
    """Apply only the Discord changes required by a layout plan."""

    CATEGORY_DELAY_SECONDS = 0.35

    @staticmethod
    def embassy_slug(country_name: str) -> str:
        value = country_name.strip().casefold()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        value = value.strip("-")
        return value[:100] or "embassy"

    @staticmethod
    def find_embassy_categories(guild: discord.Guild) -> list[discord.CategoryChannel]:
        categories = [
            category
            for category in guild.categories
            if EmbassyLayoutPlanner.discord_category_number(category) is not None
        ]
        return sorted(
            categories,
            key=lambda category: EmbassyLayoutPlanner.discord_category_number(category) or 0,
        )

    async def ensure_categories(
        self,
        guild: discord.Guild,
        plan: LayoutPlan,
    ) -> list[discord.CategoryChannel]:
        categories = self.find_embassy_categories(guild)

        while len(categories) < len(plan.categories):
            template = categories[-1] if categories else None
            if template is None:
                raise RuntimeError(
                    "No existing Embassy category exists to clone. "
                    "Create Embassy 1 manually before the first synchronization."
                )

            overwrites = dict(template.overwrites)
            next_index = len(categories) + 1
            category = await guild.create_category(
                name=f"Embassy {next_index}",
                overwrites=overwrites,
                reason="RAJDOOT embassy category expansion",
            )
            await category.edit(
                position=template.position + 1,
                reason="RAJDOOT embassy category placement",
            )
            categories.append(category)
            categories.sort(key=lambda item: item.position)

        return categories

    async def apply_plan(
        self,
        guild: discord.Guild,
        plan: LayoutPlan,
    ) -> dict[str, int]:
        categories = await self.ensure_categories(guild, plan)
        categories_by_number = {
            number: category
            for category in categories
            if (number := EmbassyLayoutPlanner.discord_category_number(category)) is not None
        }

        changed_categories = 0
        changed_channels = 0
        renamed_channels = 0

        for category_plan in plan.categories:
            category = categories_by_number.get(category_plan.index)
            if category is None:
                raise RuntimeError(f"Missing Discord category Embassy {category_plan.index}")
            if category.name != category_plan.name:
                await category.edit(
                    name=category_plan.name,
                    reason="RAJDOOT embassy alphabetical layout",
                )
                changed_categories += 1

        desired_by_id = {entry.channel_id: entry for entry in plan.entries}
        for channel_id, entry in desired_by_id.items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            target_category = categories_by_number[entry.category_index]
            desired_name = self.embassy_slug(entry.country_name)

            if channel.name != desired_name:
                await channel.edit(
                    name=desired_name,
                    reason="RAJDOOT embassy canonical channel name",
                )
                renamed_channels += 1

            if channel.category_id != target_category.id:
                await channel.edit(
                    category=target_category,
                    reason="RAJDOOT embassy category placement",
                )
                changed_channels += 1

        positions: dict[discord.abc.GuildChannel, int] = {}
        for category_plan in plan.categories:
            category = categories_by_number[category_plan.index]
            for entry in category_plan.entries:
                channel = guild.get_channel(entry.channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                desired_position = category.position + 1 + entry.position
                if channel.position != desired_position:
                    positions[channel] = desired_position

        if positions:
            await guild.edit_channel_positions(
                positions=positions,
                reason="RAJDOOT embassy alphabetical layout",
            )
            changed_channels += len(positions)

        return {
            "categories_changed": changed_categories,
            "channels_moved": changed_channels,
            "channels_renamed": renamed_channels,
        }
