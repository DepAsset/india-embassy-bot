from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.database import Database


class PreApprovalService:
    def __init__(self, database: Database) -> None:
        self.collection = database.collection("preapprovals")

    async def create(
        self,
        embassy_id: str,
        diplomat_id: int,
        applicant_warera_id: str,
        expires_at: datetime | None,
        reason: str | None = None,
    ) -> str:
        document: dict[str, Any] = {
            "embassy_id": embassy_id,
            "diplomat_id": diplomat_id,
            "applicant_warera_id": applicant_warera_id,
            "expires_at": expires_at,
            "reason": reason,
            "created_at": datetime.now(timezone.utc),
            "active": True,
        }
        result = await self.collection.insert_one(document)
        return str(result.inserted_id)

    async def find_valid(self, embassy_id: str, applicant_warera_id: str) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        return await self.collection.find_one({
            "embassy_id": embassy_id,
            "applicant_warera_id": applicant_warera_id,
            "active": True,
            "$or": [
                {"expires_at": None},
                {"expires_at": {"$gt": now}},
            ],
        })

    async def revoke(self, preapproval_id: str, revoked_by: int, reason: str) -> bool:
        result = await self.collection.update_one(
            {"_id": preapproval_id, "active": True},
            {"$set": {
                "active": False,
                "revoked_by": revoked_by,
                "revoked_at": datetime.now(timezone.utc),
                "revocation_reason": reason,
            }},
        )
        return result.modified_count == 1
