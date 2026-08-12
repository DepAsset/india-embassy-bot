from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from core.database import Database


@dataclass(frozen=True)
class RoleMembershipSnapshot:
    role_id: int
    role_name: str
    member_ids: tuple[int, ...]


@dataclass(frozen=True)
class MigrationSnapshot:
    snapshot_id: str
    created_by: int
    created_at: datetime
    role_memberships: tuple[RoleMembershipSnapshot, ...]
    embassy_mappings: tuple[dict[str, Any], ...]
    status: str = "READY"


class MigrationSnapshotService:
    """Immutable migration snapshots used to make legacy-role migration reversible."""

    def __init__(self, database: Database) -> None:
        self.collection = database.collection("migration_snapshots")

    async def create_snapshot(
        self,
        created_by: int,
        role_memberships: list[RoleMembershipSnapshot],
        embassy_mappings: list[dict[str, Any]],
    ) -> MigrationSnapshot:
        snapshot = MigrationSnapshot(
            snapshot_id=str(uuid4()),
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
            role_memberships=tuple(role_memberships),
            embassy_mappings=tuple(embassy_mappings),
        )
        await self.collection.insert_one({
            "snapshot_id": snapshot.snapshot_id,
            "created_by": snapshot.created_by,
            "created_at": snapshot.created_at,
            "status": snapshot.status,
            "role_memberships": [
                {
                    "role_id": item.role_id,
                    "role_name": item.role_name,
                    "member_ids": list(item.member_ids),
                }
                for item in snapshot.role_memberships
            ],
            "embassy_mappings": list(snapshot.embassy_mappings),
        })
        return snapshot

    async def get(self, snapshot_id: str) -> dict[str, Any] | None:
        return await self.collection.find_one({"snapshot_id": snapshot_id})

    async def mark_rollback_started(self, snapshot_id: str) -> bool:
        result = await self.collection.update_one(
            {"snapshot_id": snapshot_id, "status": "READY"},
            {"$set": {"status": "ROLLBACK_STARTED", "rollback_started_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count == 1

    async def mark_rolled_back(self, snapshot_id: str, summary: dict[str, Any]) -> bool:
        result = await self.collection.update_one(
            {"snapshot_id": snapshot_id},
            {"$set": {
                "status": "ROLLED_BACK",
                "rolled_back_at": datetime.now(timezone.utc),
                "rollback_summary": summary,
            }},
        )
        return result.modified_count == 1
