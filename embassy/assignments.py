from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.database import Database
from core.state import AssignmentStatus, AssignmentType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AssignmentService:
    """Owns durable embassy membership state.

    Discord roles/permissions are a projection of this state, not the source
    of truth. One user may hold unlimited active embassy assignments.
    """

    def __init__(self, database: Database) -> None:
        self.collection = database.collection("embassy_assignments")

    async def get_active(self, discord_user_id: int) -> list[dict]:
        cursor = self.collection.find(
            {"discord_user_id": discord_user_id, "status": AssignmentStatus.ACTIVE.value}
        )
        return await cursor.to_list(length=None)

    async def has_active(self, discord_user_id: int, embassy_id: str) -> bool:
        return await self.collection.find_one(
            {
                "discord_user_id": discord_user_id,
                "embassy_id": embassy_id,
                "status": AssignmentStatus.ACTIVE.value,
            },
            {"_id": 1},
        ) is not None

    async def grant(
        self,
        *,
        discord_user_id: int,
        embassy_id: str,
        assignment_type: AssignmentType,
        assigned_by: int | None = None,
        source: str = "system",
    ) -> tuple[str, bool]:
        existing = await self.collection.find_one(
            {
                "discord_user_id": discord_user_id,
                "embassy_id": embassy_id,
                "status": AssignmentStatus.ACTIVE.value,
            }
        )
        if existing:
            return str(existing["assignment_id"]), False

        assignment_id = str(uuid4())
        await self.collection.insert_one(
            {
                "assignment_id": assignment_id,
                "discord_user_id": discord_user_id,
                "embassy_id": embassy_id,
                "assignment_type": assignment_type.value,
                "status": AssignmentStatus.ACTIVE.value,
                "assigned_by": assigned_by,
                "assigned_at": utcnow(),
                "source": source,
            }
        )
        return assignment_id, True

    async def revoke(
        self,
        *,
        discord_user_id: int,
        embassy_id: str,
        actor_id: int,
        reason: str,
    ) -> bool:
        if not reason.strip():
            raise ValueError("A revocation reason is required")
        result = await self.collection.update_one(
            {
                "discord_user_id": discord_user_id,
                "embassy_id": embassy_id,
                "status": AssignmentStatus.ACTIVE.value,
            },
            {
                "$set": {
                    "status": AssignmentStatus.REVOKED.value,
                    "revoked_at": utcnow(),
                    "revoked_by": actor_id,
                    "revoke_reason": reason.strip(),
                }
            },
        )
        return result.modified_count == 1
