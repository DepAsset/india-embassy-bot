from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.database import Database


@dataclass(frozen=True)
class Embassy:
    embassy_id: str
    country_key: str
    country_name: str
    channel_id: int
    access_role_id: int | None = None
    category_id: int | None = None
    active: bool = True
    archived_at: datetime | None = None

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "Embassy":
        return cls(
            embassy_id=str(document["embassy_id"]),
            country_key=document["country_key"],
            country_name=document["country_name"],
            channel_id=int(document["channel_id"]),
            access_role_id=(int(document["access_role_id"]) if document.get("access_role_id") else None),
            category_id=(int(document["category_id"]) if document.get("category_id") else None),
            active=document.get("active", True),
            archived_at=document.get("archived_at"),
        )


class EmbassyRegistry:
    """Canonical registry for Embassy channels.

    Discord channel/role state is synchronized from this registry. The registry
    also supports archived embassies without deleting their historical records.
    """

    def __init__(self, database: Database) -> None:
        self.collection = database.collection("embassies")

    async def get_by_id(self, embassy_id: str) -> Embassy | None:
        document = await self.collection.find_one({"embassy_id": embassy_id})
        return Embassy.from_document(document) if document else None

    async def get_by_country(self, country_key: str) -> Embassy | None:
        document = await self.collection.find_one({"country_key": country_key.lower().strip()})
        return Embassy.from_document(document) if document else None

    async def get_active(self) -> list[Embassy]:
        cursor = self.collection.find({"active": True}).sort("country_key", 1)
        return [Embassy.from_document(item) async for item in cursor]

    async def search(self, query: str, limit: int = 25) -> list[Embassy]:
        query = query.strip()
        if not query:
            return await self.get_active()
        regex = {"$regex": query, "$options": "i"}
        cursor = self.collection.find(
            {"active": True, "$or": [{"country_name": regex}, {"country_key": regex}]}
        ).sort("country_key", 1).limit(limit)
        return [Embassy.from_document(item) async for item in cursor]

    async def upsert(self, embassy: Embassy) -> None:
        await self.collection.update_one(
            {"embassy_id": embassy.embassy_id},
            {
                "$set": {
                    "country_key": embassy.country_key.lower().strip(),
                    "country_name": embassy.country_name,
                    "channel_id": embassy.channel_id,
                    "access_role_id": embassy.access_role_id,
                    "category_id": embassy.category_id,
                    "active": embassy.active,
                    "archived_at": embassy.archived_at,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    async def archive(self, embassy_id: str) -> bool:
        result = await self.collection.update_one(
            {"embassy_id": embassy_id, "active": True},
            {"$set": {"active": False, "archived_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count == 1

    async def restore(self, embassy_id: str) -> bool:
        result = await self.collection.update_one(
            {"embassy_id": embassy_id, "active": False},
            {"$set": {"active": True, "archived_at": None, "updated_at": datetime.now(timezone.utc)}},
        )
        return result.modified_count == 1
