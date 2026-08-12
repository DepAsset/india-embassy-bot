from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


class Database:
    def __init__(self, uri: str, name: str) -> None:
        self.client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        self.db: AsyncIOMotorDatabase = self.client[name]

    def collection(self, name: str):
        return self.db[name]

    async def initialize(self) -> None:
        await self.db.command("ping")

        await self.collection("embassies").create_index("embassy_id", unique=True)
        await self.collection("embassies").create_index("country_key", unique=True)
        await self.collection("embassies").create_index([("active", 1), ("country_name", 1)])
        await self.collection("requests").create_index("request_id", unique=True)
        await self.collection("requests").create_index(
            [("discord_user_id", 1)],
            name="active_request_user",
            unique=True,
            partialFilterExpression={"active": True},
        )
        await self.collection("requests").create_index([("state", 1), ("created_at", -1)])
        await self.collection("requests").create_index([("requested_embassy_id", 1), ("state", 1)])
        await self.collection("embassy_assignments").create_index(
            [("discord_user_id", 1), ("embassy_id", 1), ("assignment_type", 1)],
            name="active_assignment_unique",
            unique=True,
            partialFilterExpression={"active": True},
        )
        await self.collection("embassy_assignments").create_index([("discord_user_id", 1), ("active", 1)])
        await self.collection("embassy_assignments").create_index([("embassy_id", 1), ("active", 1)])
        await self.collection("approval_decisions").create_index("request_id", unique=True)
        await self.collection("preapprovals").create_index([("embassy_id", 1), ("applicant_warera_id", 1), ("active", 1)])
        await self.collection("preapprovals").create_index("expires_at")
        await self.collection("verification_attempts").create_index("request_id", unique=True)
        await self.collection("audit_logs").create_index([("created_at", -1)])
        await self.collection("audit_logs").create_index([("request_id", 1), ("created_at", -1)])
        await self.collection("migration_snapshots").create_index("snapshot_id", unique=True)

    async def close(self) -> None:
        self.client.close()
