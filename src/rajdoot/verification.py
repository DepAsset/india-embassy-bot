from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rajdoot.database import Database
from rajdoot.warera import WarEraClient


@dataclass(frozen=True, slots=True)
class IdentityVerification:
    verified: bool
    status: str
    message: str
    profile: dict[str, Any] | None = None


class WarEraVerificationService:
    def __init__(self, database: Database, warera: WarEraClient) -> None:
        self.database = database
        self.warera = warera

    async def verify(self, request_id: str, warera_user_id: str) -> IdentityVerification:
        await self.database.mark_request_verifying(request_id)
        try:
            profile = await self.warera.get_profile(warera_user_id)
        except Exception as exc:
            message = f"WarEra verification could not be completed: {type(exc).__name__}."
            await self.database.mark_request_verification_failed(request_id, message)
            await self.database.add_request_event(
                request_id=request_id,
                event_type="VERIFICATION_FAILED",
                details={"reason": message},
            )
            return IdentityVerification(False, "failed", message)

        if profile is None:
            message = "WarEra profile could not be verified."
            await self.database.mark_request_verification_failed(request_id, message)
            await self.database.add_request_event(
                request_id=request_id,
                event_type="VERIFICATION_FAILED",
                details={"reason": message},
            )
            return IdentityVerification(False, "failed", message)

        await self.database.mark_request_verified(
            request_id,
            warera_user_id=profile.user_id,
            profile_snapshot=profile.raw,
        )
        await self.database.add_request_event(
            request_id=request_id,
            event_type="VERIFICATION_PASSED",
            details={"warera_user_id": profile.user_id},
        )
        return IdentityVerification(True, "verified", "WarEra identity verified.", profile.raw)
