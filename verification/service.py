from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.database import Database
from core.state import RequestState
from .otp import digest_otp, generate_otp, register_failure


class VerificationService:
    def __init__(self, database: Database) -> None:
        self.requests = database.collection("requests")
        self.attempts = database.collection("verification_attempts")

    async def issue_otp(self, request_id: str) -> str:
        otp = generate_otp()
        now = datetime.now(timezone.utc)
        await self.attempts.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "otp_hash": digest_otp(otp),
                    "attempts": 0,
                    "lock_until": None,
                    "state": "otp_pending",
                    "issued_at": now,
                    "updated_at": now,
                    "otp_session_id": str(uuid4()),
                }
            },
            upsert=True,
        )
        await self.requests.update_one(
            {"request_id": request_id},
            {"$set": {"state": RequestState.OTP_PENDING.value, "updated_at": now}},
        )
        return otp

    async def verify_otp(self, request_id: str, candidate: str) -> tuple[bool, int, datetime | None]:
        record = await self.attempts.find_one({"request_id": request_id})
        if not record:
            raise ValueError("No OTP session exists for this request")

        lock_until = record.get("lock_until")
        if lock_until and lock_until > datetime.now(timezone.utc):
            return False, int(record.get("attempts", 0)), lock_until

        if digest_otp(candidate) == record.get("otp_hash"):
            now = datetime.now(timezone.utc)
            await self.attempts.update_one(
                {"request_id": request_id},
                {"$set": {"state": "verified", "verified_at": now, "updated_at": now}},
            )
            await self.requests.update_one(
                {"request_id": request_id},
                {"$set": {"state": RequestState.VERIFIED.value, "updated_at": now}},
            )
            return True, int(record.get("attempts", 0)), None

        attempts, locked, new_lock = register_failure(int(record.get("attempts", 0)))
        now = datetime.now(timezone.utc)
        await self.attempts.update_one(
            {"request_id": request_id},
            {
                "$set": {
                    "attempts": attempts,
                    "lock_until": new_lock,
                    "state": "locked" if locked else "otp_pending",
                    "updated_at": now,
                }
            },
        )
        if locked:
            await self.requests.update_one(
                {"request_id": request_id},
                {"$set": {"state": RequestState.OTP_LOCKED.value, "updated_at": now}},
            )
        return False, attempts, new_lock
