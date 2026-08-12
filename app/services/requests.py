from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import discord

from core.audit import AuditLogger
from core.database import Database
from core.state import RequestState


class EmbassyRequestService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.requests = database.collection("requests")
        self.audit = AuditLogger(database)

    async def create_private_request(self, *, channel: discord.TextChannel, applicant: discord.Member):
        existing = await self.requests.find_one({"discord_user_id": applicant.id, "active": True})
        if existing:
            thread = channel.guild.get_thread(existing["thread_id"]) or channel.guild.get_channel(existing["thread_id"])
            if isinstance(thread, discord.Thread):
                return existing["request_id"], thread, False
            await self.requests.update_one(
                {"request_id": existing["request_id"]},
                {"$set": {"active": False, "closed_at": datetime.now(timezone.utc)}},
            )

        request_id = str(uuid4())
        thread = await channel.create_thread(
            name=f"embassy-request-{applicant.display_name}"[:100],
            type=discord.ChannelType.private_thread,
            invitable=False,
            reason="Embassy access request",
        )
        await thread.add_user(applicant)
        await self.requests.insert_one({
            "request_id": request_id,
            "discord_user_id": applicant.id,
            "thread_id": thread.id,
            "active": True,
            "status": "PENDING_VERIFICATION",
            "state": RequestState.SUBMITTED.value,
            "created_at": datetime.now(timezone.utc),
        })
        await self.audit.write("REQUEST_CREATED", actor_id=applicant.id, request_id=request_id, thread_id=thread.id)
        return request_id, thread, True
