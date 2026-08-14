from __future__ import annotations

from dataclasses import dataclass
import re

import discord

from rajdoot.discord_snapshot import DiscordGuildSnapshot
from rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner, LayoutPlan


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
        return tuple(a for a in self.actions if a.kind.startswith("archive_"))

    @property
    def role_actions(self) -> tuple[ReconciliationAction, ...]:
        # Legacy embassy access roles are intentionally outside reconciliation.
        # They are left untouched and may be removed manually by the server owner.
        return ()


class EmbassyReconciliationEngine:
    """Build a Discord change plan without performing Discord mutations.

    The current migration scope is deliberately rename-only:
    - rename the two existing Embassy categories;
    - rename the 90 existing embassy channels.

    Category creation, channel creation/moves/reordering, archive operations,
    and role operations are outside this execution gate and therefore must not
    appear as executable actions in the reviewed plan.
    """

    def __init__(self) -> None:
        self._organizer = EmbassyDiscordOrganizer()

    def build(
        self,
        guild: discord.Guild,
        snapshot: DiscordGuildSnapshot,
        embassies: list[dict],
    ) -> ReconciliationReport:
        del guild  # The snapshot is the only Discord state used during planning.
        layout = EmbassyLayoutPlanner.plan(embassies)
        actions: list[ReconciliationAction] = []

        categories_by_number = {}
        for category in snapshot.categories:
            match = re.fullmatch(r"Embassy\s+(\d+)(?:\s+\([A-Z]-[A-Z]\))?", category.name)
            if match:
                categories_by_number[int(match.group(1))] = category

        for category_plan in layout.categories:
            category = categories_by_number.get(category_plan.index)
            if category is None:
                # A missing category cannot safely be handled by a rename-only
                # migration. Surface it as a blocked/high-risk item rather than
                # silently creating Discord structure.
                actions.append(
                    ReconciliationAction(
                        kind="category_create",
                        subject_id=category_plan.index,
                        subject_name=category_plan.name,
                        detail="Required Embassy category is missing. Rename-only execution cannot create it.",
                        risk="high",
                    )
                )
            elif category.name != category_plan.name:
                actions.append(
                    ReconciliationAction(
                        kind="category_rename",
                        subject_id=category.id,
                        subject_name=category.name,
                        detail=f"Rename to {category_plan.name}.",
                    )
                )

        channels_by_id = {channel.id: channel for channel in snapshot.channels}
        for entry in layout.entries:
            channel = channels_by_id.get(entry.channel_id)
            desired_name = self._organizer.embassy_slug(entry.country_name)

            if channel is None:
                actions.append(
                    ReconciliationAction(
                        kind="channel_missing",
                        subject_id=entry.channel_id,
                        subject_name=entry.country_name,
                        detail="Expected embassy channel was not found in the Discord snapshot. Rename-only execution cannot create or repair it.",
                        risk="high",
                    )
                )
                continue

            if channel.name != desired_name:
                actions.append(
                    ReconciliationAction(
                        kind="channel_rename",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail=f"Rename to {desired_name}.",
                    )
                )

        # Deliberately do not plan category moves, channel moves, channel
        # reordering, archive operations, or role operations in this migration.
        # The user will handle legacy role deletion manually after migration.

        return ReconciliationReport(layout=layout, actions=tuple(actions))
