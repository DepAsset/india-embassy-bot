from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from embassy.registry import Embassy


class InventoryStatus(str, Enum):
    MATCHED = "matched"
    MISSING_CHANNEL = "missing_channel"
    MISSING_ROLE = "missing_role"
    DUPLICATE_COUNTRY = "duplicate_country"
    UNKNOWN_CHANNEL = "unknown_channel"
    NAME_MISMATCH = "name_mismatch"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class LegacyEmbassyRecord:
    country_key: str
    country_name: str
    channel_id: int
    access_role_id: int | None
    current_channel_name: str | None = None
    expected_channel_name: str | None = None


@dataclass(frozen=True)
class InventoryIssue:
    status: InventoryStatus
    country_key: str
    channel_id: int | None = None
    role_id: int | None = None
    detail: str = ""


@dataclass
class InventoryReport:
    matched: list[LegacyEmbassyRecord] = field(default_factory=list)
    issues: list[InventoryIssue] = field(default_factory=list)

    @property
    def safe_to_import(self) -> bool:
        blocking = {
            InventoryStatus.MISSING_CHANNEL,
            InventoryStatus.MISSING_ROLE,
            InventoryStatus.DUPLICATE_COUNTRY,
            InventoryStatus.UNKNOWN_CHANNEL,
        }
        return not any(issue.status in blocking for issue in self.issues)

    def summary(self) -> dict[str, int | bool]:
        return {
            "matched": len(self.matched),
            "issues": len(self.issues),
            "safe_to_import": self.safe_to_import,
        }


class EmbassyInventoryValidator:
    """Validate legacy Embassy mappings before any Discord mutation.

    This is deliberately a dry-run layer. It never creates, moves, renames,
    assigns, or removes Discord roles/channels.
    """

    def __init__(self, *, live_channel_ids: Iterable[int], live_role_ids: Iterable[int]) -> None:
        self.live_channel_ids = set(live_channel_ids)
        self.live_role_ids = set(live_role_ids)

    def validate(self, records: Iterable[LegacyEmbassyRecord]) -> InventoryReport:
        report = InventoryReport()
        seen_countries: set[str] = set()
        seen_channels: set[int] = set()

        for record in records:
            key = record.country_key.casefold().strip()
            if key in seen_countries:
                report.issues.append(
                    InventoryIssue(
                        InventoryStatus.DUPLICATE_COUNTRY,
                        key,
                        record.channel_id,
                        record.access_role_id,
                        "More than one legacy record maps to the same country.",
                    )
                )
                continue
            seen_countries.add(key)

            if record.channel_id in seen_channels:
                report.issues.append(
                    InventoryIssue(
                        InventoryStatus.UNKNOWN_CHANNEL,
                        key,
                        record.channel_id,
                        record.access_role_id,
                        "The same channel ID appears in multiple records.",
                    )
                )
                continue
            seen_channels.add(record.channel_id)

            if record.channel_id not in self.live_channel_ids:
                report.issues.append(
                    InventoryIssue(
                        InventoryStatus.MISSING_CHANNEL,
                        key,
                        record.channel_id,
                        record.access_role_id,
                        "Configured channel ID was not found in the live Discord inventory.",
                    )
                )
                continue

            if record.access_role_id is not None and record.access_role_id not in self.live_role_ids:
                report.issues.append(
                    InventoryIssue(
                        InventoryStatus.MISSING_ROLE,
                        key,
                        record.channel_id,
                        record.access_role_id,
                        "Configured legacy access role was not found in the live Discord inventory.",
                    )
                )
                continue

            if (
                record.current_channel_name is not None
                and record.expected_channel_name is not None
                and record.current_channel_name != record.expected_channel_name
            ):
                report.issues.append(
                    InventoryIssue(
                        InventoryStatus.NAME_MISMATCH,
                        key,
                        record.channel_id,
                        record.access_role_id,
                        f"Current name is {record.current_channel_name!r}; expected {record.expected_channel_name!r}.",
                    )
                )

            report.matched.append(record)

        return report

    @staticmethod
    def to_embassies(records: Iterable[LegacyEmbassyRecord]) -> list[Embassy]:
        return [
            Embassy(
                embassy_id=f"legacy:{record.channel_id}",
                country_key=record.country_key.casefold().strip(),
                country_name=record.country_name,
                channel_id=record.channel_id,
                access_role_id=record.access_role_id,
                active=True,
            )
            for record in records
        ]
