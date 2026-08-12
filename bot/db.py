from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings


class Database:
    def __init__(self) -> None:
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.db = self.client[settings.mongodb_database]
        self.requests = self.db.verification_requests
        self.embassies = self.db.embassies
        self.audit = self.db.audit_logs

    async def ensure_indexes(self) -> None:
        await self.requests.create_index("discord_user_id", unique=False)
        await self.requests.create_index("status")
        await self.requests.create_index("otp", unique=False)
        await self.embassies.create_index("country_code", unique=True)
        await self.audit.create_index("created_at")

    async def close(self) -> None:
        self.client.close()

    async def audit_event(self, action: str, actor_id: int | None, target_id: int | None = None, details: dict | None = None) -> None:
        await self.audit.insert_one({
            "action": action,
            "actor_id": actor_id,
            "target_id": target_id,
            "details": details or {},
            "created_at": datetime.now(timezone.utc),
        })
