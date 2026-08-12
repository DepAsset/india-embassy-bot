from datetime import datetime, timedelta, timezone

from verification.otp import MAX_ATTEMPTS, cooldown_until, digest_otp, generate_otp, register_failure


def test_otp_is_six_uppercase_alphanumeric_characters():
    otp = generate_otp()
    assert len(otp) == 6
    assert otp.isalnum()
    assert otp == otp.upper()


def test_otp_digest_is_deterministic():
    assert digest_otp("abc123") == digest_otp(" ABC123 ")


def test_fifth_failure_locks_for_ten_minutes():
    attempts, locked, lock_until = register_failure(MAX_ATTEMPTS - 1)
    assert attempts == MAX_ATTEMPTS
    assert locked is True
    assert lock_until is not None

    now = datetime.now(timezone.utc)
    delta = lock_until - now
    assert timedelta(minutes=9, seconds=55) <= delta <= timedelta(minutes=10, seconds=5)


def test_cooldown_uses_utc():
    now = datetime.now(timezone.utc)
    assert cooldown_until(now) > now
