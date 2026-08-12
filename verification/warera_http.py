from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .warera import WarEraProfile


class WarEraAPIError(RuntimeError):
    pass


class WarEraHTTPClient:
    """Small isolated HTTP client for the public WarEra API.

    The endpoint path is configurable because the API is versioned. The client
    accepts both a numeric user id and a WarEra profile URL and normalizes the
    response into the domain model used by the Embassy flow.
    """

    def __init__(self, base_url: str, profile_path: str = "/trpc/user.getUserLite", timeout: float = 12.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.profile_path = profile_path
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    @staticmethod
    def normalize_user_input(value: str) -> str:
        value = value.strip()
        if value.isdigit():
            return value
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            match = re.search(r"(?:profile|user)/([A-Za-z0-9_-]+)", parsed.path, re.I)
            if match:
                return match.group(1)
        match = re.search(r"(?:profile|user)[/:]([A-Za-z0-9_-]+)", value, re.I)
        if match:
            return match.group(1)
        return value

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(f"{self.base_url}{path}", params=params) as response:
                text = await response.text()
                if response.status >= 400:
                    raise WarEraAPIError(f"WarEra API returned HTTP {response.status}: {text[:300]}")
                try:
                    return await response.json(content_type=None)
                except Exception as exc:
                    raise WarEraAPIError("WarEra API returned non-JSON data") from exc

    @staticmethod
    def _unwrap(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            if isinstance(payload.get("result"), dict):
                result = payload["result"]
                if isinstance(result.get("data"), dict):
                    return result["data"]
                return result
            if isinstance(payload.get("data"), dict):
                return payload["data"]
            return payload
        raise WarEraAPIError("Unexpected WarEra API response shape")

    async def get_profile(self, profile_or_id: str) -> WarEraProfile:
        user_id = self.normalize_user_input(profile_or_id)
        payload = await self._get(self.profile_path, {"input": user_id})
        data = self._unwrap(payload)

        # Support the common field names used by API revisions without making
        # the rest of the bot depend on the transport representation.
        country = data.get("country") or data.get("nation") or {}
        government = data.get("government") or {}
        country_id = str(data.get("countryId") or data.get("country_id") or country.get("id") or "")
        country_name = str(data.get("countryName") or data.get("country_name") or country.get("name") or "Unknown")
        uid = str(data.get("id") or data.get("userId") or data.get("user_id") or user_id)
        roles = {str(x).lower() for x in (data.get("roles") or []) if isinstance(x, (str, int))}
        title = str(data.get("title") or data.get("role") or "").lower()
        gov_role = str(government.get("role") or government.get("title") or "").lower()

        return WarEraProfile(
            user_id=uid,
            profile_url=str(data.get("profileUrl") or data.get("profile_url") or f"https://warera.io/profile/{uid}"),
            country_id=country_id,
            country_name=country_name,
            is_president=bool(data.get("isPresident") or "president" in roles or "president" in title or "president" in gov_role),
            is_vice_president=bool(data.get("isVicePresident") or "vice president" in roles or "vice_president" in roles or "vice president" in title),
            is_eam_or_mofa=bool(data.get("isEamOrMofa") or data.get("isForeignMinister") or "eam" in roles or "foreign minister" in roles or "mofa" in roles),
        )

    async def get_company_names(self, user_id: str) -> list[str]:
        payload = await self._get(self.profile_path, {"input": user_id})
        data = self._unwrap(payload)
        companies = data.get("companies") or data.get("company") or []
        if isinstance(companies, dict):
            companies = [companies]
        names: list[str] = []
        for company in companies:
            if isinstance(company, str):
                names.append(company)
            elif isinstance(company, dict):
                name = company.get("name") or company.get("companyName")
                if name:
                    names.append(str(name))
        return names
