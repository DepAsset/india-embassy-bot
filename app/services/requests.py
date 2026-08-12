from __future__ import annotations

from uuid import uuid4

import discord

from core.audit import AuditLogger
from core.database import Database
from core.repositories import RequestRepository
from core.state import RequestState


ACTIVE_REQUEST_STATES = {
    RequestState.SUBMITTED.value,
    RequestState.PROFILE_RESOLVED.value,
    RequestState.OTP_PENDING.value,
    RequestState.OTP_LOCKED.value,
    RequestState.VERIFIED.value,
    RequestState.EMBASSY_SELECTION.value,
    RequestState.DIPLOMAT_REVIEW.value,
    RequestState.GOVERNMENT_REVIEW.value,
    RequestState.PREAPPROVED.value,
    RequestState.AUTO_APPROVED.value,
    RequestState.RECOVERY_PENDING.value,
}


class EmbassyRequestService:
    """Creates and persists private Embassy request threads.

    This service deliberately owns persistence before any later verification
    step. The request ID is the durable correlation key for the entire flow.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self.requests = RequestRepository(database)
        self.audit = AuditLogger(database)

    async def find_active_for_user(self, discord_user_id: int) -> dict | None:
        return await self.database.collection("requests").find_one(
            {"discord_user_id": discord_user_id, "state": {"$in": list(ACTIVE_REQUEST_STATES)}},
            sort=[("created_at", -1)],
        )

    async def create_private_request(
        self,
        *,
        channel: discord.TextChannel,
        applicant: discord.Member,
    ) -> tuple[str, discord.Thread, bool]:
        existing = await self.find_active_for_user(applicant.id)
        if existing:
            thread = channel.guild.get_thread(existing["thread_id"])
            if thread is not None:
                return str(existing["request_id"]), thread, False
            await self.audit.log(
                action="REQUEST_THREAD_MISSING",
                actor_id=applicant.id,
                request_id=str(existing["request_id"]),
                target_id=str(applicant.id),
                metadata={"old_thread_id": existing["thread_id"]},
            )

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
        return request_id, thread, True
