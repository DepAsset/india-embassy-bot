from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rajdoot.verification import WarEraVerificationService
from rajdoot.warera import WarEraProfile


@pytest.mark.asyncio
async def test_verification_persists_verified_profile() -> None:
    database = AsyncMock()
    warera = AsyncMock()
    warera.get_profile.return_value = WarEraProfile("42", {"id": "42", "name": "Test"})

    result = await WarEraVerificationService(database, warera).verify("request-id", "42")

    assert result.verified is True
    database.mark_request_verifying.assert_awaited_once_with("request-id")
    database.mark_request_verified.assert_awaited_once_with(
        "request-id",
        warera_user_id="42",
        profile_snapshot={"id": "42", "name": "Test"},
    )
    database.add_request_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_verification_does_not_fake_success() -> None:
    database = AsyncMock()
    warera = AsyncMock()
    warera.get_profile.return_value = None

    result = await WarEraVerificationService(database, warera).verify("request-id", "missing")

    assert result.verified is False
    database.mark_request_verification_failed.assert_awaited_once()
