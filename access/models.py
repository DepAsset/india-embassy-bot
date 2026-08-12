from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AssignmentType(StrEnum):
    FOREIGN_DIPLOMAT = "FOREIGN_DIPLOMAT"
    AMBASSADOR = "AMBASSADOR"
    VISITOR = "VISITOR"


class AccessSource(StrEnum):
    DIPLOMAT_APPROVAL = "DIPLOMAT_APPROVAL"
    PRE_APPROVAL = "PRE_APPROVAL"
    SPECIAL_OFFICIAL = "SPECIAL_OFFICIAL"
    GOVERNMENT_OVERRIDE = "GOVERNMENT_OVERRIDE"
    AUTOMATIC_FIRST_DIPLOMAT = "AUTOMATIC_FIRST_DIPLOMAT"
    AMBASSADOR_ASSIGNMENT = "AMBASSADOR_ASSIGNMENT"
    RESTORED = "RESTORED"
    MIGRATION = "MIGRATION"


@dataclass(frozen=True)
class EmbassyAssignment:
    assignment_id: str
    discord_user_id: int
    embassy_id: str
    assignment_type: AssignmentType
    source: AccessSource
    active: bool
    created_at: datetime
    revoked_at: datetime | None = None
    revoked_by: int | None = None
    revoke_reason: str | None = None


@dataclass(frozen=True)
class AccessResult:
    granted: bool
    already_active: bool = False
    assignment_id: str | None = None
    reason: str | None = None
