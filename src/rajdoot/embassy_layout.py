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
    CATEGORY_NUMBER_PATTERN = re.compile(r"\bEmbassy\s*[-#:]?\s*(\d+)\b", re.IGNORECASE)

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
    def category_number_from_name(cls, name: str) -> int | None:
        match = cls.CATEGORY_NUMBER_PATTERN.search(name)
        return int(match.group(1)) if match else None

    @classmethod
    def discord_category_number(cls, category: discord.CategoryChannel) -> int | None:
        return cls.category_number_from_name(category.name)


class EmbassyDiscordOrganizer:
    """Apply only the Discord changes required by a layout plan."""

    MAX_CHANNELS_PER_CATEGORY = 50

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
            key=lambda category: (
                EmbassyLayoutPlanner.discord_category_number(category) or 0,
                category.position,
            ),
        )

    async def ensure_categories(
        self,
        guild: discord.Guild,
        plan: LayoutPlan,
        *,
        allow_creation: bool = True,
    ) -> list[discord.CategoryChannel]:
        categories = self.find_embassy_categories(guild)

        if not allow_creation and len(categories) < len(plan.categories):
            raise RuntimeError(
                f"Embassy layout requires {len(plan.categories)} categories, but only "
                f"{len(categories)} existing Embassy categories were found."
            )

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
        *,
        allow_category_creation: bool = True,
    ) -> dict[str, int]:
        categories = await self.ensure_categories(
            guild,
            plan,
            allow_creation=allow_category_creation,
        )
        categories_by_number = {
            number: category
            for category in categories
            if (number := EmbassyLayoutPlanner.discord_category_number(category)) is not None
        }

        changed_categories = 0
        reordered_categories = 0
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

        # discord.py exposes channel ordering through each GuildChannel's
        # position/edit API; Guild has no edit_channel_positions method.
        # Move the Embassy categories one at a time into their final numeric
        # order, starting from the current top of the Embassy block.
        if categories:
            embassy_base_position = min(category.position for category in categories)
            for category_plan in plan.categories:
                category = categories_by_number.get(category_plan.index)
                if category is None:
                    continue
                desired_position = embassy_base_position + category_plan.index - 1
                if category.position != desired_position:
                    await category.edit(
                        position=desired_position,
                        reason="RAJDOOT embassy category ordering",
                    )
                    reordered_categories += 1

        desired_by_id = {entry.channel_id: entry for entry in plan.entries}

        # Rename first; renaming does not consume category capacity.
        for channel_id, entry in desired_by_id.items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            desired_name = self.embassy_slug(entry.country_name)
            if channel.name != desired_name:
                await channel.edit(
                    name=desired_name,
                    reason="RAJDOOT embassy canonical channel name",
                )
                renamed_channels += 1

        current_counts = {category.id: len(category.channels) for category in categories}
        desired_category_by_channel = {
            channel_id: categories_by_number[entry.category_index].id
            for channel_id, entry in desired_by_id.items()
        }

        pending_moves: dict[int, tuple[discord.TextChannel, int]] = {}
        for channel_id, target_category_id in desired_category_by_channel.items():
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            if channel.category_id != target_category_id:
                pending_moves[channel_id] = (channel, target_category_id)

        # Count unrelated channels already occupying Embassy categories and
        # compare them with the complete desired final state. We never evict
        # unrelated channels just to make the reconciliation fit.
        embassy_ids = set(desired_by_id)
        non_embassy_counts = {category.id: 0 for category in categories}
        for category in categories:
            for channel in category.channels:
                if channel.id not in embassy_ids:
                    non_embassy_counts[category.id] += 1

        desired_embassy_counts = {category.id: 0 for category in categories}
        for entry in plan.entries:
            target_id = categories_by_number[entry.category_index].id
            desired_embassy_counts[target_id] += 1

        for category in categories:
            desired_total = non_embassy_counts[category.id] + desired_embassy_counts[category.id]
            if desired_total > self.MAX_CHANNELS_PER_CATEGORY:
                raise RuntimeError(
                    f"Embassy layout cannot fit in {category.name}: final channel count "
                    f"would be {desired_total}, exceeding Discord's {self.MAX_CHANNELS_PER_CATEGORY}-channel category limit. "
                    "Move unrelated channels out of the Embassy category first."
                )

        # Discord rejects a move into a full category even if another embassy
        # channel is about to leave that category. Always perform an outbound
        # move first whenever possible, freeing capacity before filling it.
        while pending_moves:
            candidate: tuple[int, discord.TextChannel, int] | None = None
            for channel_id, (channel, target_category_id) in pending_moves.items():
                if current_counts.get(target_category_id, 0) < self.MAX_CHANNELS_PER_CATEGORY:
                    candidate = (channel_id, channel, target_category_id)
                    break

            if candidate is None:
                raise RuntimeError(
                    "Embassy channels cannot be safely redistributed because every required "
                    "destination category is currently full. No temporary category was used, "
                    "so no unrelated channels were displaced."
                )

            channel_id, channel, target_category_id = candidate
            source_category_id = channel.category_id
            target_category = guild.get_channel(target_category_id)
            if not isinstance(target_category, discord.CategoryChannel):
                raise RuntimeError(f"Missing target Embassy category {target_category_id}")

            await channel.edit(
                category=target_category,
                reason="RAJDOOT embassy category placement",
            )
            if source_category_id in current_counts:
                current_counts[source_category_id] -= 1
            current_counts[target_category_id] = current_counts.get(target_category_id, 0) + 1
            changed_channels += 1
            del pending_moves[channel_id]

        # Discord.py does not provide Guild.edit_channel_positions. Apply the
        # final order through GuildChannel.edit(position=...). Doing this in
        # ascending desired order makes each placement deterministic while
        # keeping all channels inside their already-final categories.
        for category_plan in plan.categories:
            category = categories_by_number[category_plan.index]
            for entry in category_plan.entries:
                channel = guild.get_channel(entry.channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                desired_position = category.position + 1 + entry.position
                if channel.position != desired_position:
                    await channel.edit(
                        position=desired_position,
                        reason="RAJDOOT embassy alphabetical layout",
                    )
                    changed_channels += 1

        return {
            "categories_changed": changed_categories,
            "categories_reordered": reordered_categories,
            "channels_moved": changed_channels,
            "channels_renamed": renamed_channels,
        }
