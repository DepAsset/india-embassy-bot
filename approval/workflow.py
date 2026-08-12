from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import uuid4

from core.audit import AuditLogger
from core.database import Database
from core.state import RequestState


class Route(StrEnum):
    PREAPPROVED = "PREAPPROVED"
    SPECIAL_OFFICIAL = "SPECIAL_OFFICIAL"
    FOREIGN_DIPLOMAT = "FOREIGN_DIPLOMAT"
    INDIAN_GOVERNMENT = "INDIAN_GOVERNMENT"
    # Compatibility alias used by the Discord routing layer.
    GOVERNMENT_REVIEW = "INDIAN_GOVERNMENT"


class Decision(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class ApprovalWorkflow:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.requests = database.collection("requests")
        self.decisions = database.collection("approval_decisions")
        self.preapprovals = database.collection("preapprovals")
        self.audit = AuditLogger(database)

    async def create_preapproval(self, *, embassy_id: str, diplomat_id: int, applicant_warera_id: str, expires_at: datetime | None, reason: str | None) -> str:
        now = datetime.now(timezone.utc)
        preapproval_id = str(uuid4())
        await self.preapprovals.insert_one({"preapproval_id": preapproval_id, "embassy_id": embassy_id, "diplomat_id": diplomat_id, "applicant_warera_id": applicant_warera_id, "expires_at": expires_at, "reason": reason, "created_at": now, "active": True})
        await self.audit.log(action="PREAPPROVAL_CREATED", actor_id=diplomat_id, embassy_id=embassy_id, warera_id=applicant_warera_id, metadata={"preapproval_id": preapproval_id, "expires_at": expires_at.isoformat() if expires_at else None})
        return preapproval_id

    async def find_preapproval(self, embassy_id: str, applicant_warera_id: str) -> dict | None:
        now = datetime.now(timezone.utc)
        result = await self.preapprovals.find_one({"embassy_id": embassy_id, "applicant_warera_id": applicant_warera_id, "active": True, "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}, sort=[("created_at", -1)])
        if result is None:
            await self.preapprovals.update_many({"embassy_id": embassy_id, "applicant_warera_id": applicant_warera_id, "active": True, "expires_at": {"$lte": now}}, {"$set": {"active": False, "expired_at": now}})
        return result

    async def consume_preapproval(self, preapproval_id: str) -> bool:
        result = await self.preapprovals.update_one({"preapproval_id": preapproval_id, "active": True}, {"$set": {"active": False, "used_at": datetime.now(timezone.utc)}})
        return result.modified_count == 1

    async def revoke_preapproval(self, preapproval_id: str, actor_id: int, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("A reason is required")
        result = await self.preapprovals.update_one({"preapproval_id": preapproval_id, "active": True}, {"$set": {"active": False, "revoked_by": actor_id, "revoked_at": datetime.now(timezone.utc), "revocation_reason": reason.strip()}})
        return result.modified_count == 1

    async def route(self, request_id: str, *, embassy_country_id: str) -> Route:
        request = await self.requests.find_one({"request_id": request_id})
        if not request:
            raise ValueError("Request not found")
        warera_id = str(request.get("warera_user_id") or "")
        embassy_id = str(request.get("requested_embassy_id") or "")
        preapproval = await self.find_preapproval(embassy_id, warera_id)
        if preapproval:
            return Route.PREAPPROVED
        flags = request.get("official_flags") or {}
        if flags.get("president") or flags.get("vice_president") or flags.get("eam_or_mofa"):
            return Route.SPECIAL_OFFICIAL
        applicant_id = str(request.get("verified_country_id") or "").strip().lower()
        applicant_name = str(request.get("verified_country_name") or "").strip().lower()
        embassy_key = str(embassy_country_id).strip().lower()
        if applicant_id == embassy_key or applicant_name == embassy_key:
            return Route.FOREIGN_DIPLOMAT
        return Route.INDIAN_GOVERNMENT

    async def decide(self, request_id: str, actor_id: int, decision: Decision, route: Route, reason: str | None = None) -> bool:
        now = datetime.now(timezone.utc)
        try:
            await self.decisions.insert_one({"request_id": request_id, "actor_id": actor_id, "decision": decision.value, "route": route.value, "reason": reason, "decided_at": now})
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                return False
            raise
        new_state = RequestState.APPROVED.value if decision is Decision.APPROVED else RequestState.DECLINED.value
        current = await self.requests.find_one({"request_id": request_id})
        if not current or current.get("state") not in {RequestState.DIPLOMAT_REVIEW.value, RequestState.GOVERNMENT_REVIEW.value, RequestState.PREAPPROVED.value, RequestState.AUTO_APPROVED.value}:
            return False
        await self.requests.update_one({"request_id": request_id, "state": current["state"]}, {"$set": {"state": new_state, "decision": decision.value, "decision_actor_id": actor_id, "decision_reason": reason, "updated_at": now, "active": False}})
        await self.audit.log(action=f"REQUEST_{decision.value}", actor_id=actor_id, request_id=request_id, embassy_id=str(current.get("requested_embassy_id") or ""), warera_id=str(current.get("warera_user_id") or ""), old_state=current.get("state"), new_state=new_state, reason=reason, metadata={"route": route.value})
        return True

    async def auto_approve_preapproved(self, request_id: str, actor_id: int = 0) -> bool:
        request = await self.requests.find_one({"request_id": request_id})
        if not request:
            return False
        preapproval = await self.find_preapproval(str(request.get("requested_embassy_id") or ""), str(request.get("warera_user_id") or ""))
        if not preapproval or not await self.consume_preapproval(str(preapproval["preapproval_id"])):
            return False
        now = datetime.now(timezone.utc)
        try:
            await self.decisions.insert_one({"request_id": request_id, "actor_id": actor_id, "decision": Decision.APPROVED.value, "route": Route.PREAPPROVED.value, "reason": "Valid diplomat pre-approval", "decided_at": now})
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                return False
            raise
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.APPROVED.value, "decision": Decision.APPROVED.value, "decision_reason": "Valid diplomat pre-approval", "updated_at": now, "active": False}})
        await self.audit.log(action="REQUEST_AUTO_APPROVED", actor_id=actor_id, request_id=request_id, embassy_id=str(request.get("requested_embassy_id") or ""), warera_id=str(request.get("warera_user_id") or ""), new_state=RequestState.APPROVED.value)
        return True

    @staticmethod
    def default_preapproval_expiry(hours: int = 72) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=hours)
