from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from core.database import Database
from access.assignments import AssignmentService


class ApprovalRoute(StrEnum):
    PREAPPROVED = "PREAPPROVED"
    SPECIAL_OFFICIAL = "SPECIAL_OFFICIAL"
    FOREIGN_DIPLOMAT = "FOREIGN_DIPLOMAT"
    INDIAN_GOVERNMENT = "INDIAN_GOVERNMENT"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


@dataclass(frozen=True)
class RouteContext:
    request_id: str
    applicant_id: int
    embassy_id: str
    applicant_country_key: str
    is_special_official: bool = False
    has_preapproval: bool = False


class ApprovalEngine:
    """Single routing/decision layer for Embassy requests.

    It contains business decisions only. Discord UI and notifications remain
    adapters around this service so the rules cannot be bypassed by a command.
    """

    def __init__(self, database: Database, assignments: AssignmentService) -> None:
        self.requests = database.collection("embassy_requests")
        self.approvals = database.collection("approval_decisions")
        self.preapprovals = database.collection("preapprovals")
        self.assignments = assignments

    async def resolve_route(self, context: RouteContext) -> ApprovalRoute:
        if context.has_preapproval:
            return ApprovalRoute.PREAPPROVED
        if context.is_special_official:
            return ApprovalRoute.SPECIAL_OFFICIAL

        embassy = await self.requests.find_one(
            {"request_id": context.request_id}, {"embassy_country_key": 1}
        )
        embassy_country = (embassy or {}).get("embassy_country_key", "").lower()
        if embassy_country and embassy_country == context.applicant_country_key.lower():
            return ApprovalRoute.FOREIGN_DIPLOMAT
        return ApprovalRoute.INDIAN_GOVERNMENT

    async def record_decision(
        self,
        request_id: str,
        actor_id: int,
        decision: Decision,
        route: ApprovalRoute,
        reason: str | None = None,
    ) -> bool:
        """Atomically accept the first decision for a request.

        Returns False when another authorized actor already decided the request.
        This is the first-click-wins invariant used by diplomat approvals.
        """
        now = datetime.now(timezone.utc)
        result = await self.approvals.update_one(
            {"request_id": request_id, "decision": {"$exists": False}},
            {"$set": {
                "request_id": request_id,
                "actor_id": actor_id,
                "decision": decision.value,
                "route": route.value,
                "reason": reason,
                "decided_at": now,
            }},
            upsert=True,
        )
        return result.upserted_id is not None or result.modified_count == 1

    async def get_decision(self, request_id: str) -> dict[str, Any] | None:
        return await self.approvals.find_one({"request_id": request_id})
