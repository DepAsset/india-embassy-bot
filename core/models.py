from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .state import AssignmentStatus, AssignmentType, EmbassyStatus, RequestState


@dataclass(slots=True, frozen=True)
class Embassy:
    id: str
    country_id: str
    canonical_name: str
    channel_id: int
    category_id: int
    status: EmbassyStatus = EmbassyStatus.ACTIVE


@dataclass(slots=True, frozen=True)
class EmbassyAssignment:
    id: str
    discord_user_id: int
    embassy_id: str
    assignment_type: AssignmentType
    status: AssignmentStatus = AssignmentStatus.ACTIVE
    assigned_by: int | None = None
    assigned_at: datetime | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


@dataclass(slots=True, frozen=True)
class EmbassyRequest:
    request_id: str
    discord_user_id: int
    thread_id: int
    state: RequestState
    warera_user_id: str | None = None
    verified_country_id: str | None = None
    requested_embassy_id: str | None = None
    actor_id: int | None = None
    decision_reason: str | None = None
