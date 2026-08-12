from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import aiohttp


@dataclass(slots=True, frozen=True)
class WarEraProfile:
    user_id: str
    profile_url: str
    country_id: str
    country_name: str
    is_president: bool = False
    is_vice_president: bool = False
    is_eam_or_mofa: bool = False


class WarEraClient(Protocol):
    async def get_profile(self, profile_or_id: str) -> WarEraProfile:
        """Resolve a profile URL/ID to canonical WarEra identity data."""

    async def get_company_names(self, user_id: str) -> list[str]:
        """Return current company names for OTP verification."""


class WarEraApiError(RuntimeError):
    """Raised when the WarEra API cannot complete a request."""


class WarEraHttpClient:
    """Small async adapter for the public WarEra tRPC API."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        base = base_url.rstrip("/")
        self.base_url = base if base.endswith("/trpc") else f"{base}/trpc"
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: aiohttp.ClientSession | None = None

    async def _session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self.session

    @staticmethod
    def extract_user_id(profile_or_id: str) -> str:
        value = profile_or_id.strip()
        match = re.search(r"/user/([A-Za-z0-9_-]+)", value)
        if match:
            return match.group(1)
        if re.fullmatch(r"[A-Za-z0-9_-]+", value):
            return value
        raise ValueError("Invalid WarEra profile URL or user ID")

    async def _get(self, procedure: str, payload: dict) -> dict:
        session = await self._session()
        input_value = quote(json.dumps({"json": payload}, separators=(",", ":")))
        url = f"{self.base_url}/{procedure}?input={input_value}"
        async with session.get(url) as response:
            body = await response.text()
            if response.status >= 400:
                raise WarEraApiError(f"WarEra API returned HTTP {response.status}: {body[:300]}")
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise WarEraApiError("WarEra API returned invalid JSON") from exc

    @staticmethod
    def _unwrap(data: dict) -> dict:
        value = data
        if isinstance(value.get("result"), dict):
            value = value["result"]
        if isinstance(value.get("data"), dict):
            value = value["data"]
        if isinstance(value.get("json"), dict):
            value = value["json"]
        return value

    async def get_profile(self, profile_or_id: str) -> WarEraProfile:
        user_id = self.extract_user_id(profile_or_id)
        raw = self._unwrap(await self._get("user.getUserLite", {"userId": user_id}))
        user = raw.get("user", raw)
        canonical_id = str(user.get("id") or user_id)
        return WarEraProfile(
            user_id=canonical_id,
            profile_url=f"https://app.warera.io/user/{canonical_id}",
            country_id=str(user.get("countryId") or user.get("country_id") or ""),
            country_name=str(user.get("countryName") or user.get("country_name") or "Unknown"),
            is_president=bool(user.get("isPresident", False)),
            is_vice_president=bool(user.get("isVicePresident", False)),
            is_eam_or_mofa=bool(user.get("isEamOrMofa", False)),
        )

    async def get_company_names(self, user_id: str) -> list[str]:
        raw = self._unwrap(await self._get("company.getCompanies", {"userId": user_id, "perPage": 100}))
        companies = raw.get("companies", [])
        if not isinstance(companies, list):
            return []
        return [
            str(company.get("name"))
            for company in companies
            if isinstance(company, dict) and company.get("name") is not None
        ]

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.session = None
