from datetime import datetime, timezone

from verification.otp import OTP_LENGTH, digest_otp, generate_otp, register_failure


def test_generate_otp_shape_and_alphabet() -> None:
    otp = generate_otp()
    assert len(otp) == OTP_LENGTH
    assert otp == otp.upper()
    assert all(char in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for char in otp)


def test_digest_normalizes_input() -> None:
    assert digest_otp(" abcd 2345 ") == digest_otp("ABCD2345")
    assert digest_otp("ABCD2345") != digest_otp("ABCD2346")


def test_register_failure_locks_on_fifth_attempt() -> None:
    attempts, locked, until = register_failure(4)
    assert attempts == 5
    assert locked is True
    assert isinstance(until, datetime)
    assert until.tzinfo == timezone.utc


def test_register_failure_does_not_lock_before_fifth() -> None:
    attempts, locked, until = register_failure(3)
    assert attempts == 4
    assert locked is False
    assert until is None
