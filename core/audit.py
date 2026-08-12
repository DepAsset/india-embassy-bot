from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .database import Database


class AuditLogger:
    def __init__(self, database: Database) -> None:
        self.collection = database.collection("audit_logs")

    async def log(
        self,
        *,
        action: str,
        actor_id: int | None = None,
        request_id: str | None = None,
        target_id: str | None = None,
        warera_id: str | None = None,
        embassy_id: str | None = None,
        old_state: str | None = None,
        new_state: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.collection.insert_one(
            {
                "action": action,
                "actor_id": actor_id,
                "request_id": request_id,
                "target_id": target_id,
                "warera_id": warera_id,
                "embassy_id": embassy_id,
                "old_state": old_state,
                "new_state": new_state,
                "reason": reason,
                "metadata": metadata or {},
                "timestamp": datetime.now(timezone.utc),
            }
        )
