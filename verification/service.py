from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core.database import Database
from core.state import RequestState
from .otp import digest_otp, generate_otp, register_failure
from .warera import WarEraClient


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

    async def verify_company_ownership(
        self,
        request_id: str,
        user_id: str,
        client: WarEraClient,
    ) -> tuple[bool, int, datetime | None, list[str]]:
        """Verify the stored OTP by checking the applicant's live companies.

        The applicant never submits the OTP to Discord. They rename one of
        their owned WarEra companies to the OTP, then press one button. This
        method fetches all current company names and compares them locally.
        """
        record = await self.attempts.find_one({"request_id": request_id})
        if not record:
            raise ValueError("No OTP session exists for this request")

        lock_until = record.get("lock_until")
        now = datetime.now(timezone.utc)
        if lock_until and lock_until > now:
            return False, int(record.get("attempts", 0)), lock_until, []

        names = await client.get_company_names(user_id)
        normalized_names = {name.strip().upper() for name in names}
        expected_hash = record.get("otp_hash")

        # We cannot recover the OTP from its hash, so compare each company name
        # against the stored digest. This keeps the raw OTP out of MongoDB.
        matched = any(digest_otp(name) == expected_hash for name in normalized_names)
        if matched:
            await self.attempts.update_one(
                {"request_id": request_id},
                {
                    "$set": {
                        "state": "verified",
                        "verified_at": now,
                        "updated_at": now,
                    }
                },
            )
            await self.requests.update_one(
                {"request_id": request_id},
                {
                    "$set": {
                        "state": RequestState.VERIFIED.value,
                        "warera_user_id": user_id,
                        "updated_at": now,
                    }
                },
            )
            return True, int(record.get("attempts", 0)), None, names

        attempts, locked, new_lock = register_failure(int(record.get("attempts", 0)))
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
        return False, attempts, new_lock, names
