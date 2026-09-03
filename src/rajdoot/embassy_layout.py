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
    """Deterministic alphabetical embassy layout planner.

    Letter groups are kept intact. A category normally targets 50 embassies,
    but a small overflow is allowed when it prevents splitting a country-letter
    group; a single letter group may never itself exceed 50.
    """

    MAX_PER_CATEGORY = 50
    MAX_LETTER_GROUP_OVERFLOW = 5
    CATEGORY_NUMBER_PATTERN = re.compile(r"\bEmbassy\s*[-#:]?\s*(\d+)\b", re.IGNORECASE)

    @classmethod
    def plan(cls, embassies: list[dict]) -> LayoutPlan:
        active = [e for e in embassies if e.get("status") == "active" and e.get("channel_id")]
        active.sort(key=lambda e: str(e["country_name"]).strip().casefold())
        groups: list[list[dict]] = []
        for embassy in active:
            name = str(embassy["country_name"]).strip()
            if not name: raise ValueError(f"Embassy {embassy.get('id')} has an empty country name")
            letter = name[0].upper()
            if not groups or groups[-1][0]["_letter"] != letter: groups.append([])
            item = dict(embassy); item["_letter"] = letter; groups[-1].append(item)
        for group in groups:
            if len(group) > cls.MAX_PER_CATEGORY: raise ValueError(f"The {group[0]['_letter']} group contains {len(group)} embassies, which exceeds the category limit of {cls.MAX_PER_CATEGORY}.")

        categories: list[list[dict]] = []
        current: list[dict] = []
        for group in groups:
            if not current:
                current.extend(group); continue
            proposed = len(current) + len(group)
            if proposed <= cls.MAX_PER_CATEGORY or (proposed <= cls.MAX_PER_CATEGORY + cls.MAX_LETTER_GROUP_OVERFLOW and len(current) >= cls.MAX_PER_CATEGORY - cls.MAX_LETTER_GROUP_OVERFLOW):
                current.extend(group)
            else:
                categories.append(current); current = list(group)
        if current: categories.append(current)

        entries: list[LayoutEntry] = []; category_plans: list[CategoryPlan] = []; total_categories = len(categories)
        for category_index, category in enumerate(categories, start=1):
            category_entries: list[LayoutEntry] = []
            for position, embassy in enumerate(category):
                entry = LayoutEntry(str(embassy["id"]), str(embassy["country_name"]).strip(), int(embassy["channel_id"]), category_index, position)
                entries.append(entry); category_entries.append(entry)
            category_plans.append(CategoryPlan(category_index, tuple(category_entries), cls.category_name(category_index, category_entries, is_final=category_index == total_categories)))
        return LayoutPlan(tuple(category_plans), tuple(entries))

    @staticmethod
    def category_name(index: int, entries: list[LayoutEntry] | tuple[LayoutEntry, ...], *, is_final: bool = False) -> str:
        if not entries: return f"Embassy {index}"
        first = entries[0].country_name.strip()[0].upper(); last = "Z" if is_final else entries[-1].country_name.strip()[0].upper()
        return f"Embassy {index} ({first}-{last})"

    @classmethod
    def category_number_from_name(cls, name: str) -> int | None:
        match = cls.CATEGORY_NUMBER_PATTERN.search(name); return int(match.group(1)) if match else None

    @classmethod
    def discord_category_number(cls, category: discord.CategoryChannel) -> int | None:
        return cls.category_number_from_name(category.name)


class EmbassyDiscordOrganizer:
    MAX_CHANNELS_PER_CATEGORY = 50

    @staticmethod
    def embassy_slug(country_name: str) -> str:
        value = country_name.strip().casefold(); value = re.sub(r"[^a-z0-9]+", "-", value); value = value.strip("-"); return value[:100] or "embassy"

    @staticmethod
    def find_embassy_categories(guild: discord.Guild) -> list[discord.CategoryChannel]:
        categories = [c for c in guild.categories if EmbassyLayoutPlanner.discord_category_number(c) is not None]
        return sorted(categories, key=lambda c: (EmbassyLayoutPlanner.discord_category_number(c) or 0, c.position))

    async def ensure_categories(self, guild: discord.Guild, plan: LayoutPlan, *, allow_creation: bool = True) -> list[discord.CategoryChannel]:
        categories = self.find_embassy_categories(guild)
        if not allow_creation and len(categories) < len(plan.categories): raise RuntimeError(f"Embassy layout requires {len(plan.categories)} categories, but only {len(categories)} existing Embassy categories were found.")
        while len(categories) < len(plan.categories):
            template = categories[-1] if categories else None
            if template is None: raise RuntimeError("No existing Embassy category exists to clone. Create Embassy 1 manually before the first synchronization.")
            overwrites = dict(template.overwrites); next_index = len(categories) + 1
            category = await guild.create_category(name=f"Embassy {next_index}", overwrites=overwrites, reason="RAJDOOT embassy category expansion")
            await category.edit(position=template.position + 1, reason="RAJDOOT embassy category placement")
            categories.append(category); categories.sort(key=lambda item: item.position)
        return categories

    async def apply_plan(self, guild: discord.Guild, plan: LayoutPlan, *, allow_category_creation: bool = True) -> dict[str, int]:
        categories = await self.ensure_categories(guild, plan, allow_creation=allow_category_creation)
        categories_by_number = {n: c for c in categories if (n := EmbassyLayoutPlanner.discord_category_number(c)) is not None}
        changed_categories = reordered_categories = changed_channels = renamed_channels = 0
        for category_plan in plan.categories:
            category = categories_by_number.get(category_plan.index)
            if category is None: raise RuntimeError(f"Missing Discord category Embassy {category_plan.index}")
            if category.name != category_plan.name:
                await category.edit(name=category_plan.name, reason="RAJDOOT embassy alphabetical layout"); changed_categories += 1
        if categories:
            base = min(c.position for c in categories)
            for category_plan in plan.categories:
                category = categories_by_number.get(category_plan.index)
                if category and category.position != base + category_plan.index - 1:
                    await category.edit(position=base + category_plan.index - 1, reason="RAJDOOT embassy category ordering"); reordered_categories += 1
        desired_by_id = {entry.channel_id: entry for entry in plan.entries}
        for channel_id, entry in desired_by_id.items():
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                desired_name = self.embassy_slug(entry.country_name)
                if channel.name != desired_name: await channel.edit(name=desired_name, reason="RAJDOOT embassy canonical channel name"); renamed_channels += 1
        current_counts = {c.id: len(c.channels) for c in categories}; desired_category_by_channel = {cid: categories_by_number[e.category_index].id for cid, e in desired_by_id.items()}
        pending_moves = {cid: (guild.get_channel(cid), target) for cid, target in desired_category_by_channel.items() if isinstance(guild.get_channel(cid), discord.TextChannel) and guild.get_channel(cid).category_id != target}
        embassy_ids = set(desired_by_id); non_embassy_counts = {c.id: sum(1 for ch in c.channels if ch.id not in embassy_ids) for c in categories}; desired_counts = {c.id: 0 for c in categories}
        for entry in plan.entries: desired_counts[categories_by_number[entry.category_index].id] += 1
        for category in categories:
            final_count = non_embassy_counts[category.id] + desired_counts[category.id]
            if final_count > self.MAX_CHANNELS_PER_CATEGORY: raise RuntimeError(f"Embassy layout cannot fit in {category.name}: final channel count would be {final_count}, exceeding Discord's {self.MAX_CHANNELS_PER_CATEGORY}-channel category limit. Move unrelated channels out of the Embassy category first.")
        while pending_moves:
            candidate = next(((cid, channel, target) for cid, (channel, target) in pending_moves.items() if current_counts.get(target, 0) < self.MAX_CHANNELS_PER_CATEGORY), None)
            if candidate is None: raise RuntimeError("Embassy channels cannot be safely redistributed because every required destination category is currently full. No unrelated channels were displaced.")
            cid, channel, target = candidate; target_category = guild.get_channel(target)
            if not isinstance(channel, discord.TextChannel) or not isinstance(target_category, discord.CategoryChannel): raise RuntimeError("Missing embassy channel or target category during layout reconciliation")
            source = channel.category_id; await channel.edit(category=target_category, reason="RAJDOOT embassy category placement")
            if source in current_counts: current_counts[source] -= 1
            current_counts[target] = current_counts.get(target, 0) + 1; changed_channels += 1; del pending_moves[cid]
        for category_plan in plan.categories:
            category = categories_by_number[category_plan.index]
            for entry in category_plan.entries:
                channel = guild.get_channel(entry.channel_id)
                if isinstance(channel, discord.TextChannel):
                    desired_position = category.position + 1 + entry.position
                    if channel.position != desired_position: await channel.edit(position=desired_position, reason="RAJDOOT embassy alphabetical layout"); changed_channels += 1
        return {"categories_changed": changed_categories, "categories_reordered": reordered_categories, "channels_moved": changed_channels, "channels_renamed": renamed_channels}
