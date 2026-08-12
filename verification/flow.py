from __future__ import annotations

from datetime import datetime, timezone
import re

from core.audit import AuditLogger
from core.database import Database
from core.state import RequestState
from .otp import digest_otp, generate_otp, register_failure
from .warera import WarEraClient, WarEraProfile


class VerificationFlow:
    """Durable WarEra identity and company-rename verification state machine."""

    def __init__(self, database: Database, warera: WarEraClient) -> None:
        self.db = database
        self.warera = warera
        self.requests = database.collection("requests")
        self.otp = database.collection("verification_attempts")
        self.audit = AuditLogger(database)

    async def resolve_profile(self, request_id: str, supplied: str, actor_id: int) -> WarEraProfile:
        profile = await self.warera.get_profile(supplied)
        now = datetime.now(timezone.utc)
        await self.requests.update_one(
            {"request_id": request_id, "state": RequestState.SUBMITTED.value},
            {"$set": {
                "state": RequestState.PROFILE_RESOLVED.value,
                "warera_user_id": profile.user_id,
                "warera_profile_url": profile.profile_url,
                "verified_country_id": profile.country_id,
                "verified_country_name": profile.country_name,
                "official_flags": {
                    "president": profile.is_president,
                    "vice_president": profile.is_vice_president,
                    "eam_or_mofa": profile.is_eam_or_mofa,
                },
                "updated_at": now,
            }},
        )
        await self.audit.log(action="PROFILE_RESOLVED", actor_id=actor_id, request_id=request_id, warera_id=profile.user_id, new_state=RequestState.PROFILE_RESOLVED.value)
        return profile

    async def issue_company_otp(self, request_id: str, actor_id: int) -> str:
        request = await self.requests.find_one({"request_id": request_id})
        if not request or not request.get("warera_user_id"):
            raise ValueError("Resolve the WarEra profile before issuing OTP")
        otp = generate_otp()
        now = datetime.now(timezone.utc)
        await self.otp.update_one(
            {"request_id": request_id},
            {"$set": {
                "request_id": request_id,
                "otp_hash": digest_otp(otp),
                "attempts": 0,
                "lock_until": None,
                "issued_at": now,
                "updated_at": now,
                "state": "otp_pending",
            }},
            upsert=True,
        )
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.OTP_PENDING.value, "updated_at": now}})
        await self.audit.log(action="OTP_ISSUED", actor_id=actor_id, request_id=request_id, warera_id=str(request["warera_user_id"]))
        return otp

    async def verify_company_otp(self, request_id: str, candidate: str, actor_id: int) -> tuple[bool, int, datetime | None]:
        request = await self.requests.find_one({"request_id": request_id})
        record = await self.otp.find_one({"request_id": request_id})
        if not request or not record:
            raise ValueError("No active OTP verification exists")
        now = datetime.now(timezone.utc)
        lock_until = record.get("lock_until")
        if lock_until and lock_until > now:
            return False, int(record.get("attempts", 0)), lock_until

        supplied = re.sub(r"\s+", "", candidate.strip().upper())
        if digest_otp(supplied) != record.get("otp_hash"):
            attempts, locked, new_lock = register_failure(int(record.get("attempts", 0)))
            await self.otp.update_one({"request_id": request_id}, {"$set": {"attempts": attempts, "lock_until": new_lock, "state": "locked" if locked else "otp_pending", "updated_at": now}})
            if locked:
                await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.OTP_LOCKED.value, "updated_at": now}})
            await self.audit.log(action="OTP_FAILED", actor_id=actor_id, request_id=request_id, warera_id=str(request["warera_user_id"]), metadata={"attempts": attempts, "locked": locked})
            return False, attempts, new_lock

        company_names = await self.warera.get_company_names(str(request["warera_user_id"]))
        normalized_companies = {re.sub(r"\s+", "", name.strip().upper()) for name in company_names}
        if supplied not in normalized_companies:
            attempts, locked, new_lock = register_failure(int(record.get("attempts", 0)))
            await self.otp.update_one({"request_id": request_id}, {"$set": {"attempts": attempts, "lock_until": new_lock, "state": "locked" if locked else "otp_pending", "updated_at": now}})
            if locked:
                await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.OTP_LOCKED.value, "updated_at": now}})
            await self.audit.log(action="OTP_COMPANY_CHECK_FAILED", actor_id=actor_id, request_id=request_id, warera_id=str(request["warera_user_id"]), metadata={"attempts": attempts, "locked": locked})
            return False, attempts, new_lock

        await self.otp.update_one({"request_id": request_id}, {"$set": {"state": "verified", "verified_at": now, "updated_at": now}})
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.VERIFIED.value, "updated_at": now, "verification_completed_at": now}})
        await self.audit.log(action="OTP_VERIFIED", actor_id=actor_id, request_id=request_id, warera_id=str(request["warera_user_id"]), new_state=RequestState.VERIFIED.value)
        return True, int(record.get("attempts", 0)), None
