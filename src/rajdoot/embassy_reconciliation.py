from __future__ import annotations

from dataclasses import dataclass

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
        return tuple(a for a in self.actions if a.kind.startswith("role_"))


class EmbassyReconciliationEngine:
    """Build a Discord change plan without performing Discord mutations."""

    def __init__(self) -> None:
        self._organizer = EmbassyDiscordOrganizer()

    def build(
        self,
        guild: discord.Guild,
        snapshot: DiscordGuildSnapshot,
        embassies: list[dict],
        legacy_roles: list[dict] | None = None,
    ) -> ReconciliationReport:
        layout = EmbassyLayoutPlanner.plan(embassies)
        actions: list[ReconciliationAction] = []

        categories_by_number = {
            number: category
            for category in snapshot.categories
            if (number := EmbassyLayoutPlanner.discord_category_number(_category(category)))
            is not None
        }

        for category_plan in layout.categories:
            category = categories_by_number.get(category_plan.index)
            if category is None:
                actions.append(
                    ReconciliationAction(
                        kind="category_create",
                        subject_id=category_plan.index,
                        subject_name=category_plan.name,
                        detail="Create by cloning the last existing Embassy category permissions.",
                        risk="medium",
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
            target_category = categories_by_number.get(entry.category_index)
            desired_name = self._organizer.embassy_slug(entry.country_name)

            if channel is None:
                actions.append(
                    ReconciliationAction(
                        kind="channel_missing",
                        subject_id=entry.channel_id,
                        subject_name=entry.country_name,
                        detail="Expected embassy channel was not found in the Discord snapshot.",
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

            if target_category is not None and channel.category_id != target_category.id:
                actions.append(
                    ReconciliationAction(
                        kind="channel_move",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail=f"Move to {target_category.name}.",
                    )
                )

            desired_position = target_category.position + 1 + entry.position if target_category else None
            if desired_position is not None and channel.position != desired_position:
                actions.append(
                    ReconciliationAction(
                        kind="channel_reorder",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail=f"Move from position {channel.position} to desired layout position.",
                    )
                )

        active_ids = {entry.channel_id for entry in layout.entries}
        archived_ids = {
            int(e["channel_id"])
            for e in embassies
            if e.get("status") == "archived" and e.get("channel_id")
        }
        embassy_category_ids = {category.id for category in categories_by_number.values()}
        for channel in snapshot.channels:
            if channel.category_id not in embassy_category_ids:
                continue
            if channel.id in active_ids:
                continue
            if channel.id in archived_ids:
                actions.append(
                    ReconciliationAction(
                        kind="archive_channel",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail="Move to the Embassy Graveyard during the controlled archive step.",
                        risk="medium",
                    )
                )
            else:
                actions.append(
                    ReconciliationAction(
                        kind="archive_unmatched_channel",
                        subject_id=channel.id,
                        subject_name=channel.name,
                        detail="Unmatched channel found inside an Embassy category. Review before moving to Embassy Graveyard.",
                        risk="high",
                    )
                )

        if legacy_roles:
            role_by_id = {role.id: role for role in snapshot.roles}
            for row in legacy_roles:
                role = role_by_id.get(int(row["role_id"]))
                if role is None:
                    actions.append(
                        ReconciliationAction(
                            kind="role_missing",
                            subject_id=int(row["role_id"]),
                            subject_name=str(row["role_name"]),
                            detail="Role recorded in Supabase was not found in the Discord snapshot.",
                            risk="medium",
                        )
                    )
                    continue
                if row["disposition"] == "orphan_pending_deletion":
                    actions.append(
                        ReconciliationAction(
                            kind="role_delete_candidate",
                            subject_id=role.id,
                            subject_name=role.name,
                            detail=f"Delete only after membership review. Current members: {role.member_count}.",
                            risk="high" if role.member_count else "medium",
                        )
                    )
                elif role.name != row["role_name"]:
                    actions.append(
                        ReconciliationAction(
                            kind="role_rename_candidate",
                            subject_id=role.id,
                            subject_name=role.name,
                            detail=f"Canonical legacy-role name is {row['role_name']}.",
                        )
                    )

        return ReconciliationReport(layout=layout, actions=tuple(actions))


def _category(snapshot_category: object) -> discord.CategoryChannel:
    """Adapter used so the layout parser can stay independent of snapshot types."""
    # A lightweight proxy is enough because discord_category_number only reads .name.
    category = discord.CategoryChannel.__new__(discord.CategoryChannel)
    category.name = getattr(snapshot_category, "name")
    return category
