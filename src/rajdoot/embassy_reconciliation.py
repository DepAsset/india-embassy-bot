from __future__ import annotations

from dataclasses import dataclass
import re

import discord

from rajdoot.discord_snapshot import DiscordGuildSnapshot
from rajdoot.embassy_layout import EmbassyDiscordOrganizer, EmbassyLayoutPlanner, LayoutPlan


SAFE_RENAME_KINDS = frozenset({"category_rename", "channel_rename"})


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
        return tuple(a for a in self.actions if a.kind == "category_rename")

    @property
    def channel_actions(self) -> tuple[ReconciliationAction, ...]:
        return tuple(a for a in self.actions if a.kind == "channel_rename")

    @property
    def archive_actions(self) -> tuple[ReconciliationAction, ...]:
        return ()

    @property
    def role_actions(self) -> tuple[ReconciliationAction, ...]:
        # Legacy embassy access roles are intentionally outside reconciliation.
        # They are left untouched and may be removed manually by the server owner.
        return ()

    @property
    def unsupported_actions(self) -> tuple[ReconciliationAction, ...]:
        """Return actions that must never enter the executable plan.

        The reviewed/executable plan is intentionally a strict subset of the
        reconciliation domain: only category_rename and channel_rename are
        executable. This makes the review screen and execution gate use the
        same canonical action set instead of generating an action and then
        rejecting that same action at confirmation time.
        """
        return tuple(a for a in self.actions if a.kind not in SAFE_RENAME_KINDS)


class EmbassyReconciliationEngine:
    """Build a Discord change plan without performing Discord mutations.

    The current migration scope is deliberately rename-only:
    - rename the two existing Embassy categories;
    - rename the existing embassy channels.

    Category creation, channel creation/moves/reordering, archive operations,
    and role operations are outside this execution gate and therefore are not
    executable actions in the reviewed plan.
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
                # Missing structure is intentionally NOT turned into an
                # executable action. Rename-only execution must never create
                # Discord structure. It will therefore not poison confirmation
                # with a category_create action.
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

        channels_by_id = {channel.id: channel for channel in snapshot.channels}
        for entry in layout.entries:
            channel = channels_by_id.get(entry.channel_id)
            desired_name = self._organizer.embassy_slug(entry.country_name)

            if channel is None:
                # Missing structure is intentionally NOT turned into an
                # executable action. Creating/repairing channels is outside the
                # reviewed rename-only migration scope.
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

        # IMPORTANT: actions returned above are the canonical executable plan.
        # Deliberately do not add category creation, channel creation/moves,
        # reordering, archive operations, or role operations. The confirmation
        # gate must never see an action it is expected to reject.
        return ReconciliationReport(layout=layout, actions=tuple(actions))
