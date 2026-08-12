from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .database import Database
from .state import RequestState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequestRepository:
    def __init__(self, database: Database) -> None:
        self.collection = database.collection("requests")

    async def create(
        self,
        *,
        request_id: str,
        discord_user_id: int,
        thread_id: int,
    ) -> None:
        now = utcnow()
        await self.collection.insert_one(
            {
                "request_id": request_id,
                "discord_user_id": discord_user_id,
                "thread_id": thread_id,
                "state": RequestState.SUBMITTED.value,
                "created_at": now,
                "updated_at": now,
            }
        )

    async def get(self, request_id: str) -> dict[str, Any] | None:
        return await self.collection.find_one({"request_id": request_id})

    async def transition(
        self,
        request_id: str,
        expected_state: RequestState,
        new_state: RequestState,
        *,
        actor_id: int | None = None,
        reason: str | None = None,
    ) -> bool:
        """Atomically transition a request.

        This is the foundation for first-click-wins approval handling. The
        second concurrent actor cannot change a request that another actor has
        already resolved.
        """
        update: dict[str, Any] = {
            "$set": {
                "state": new_state.value,
                "updated_at": utcnow(),
            }
        }
        if actor_id is not None:
            update["$set"]["actor_id"] = actor_id
        if reason is not None:
            update["$set"]["decision_reason"] = reason

        result = await self.collection.update_one(
            {
                "request_id": request_id,
                "state": expected_state.value,
            },
            update,
        )
        return result.modified_count == 1
