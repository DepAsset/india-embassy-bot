from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from access.service import AccessService
from core.database import Database


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
    """Single routing and decision layer for Embassy requests."""

    def __init__(self, database: Database, assignments: AccessService) -> None:
        self.requests = database.collection("requests")
        self.approvals = database.collection("approval_decisions")
        self.assignments = assignments

    async def resolve_route(self, context: RouteContext) -> ApprovalRoute:
        if context.has_preapproval:
            return ApprovalRoute.PREAPPROVED
        if context.is_special_official:
            return ApprovalRoute.SPECIAL_OFFICIAL
        embassy = await self.requests.find_one({"request_id": context.request_id}, {"embassy_country_key": 1})
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
        now = datetime.now(timezone.utc)
        result = await self.approvals.update_one(
            {"request_id": request_id, "decided_at": {"$exists": False}},
            {"$setOnInsert": {
                "request_id": request_id,
                "actor_id": actor_id,
                "decision": decision.value,
                "route": route.value,
                "reason": reason,
                "decided_at": now,
            }},
            upsert=True,
        )
        return bool(result.upserted_id)

    async def get_decision(self, request_id: str) -> dict[str, Any] | None:
        return await self.approvals.find_one({"request_id": request_id})
