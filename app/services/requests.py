from __future__ import annotations

from uuid import uuid4

import discord

from core.audit import AuditLogger
from core.database import Database
from core.repositories import RequestRepository


class EmbassyRequestService:
    """Creates and persists private Embassy request threads.

    This service deliberately owns persistence before any later verification
    step. The request ID is the durable correlation key for the entire flow.
    """

    def __init__(self, database: Database) -> None:
        self.requests = RequestRepository(database)
        self.audit = AuditLogger(database)

    async def create_private_request(
        self,
        *,
        channel: discord.TextChannel,
        applicant: discord.Member,
    ) -> tuple[str, discord.Thread]:
        request_id = str(uuid4())
        thread = await channel.create_thread(
            name=f"embassy-request-{applicant.id}",
            type=discord.ChannelType.private_thread,
            invitable=False,
            reason="Create Embassy System private application thread",
        )
        await thread.add_user(applicant)
        await self.requests.create(
            request_id=request_id,
            discord_user_id=applicant.id,
            thread_id=thread.id,
        )
        await self.audit.log(
            action="REQUEST_CREATED",
            actor_id=applicant.id,
            request_id=request_id,
            target_id=str(applicant.id),
            metadata={"thread_id": thread.id, "channel_id": channel.id},
        )
        return request_id, thread
