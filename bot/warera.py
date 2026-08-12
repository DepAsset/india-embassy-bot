from dataclasses import dataclass
from typing import Any

import aiohttp

from .config import settings


@dataclass(slots=True)
class WarEraProfile:
    user_id: str
    username: str
    country: str | None = None
    country_code: str | None = None
    raw: dict[str, Any] | None = None


class WarEraClient:
    """Thin adapter around WarEra API.

    Endpoint details are isolated here so the embassy workflow does not depend on
    hard-coded API paths. Fill in the exact endpoint contract once WARERA_API_BASE
    and the API/client reference used by the server are provided.
    """

    def __init__(self) -> None:
        self.base = settings.warera_api_base.rstrip("/")
        self.headers = {}
        if settings.warera_api_token:
            self.headers["Authorization"] = f"Bearer {settings.warera_api_token}"

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base:
            raise RuntimeError("WARERA_API_BASE is not configured")
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(f"{self.base}/{path.lstrip('/')}", params=params, timeout=20) as response:
                response.raise_for_status()
                return await response.json()

    async def get_profile(self, user_id: str) -> WarEraProfile:
        # Exact endpoint intentionally left isolated until the supplied API client/base is confirmed.
        raise NotImplementedError("Configure the exact WarEra profile endpoint in bot/warera.py")

    async def verify_company_rename_otp(self, user_id: str, otp: str) -> bool:
        # Ownership verification mechanism: applicant temporarily renames their company using the OTP.
        raise NotImplementedError("Configure the WarEra company-rename verification endpoint in bot/warera.py")
