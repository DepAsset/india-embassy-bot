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
        request = await self.requests.find_one({"request_id": request_id})
        if not request:
            raise ValueError("Embassy request not found")
        if request.get("state") in {RequestState.VERIFIED.value, RequestState.APPROVED.value, RequestState.DECLINED.value, RequestState.CLOSED.value}:
            raise ValueError("This Embassy request is no longer awaiting verification")

        profile = await self.warera.get_profile(supplied)
        now = datetime.now(timezone.utc)
        safe_username = str(profile.username).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        profile_display = f"[{safe_username}]({profile.profile_url})"
        await self.requests.update_one(
            {"request_id": request_id},
            {"$set": {
                "state": RequestState.PROFILE_RESOLVED.value,
                "warera_user_id": profile.user_id,
                "warera_username": profile.username,
                "warera_profile_url": profile_display,
                "warera_profile_raw_url": profile.profile_url,
                "verified_country_id": profile.country_id,
                "verified_country_name": profile.country_name,
                "official_flags": {
                    "president": profile.is_president,
                    "vice_president": profile.is_vice_president,
                    "eam_or_mofa": profile.is_eam_or_mofa,
                },
                "updated_at": now,
            }}
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
            {"$set": {"request_id": request_id, "otp_hash": digest_otp(otp), "attempts": 0, "lock_until": None, "issued_at": now, "updated_at": now, "state": "otp_pending"}, "$inc": {"issuance_count": 1}},
            upsert=True,
        )
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.OTP_PENDING.value, "updated_at": now}})
        await self.audit.log(action="OTP_ISSUED", actor_id=actor_id, request_id=request_id, warera_id=str(request["warera_user_id"]))
        return otp

    async def _failure(self, request: dict, record: dict, request_id: str, actor_id: int, now: datetime, action: str) -> tuple[bool, int, datetime | None]:
        attempts, locked, new_lock = register_failure(int(record.get("attempts", 0)))
        lockouts = int(record.get("lockouts", 0)) + (1 if locked else 0)
        recovery = locked and lockouts >= 2
        state = "recovery_pending" if recovery else ("locked" if locked else "otp_pending")
        await self.otp.update_one({"request_id": request_id}, {"$set": {"attempts": attempts, "lock_until": new_lock, "lockouts": lockouts, "state": state, "updated_at": now}})
        if recovery:
            await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.RECOVERY_PENDING.value, "active": True, "updated_at": now}})
        elif locked:
            await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.OTP_LOCKED.value, "updated_at": now}})
        await self.audit.log(action=action, actor_id=actor_id, request_id=request_id, warera_id=str(request.get("warera_user_id") or ""), metadata={"attempts": attempts, "lockouts": lockouts, "manual_review": recovery})
        return False, attempts, new_lock

    async def _prepare_verification(self, request_id: str) -> tuple[dict, dict, datetime]:
        request = await self.requests.find_one({"request_id": request_id})
        record = await self.otp.find_one({"request_id": request_id})
        if not request or not record:
            raise ValueError("No active OTP verification exists")
        now = datetime.now(timezone.utc)
        lock_until = record.get("lock_until")
        if lock_until and lock_until > now:
            raise ValueError(f"Verification is locked until {lock_until.isoformat()}")
        if lock_until and lock_until <= now and int(record.get("attempts", 0)) >= 5:
            await self.otp.update_one({"request_id": request_id}, {"$set": {"attempts": 0, "lock_until": None, "state": "otp_pending", "updated_at": now}})
            record["attempts"] = 0
        return request, record, now

    async def _complete_company_verification(self, request: dict, record: dict, request_id: str, actor_id: int, now: datetime) -> tuple[bool, int, datetime | None]:
        company_names = await self.warera.get_company_names(str(request["warera_user_id"]))
        otp_hash = record.get("otp_hash")
        matched = any(digest_otp(re.sub(r"\s+", "", name.strip().upper())) == otp_hash for name in company_names)
        if not matched:
            return await self._failure(request, record, request_id, actor_id, now, "OTP_COMPANY_CHECK_FAILED")

        await self.otp.update_one({"request_id": request_id}, {"$set": {"state": "verified", "verified_at": now, "updated_at": now}})
        await self.requests.update_one({"request_id": request_id}, {"$set": {"state": RequestState.VERIFIED.value, "updated_at": now, "verification_completed_at": now, "active": True}})
        await self.audit.log(action="OTP_VERIFIED", actor_id=actor_id, request_id=request_id, warera_id=str(request["warera_user_id"]), new_state=RequestState.VERIFIED.value)
        return True, int(record.get("attempts", 0)), None

    async def verify_company_otp(self, request_id: str, candidate: str, actor_id: int) -> tuple[bool, int, datetime | None]:
        request, record, now = await self._prepare_verification(request_id)
        supplied = re.sub(r"\s+", "", candidate.strip().upper())
        if digest_otp(supplied) != record.get("otp_hash"):
            return await self._failure(request, record, request_id, actor_id, now, "OTP_FAILED")
        return await self._complete_company_verification(request, record, request_id, actor_id, now)

    async def verify_company_ownership(self, request_id: str, actor_id: int) -> tuple[bool, int, datetime | None]:
        """Verify the stored OTP directly against the applicant's owned companies.

        The applicant never submits the OTP back to Discord. The bot retrieves
        the stored OTP hash and compares it against the names of the applicant's
        currently owned companies returned by the WarEra API.
        """
        request, record, now = await self._prepare_verification(request_id)
        return await self._complete_company_verification(request, record, request_id, actor_id, now)
