from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

import httpx

from rajdoot.config import Settings


@dataclass(frozen=True, slots=True)
class WarEraProfile:
    user_id: str
    raw: dict[str, Any]


class WarEraClient:
    """Purpose-built WarEra client with bounded timeouts and connection reuse."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.warera_api_base_url.rstrip("/")
        self.profile_path = settings.warera_api_profile_path
        self.full_profile_path = settings.warera_api_full_profile_path
        self.companies_path = settings.warera_api_companies_path
        self.company_path = settings.warera_api_company_path
        self.country_path = settings.warera_api_country_path
        self.token = settings.warera_api_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token and not self.token.startswith("<PUT_"):
            headers["X-API-Key"] = self.token
        return headers

    async def _post(self, client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> Any:
        response = await client.post(f"{self.base_url}{path}", json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict) and "data" in result:
                return result["data"]
            if isinstance(payload.get("user"), dict):
                return payload["user"]
            if isinstance(payload.get("data"), dict):
                return payload["data"]
        return payload

    async def get_profile(self, user_id: str) -> WarEraProfile | None:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                payload = await self._post(client, self.profile_path, {"userId": str(user_id)})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
        profile = self._unwrap(payload)
        return WarEraProfile(str(user_id), profile) if isinstance(profile, dict) else None

    async def get_full_profile(self, user_id: str) -> WarEraProfile | None:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                payload = await self._post(client, self.full_profile_path, {"userId": str(user_id)})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
            profile = self._unwrap(payload)
            if not isinstance(profile, dict):
                return None

            country_value = profile.get("country")
            country_id = None
            if isinstance(country_value, dict):
                country_id = country_value.get("_id") or country_value.get("id") or country_value.get("countryId")
            elif isinstance(country_value, str):
                country_id = country_value
            if not country_id:
                country_id = profile.get("countryId") or profile.get("citizenshipId")
                infos = profile.get("infos")
                if isinstance(infos, dict):
                    country_id = country_id or infos.get("countryId")

            # Country enrichment is helpful but must never make an otherwise
            # valid WarEra profile fail. A transient country endpoint failure
            # therefore leaves the canonical ID in place and lets the workflow
            # retry enrichment later.
            if country_id and not (isinstance(country_value, dict) and country_value.get("name")):
                try:
                    country_payload = await self._post(client, self.country_path, {"countryId": str(country_id)})
                    country = self._unwrap(country_payload)
                    if isinstance(country, dict) and country.get("name"):
                        resolved_id = str(country.get("_id") or country.get("id") or country_id)
                        profile["country"] = {"id": resolved_id, "name": str(country["name"])}
                        profile["countryName"] = str(country["name"])
                except httpx.HTTPError:
                    pass

        return WarEraProfile(str(user_id), profile)

    async def get_country_by_id(self, country_id: str) -> dict[str, Any] | None:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                payload = await self._post(client, self.country_path, {"countryId": str(country_id)})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
        country = self._unwrap(payload)
        return country if isinstance(country, dict) else None

    async def _get_companies(self, client: httpx.AsyncClient, user_id: str) -> list[dict[str, Any]]:
        companies: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(100):
            payload: dict[str, Any] = {"userId": str(user_id), "perPage": 100}
            if cursor:
                payload["cursor"] = cursor
            data = self._unwrap(await self._post(client, self.companies_path, payload))
            if isinstance(data, dict):
                items = data.get("items") or data.get("companies") or []
                next_cursor = data.get("nextCursor") or data.get("next_cursor")
            elif isinstance(data, list):
                items, next_cursor = data, None
            else:
                items, next_cursor = [], None
            for item in items:
                if isinstance(item, str):
                    companies.append({"_id": item})
                elif isinstance(item, dict):
                    company_id = item.get("_id") or item.get("id") or item.get("companyId")
                    company = dict(item)
                    if company_id:
                        company.setdefault("_id", str(company_id))
                    companies.append(company)
            if not next_cursor or str(next_cursor) == cursor:
                break
            cursor = str(next_cursor)
        return companies

    async def get_companies(self, user_id: str) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await self._get_companies(client, user_id)

    async def _get_company_by_id(self, client: httpx.AsyncClient, company_id: str) -> dict[str, Any] | None:
        try:
            payload = await self._post(client, self.company_path, {"companyId": str(company_id)})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        company = self._unwrap(payload)
        return company if isinstance(company, dict) else None

    async def get_company_by_id(self, company_id: str) -> dict[str, Any] | None:
        timeout = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await self._get_company_by_id(client, company_id)

    async def get_all_company_details(self, user_id: str) -> list[dict[str, Any]]:
        timeout = httpx.Timeout(8.0, connect=4.0)
        limits = httpx.Limits(max_connections=8, max_keepalive_connections=8)
        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            references = await self._get_companies(client, user_id)
            semaphore = asyncio.Semaphore(8)

            async def resolve(reference: dict[str, Any]) -> dict[str, Any] | None:
                if isinstance(reference.get("name"), str):
                    return reference
                company_id = reference.get("_id") or reference.get("id") or reference.get("companyId")
                if not company_id:
                    return None
                async with semaphore:
                    details = await self._get_company_by_id(client, str(company_id))
                if not details:
                    return None
                merged = dict(details)
                merged.setdefault("_id", str(company_id))
                return merged

            resolved = await asyncio.gather(*(resolve(reference) for reference in references))
            return [company for company in resolved if company is not None]

    async def verify_company_otp(self, user_id: str, otp: str | None) -> bool:
        if not otp:
            return False
        return await self.verify_company_otp_hash(user_id, hashlib.sha256(otp.casefold().strip().encode()).hexdigest())

    async def verify_company_otp_hash(self, user_id: str, expected_hash: str) -> bool:
        companies = await self.get_all_company_details(user_id)
        return any(
            isinstance(company.get("name"), str)
            and hashlib.sha256(company["name"].casefold().strip().encode()).hexdigest() == expected_hash
            for company in companies
        )


def detect_government_position(profile: dict[str, Any]) -> str | None:
    """Detect President/VP/MoFA from the full user response."""
    infos = profile.get("infos")
    if isinstance(infos, dict):
        if infos.get("minOfForeignAffairsOf"):
            return "Minister of Foreign Affairs"
        for key, value in infos.items():
            key_norm = str(key).casefold().replace("_", "")
            if value and "vicepresident" in key_norm:
                return "Vice President"
            if value and "president" in key_norm and "vice" not in key_norm:
                return "President"

    def walk(value: Any, key_hint: str = "") -> str | None:
        if isinstance(value, dict):
            for key, child in value.items():
                found = walk(child, str(key))
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child, key_hint)
                if found:
                    return found
        elif isinstance(value, str) and value.strip():
            key_norm = key_hint.casefold().replace("_", "")
            text = value.casefold().strip()
            if "ministerofforeignaffairs" in key_norm or text in {"minister of foreign affairs", "foreign affairs minister", "mofa"}:
                return "Minister of Foreign Affairs"
            if "vicepresident" in key_norm or text == "vice president":
                return "Vice President"
            if ("president" in key_norm and "vice" not in key_norm) or text == "president":
                return "President"
        return None

    return walk(profile)
