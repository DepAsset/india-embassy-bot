from __future__ import annotations

from dataclasses import dataclass

import discord

from rajdoot.discord_snapshot import DiscordGuildSnapshot
from rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner, LayoutPlan


SAFE_LAYOUT_KINDS = frozenset(
    {
        "category_rename",
        "category_reorder",
        "channel_rename",
        "channel_move",
        "channel_reorder",
    }
)


@dataclass(frozen=True, slots=True)
class ReconciliationAction:
    kind: str
    subject_id: int | str
    subject_name: str
    detail: str
    risk: str = "low"


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    layout: LayoutPlan
    actions: tuple[ReconciliationAction, ...]

    @property
    def category_actions(self) -> tuple[ReconciliationAction, ...]:
        return tuple(a for a in self.actions if a.kind.startswith("category_"))

    @property
    def channel_actions(self) -> tuple[ReconciliationAction, ...]:
        return tuple(a for a in self.actions if a.kind.startswith("channel_"))

    @property
    def archive_actions(self) -> tuple[ReconciliationAction, ...]:
        return ()

    @property
    def role_actions(self) -> tuple[ReconciliationAction, ...]:
        # Legacy embassy access roles remain outside reconciliation.
        return ()

    @property
    def unsupported_actions(self) -> tuple[ReconciliationAction, ...]:
        return tuple(a for a in self.actions if a.kind not in SAFE_LAYOUT_KINDS)


class EmbassyReconciliationEngine:
    """Build a safe, reviewed embassy layout plan without mutating Discord.

    The executable scope is now:
    - canonical category names;
    - Embassy category ordering;
    - canonical embassy channel names;
    - moving channels into their planned Embassy category;
    - alphabetical channel ordering inside each Embassy category.

    Creation, deletion, archiving, role changes, and membership changes remain
    outside the reconciliation gate.
    """

    def __init__(self) -> None:
        self._organizer = EmbassyDiscordOrganizer()

    def build(
        self,
        guild: discord.Guild,
        snapshot: DiscordGuildSnapshot,
        embassies: list[dict],
    ) -> ReconciliationReport:
        del guild
        layout = EmbassyLayoutPlanner.plan(embassies)
        actions: list[ReconciliationAction] = []

        categories_by_number: dict[int, object] = {}
        embassy_categories = []
        for category in snapshot.categories:
            number = EmbassyLayoutPlanner.category_number_from_name(category.name)
            if number is not None:
                if number in categories_by_number:
                    raise RuntimeError(
                        f"Duplicate Embassy category number {number} was found in the Discord snapshot."
                    )
                categories_by_number[number] = category
                embassy_categories.append(category)

        # Preserve the current location of the Embassy block, but make the
        # categories contiguous and numeric: Embassy 1, Embassy 2, ...
        embassy_base_position = min((category.position for category in embassy_categories), default=None)

        for category_plan in layout.categories:
            category = categories_by_number.get(category_plan.index)
            if category is None:
                # Missing categories are not created by reconciliation.
                continue

            if category.name != category_plan.name:
                actions.append(
                    ReconciliationAction(
                        kind="category_rename",
                        subject_id=category.id,
                        subject_name=category.name,
                        detail=f"Rename to {category_plan.name}.",
                    )
                )

            if embassy_base_position is not None:
                desired_position = embassy_base_position + category_plan.index - 1
                if category.position != desired_position:
                    actions.append(
                        ReconciliationAction(
                            kind="category_reorder",
                            subject_id=category.id,
                            subject_name=category.name,
                            detail=f"Place as Embassy category #{category_plan.index} in the Embassy block.",
                        )
                    )

        channels_by_id = {channel.id: channel for channel in snapshot.channels}
        for entry in layout.entries:
            channel = channels_by_id.get(entry.channel_id)
            if channel is None:
                continue

            target_category = categories_by_number.get(entry.category_index)
            desired_name = self._organizer.embassy_slug(entry.country_name)

            if channel.name != desired_name:
                actions.append(
                    ReconciliationAction(
                        kind="channel_rename",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail=f"Rename to {desired_name}.",
                    )
                )

            if target_category is None:
                # The missing category is already surfaced by the layout plan;
                # do not create a repair action that the executor could run.
                continue

            if channel.category_id != target_category.id:
                actions.append(
                    ReconciliationAction(
                        kind="channel_move",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail=f"Move into {target_category.name} at alphabetical slot {entry.position + 1}.",
                    )
                )
                continue

            # If it is already in the correct category, compare its current
            # position with the desired alphabetical slot. The exact global
            # Discord position is intentionally not exposed as an API contract;
            # the executor calculates it from the live category position.
            desired_position = target_category.position + 1 + entry.position
            if channel.position != desired_position:
                actions.append(
                    ReconciliationAction(
                        kind="channel_reorder",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail=f"Place in {target_category.name} at alphabetical slot {entry.position + 1}.",
                    )
                )

        return ReconciliationReport(layout=layout, actions=tuple(actions))
