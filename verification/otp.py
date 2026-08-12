from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone


OTP_LENGTH = 8
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 10


def generate_otp(length: int = OTP_LENGTH) -> str:
    """Generate a cryptographically secure, uppercase alphanumeric OTP."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def digest_otp(value: str) -> str:
    """Return a deterministic SHA-256 digest for safe database storage."""
    normalized = "".join(value.strip().upper().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def register_failure(attempts: int) -> tuple[int, bool, datetime | None]:
    """Record an OTP failure and apply the five-attempt cooldown policy."""
    new_attempts = max(0, attempts) + 1
    if new_attempts >= MAX_ATTEMPTS:
        return new_attempts, True, datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
    return new_attempts, False, None
