from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from access.models import AccessResult, AccessSource, AssignmentType
from core.database import Database


@dataclass(frozen=True)
class AssignmentResult:
    assignment_id: str | None
    created: bool
    already_active: bool


@dataclass(frozen=True)
class RevokeResult:
    revoked: bool
    assignment_id: str | None


class AccessService:
    """Persistent source-of-truth for Embassy assignments.

    Discord roles are deliberately not used to decide whether access exists.
    A unique active (user, embassy, assignment_type) record prevents duplicate
    assignments and allows a user to hold unlimited embassy assignments.
    """

    def __init__(self, database: Database) -> None:
        self.collection = database.collection("embassy_assignments")

    async def assign(
        self,
        discord_user_id: int,
        embassy_id: str,
        assignment_type: AssignmentType,
        source: AccessSource,
        *,
        assigned_by: int | None = None,
    ) -> AssignmentResult:
        now = datetime.now(timezone.utc)
        assignment_id = str(uuid4())
        document = {
            "assignment_id": assignment_id,
            "discord_user_id": discord_user_id,
            "embassy_id": embassy_id,
            "assignment_type": assignment_type.value,
            "source": source.value,
            "active": True,
            "created_at": now,
            "assigned_by": assigned_by,
        }
        # The partial unique index is the final duplicate guard. This method
        # treats a duplicate-key race as an existing assignment.
        try:
            await self.collection.insert_one(document)
            return AssignmentResult(assignment_id, True, False)
        except Exception as exc:
            if exc.__class__.__name__ != "DuplicateKeyError":
                raise
            existing = await self.collection.find_one({
                "discord_user_id": discord_user_id,
                "embassy_id": embassy_id,
                "assignment_type": assignment_type.value,
                "active": True,
            })
            return AssignmentResult(existing.get("assignment_id") if existing else None, False, True)

    async def revoke(
        self,
        discord_user_id: int,
        embassy_id: str,
        *,
        revoked_by: int,
        reason: str,
        assignment_type: AssignmentType | None = None,
    ) -> RevokeResult:
        query = {
            "discord_user_id": discord_user_id,
            "embassy_id": embassy_id,
            "active": True,
        }
        if assignment_type is not None:
            query["assignment_type"] = assignment_type.value
        document = await self.collection.find_one_and_update(
            query,
            {"$set": {
                "active": False,
                "revoked_at": datetime.now(timezone.utc),
                "revoked_by": revoked_by,
                "revoke_reason": reason,
            }},
            return_document=True,
        )
        return RevokeResult(bool(document), document.get("assignment_id") if document else None)

    async def active_for_user(self, discord_user_id: int) -> list[dict]:
        cursor = self.collection.find({"discord_user_id": discord_user_id, "active": True}).sort("embassy_id", 1)
        return [item async for item in cursor]

    async def active_for_embassy(self, embassy_id: str) -> list[dict]:
        cursor = self.collection.find({"embassy_id": embassy_id, "active": True}).sort("discord_user_id", 1)
        return [item async for item in cursor]

    async def has_access(self, discord_user_id: int, embassy_id: str) -> bool:
        return await self.collection.find_one({
            "discord_user_id": discord_user_id,
            "embassy_id": embassy_id,
            "active": True,
        }) is not None
