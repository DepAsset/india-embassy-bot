from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.database import Database


class AuditLogger:
    def __init__(self, database: Database) -> None:
        self.collection = database.collection("audit_logs")

    async def write(self, action: str, *, actor_id: int | None = None, request_id: str | None = None, **data: Any) -> None:
        await self.collection.insert_one({
            "action": action,
            "actor_id": actor_id,
            "request_id": request_id,
            "data": data,
            "created_at": datetime.now(timezone.utc),
        })
