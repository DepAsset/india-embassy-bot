from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class Database:
    """Small MongoDB lifecycle wrapper.

    The bot stores durable application state here because the Render filesystem
    must never be treated as persistent storage.
    """

    def __init__(self, uri: str, database_name: str) -> None:
        self.uri = uri
        self.database_name = database_name
        self.client: AsyncIOMotorClient | None = None
        self.db: AsyncIOMotorDatabase[Any] | None = None

    async def connect(self) -> None:
        if self.client is not None:
            return
        self.client = AsyncIOMotorClient(self.uri, serverSelectionTimeoutMS=5000)
        await self.client.admin.command("ping")
        self.db = self.client[self.database_name]
        await self.ensure_indexes()
        logger.info("Connected to MongoDB database %s", self.database_name)

    async def ensure_indexes(self) -> None:
        if self.db is None:
            raise RuntimeError("Database is not connected")

        await self.db.embassies.create_index("channel_id", unique=True)
        await self.db.embassies.create_index("canonical_name", unique=True, partialFilterExpression={"status": "active"})
        await self.db.embassies.create_index([("status", 1), ("canonical_name", 1)])

        await self.db.embassy_assignments.create_index(
            [("discord_user_id", 1), ("embassy_id", 1)],
            unique=True,
            partialFilterExpression={"status": "active"},
        )
        await self.db.embassy_assignments.create_index([("discord_user_id", 1), ("status", 1)])
        await self.db.embassy_assignments.create_index([("embassy_id", 1), ("status", 1)])

        await self.db.requests.create_index("request_id", unique=True)
        await self.db.requests.create_index([("discord_user_id", 1), ("state", 1)])
        await self.db.requests.create_index([("requested_embassy_id", 1), ("state", 1)])

        await self.db.preapprovals.create_index([("target_warera_id", 1), ("embassy_id", 1), ("status", 1)])
        await self.db.preapprovals.create_index("expires_at")
        await self.db.audit_logs.create_index([("timestamp", -1)])
        await self.db.audit_logs.create_index([("request_id", 1), ("timestamp", -1)])
        await self.db.migration_snapshots.create_index("snapshot_id", unique=True)
        await self.db.organization_jobs.create_index([("state", 1), ("created_at", -1)])
        await self.db.dashboard_state.create_index("dashboard_key", unique=True)

    def collection(self, name: str):
        if self.db is None:
            raise RuntimeError("Database is not connected")
        return self.db[name]

    async def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.db = None
            logger.info("MongoDB connection closed")
