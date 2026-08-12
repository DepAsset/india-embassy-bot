from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from hashlib import sha256

MAX_ATTEMPTS = 5
COOLDOWN_MINUTES = 10
OTP_ALPHABET = string.ascii_uppercase + string.digits


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_otp(length: int = 6) -> str:
    return "".join(secrets.choice(OTP_ALPHABET) for _ in range(length))


def digest_otp(otp: str) -> str:
    return sha256(otp.strip().upper().encode("utf-8")).hexdigest()


def cooldown_until(now: datetime | None = None) -> datetime:
    return (now or utcnow()) + timedelta(minutes=COOLDOWN_MINUTES)


def is_locked(lock_until: datetime | None) -> bool:
    return lock_until is not None and lock_until > utcnow()


def register_failure(attempts: int) -> tuple[int, bool, datetime | None]:
    next_attempts = attempts + 1
    if next_attempts >= MAX_ATTEMPTS:
        return next_attempts, True, cooldown_until()
    return next_attempts, False, None
