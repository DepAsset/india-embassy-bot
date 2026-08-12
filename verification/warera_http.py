from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .warera import WarEraClient, WarEraCompany, WarEraProfile


class WarEraAPIError(RuntimeError):
    pass


class WarEraHTTPClient(WarEraClient):
    """HTTP adapter for the public WarEra API used by Embassy verification.

    Verification deliberately does not trust the `company` field returned by
    user.getUserById. That field represents the company the player works for.
    Company ownership is established through company.getCompanies(userId),
    followed by company.getById for each returned company.
    """

    def __init__(
        self,
        base_url: str,
        *,
        user_by_id_endpoint: str = "/trpc/user.getUserById",
        country_by_id_endpoint: str = "/trpc/country.getCountryById",
        government_by_country_endpoint: str = "/trpc/government.getByCountryId",
        companies_endpoint: str = "/trpc/company.getCompanies",
        company_by_id_endpoint: str = "/trpc/company.getById",
        timeout: float = 12.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_by_id_endpoint = user_by_id_endpoint
        self.country_by_id_endpoint = country_by_id_endpoint
        self.government_by_country_endpoint = government_by_country_endpoint
        self.companies_endpoint = companies_endpoint
        self.company_by_id_endpoint = company_by_id_endpoint
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    @staticmethod
    def normalize_user_input(value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme and parsed.netloc:
            path = parsed.path.rstrip("/")
            match = re.search(r"(?:profile|user)/([A-Za-z0-9_-]+)", path, re.I)
            if match:
                return match.group(1)
            tail = path.rsplit("/", 1)[-1]
            if tail:
                return tail
        match = re.search(r"(?:profile|user)[/:]([A-Za-z0-9_-]+)", value, re.I)
        if match:
            return match.group(1)
        return value

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(f"{self.base_url}{path}", json=payload) as response:
                text = await response.text()
                if response.status >= 400:
                    raise WarEraAPIError(f"WarEra API returned HTTP {response.status}: {text[:500]}")
                try:
                    return await response.json(content_type=None)
                except Exception as exc:
                    raise WarEraAPIError("WarEra API returned non-JSON data") from exc

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            result = payload["result"]
            if "data" in result:
                data = result["data"]
                if isinstance(data, dict) and "json" in data:
                    return data["json"]
                return data
            return result
        return payload

    @classmethod
    def _object(cls, payload: Any) -> dict[str, Any]:
        data = cls._unwrap(payload)
        if not isinstance(data, dict):
            raise WarEraAPIError("WarEra API returned an unexpected object")
        return data

    async def _get_user(self, user_id: str) -> dict[str, Any]:
        return self._object(await self._post(self.user_by_id_endpoint, {"userId": user_id}))

    async def _get_country(self, country_id: str) -> dict[str, Any]:
        return self._object(await self._post(self.country_by_id_endpoint, {"countryId": country_id}))

    async def _get_government(self, country_id: str) -> dict[str, Any]:
        return self._object(await self._post(self.government_by_country_endpoint, {"countryId": country_id}))

    async def get_profile(self, profile_or_id: str) -> WarEraProfile:
        user_id = self.normalize_user_input(profile_or_id)
        data = await self._get_user(user_id)

        canonical_id = str(data.get("_id") or data.get("id") or data.get("userId") or user_id)
        country_id = str(data.get("country") or data.get("countryId") or data.get("country_id") or "")
        if not country_id:
            raise WarEraAPIError("WarEra user profile did not contain a country ID")

        country_data = await self._get_country(country_id)
        country = country_data.get("country") if isinstance(country_data.get("country"), dict) else country_data
        country_name = str(country.get("name") or country.get("countryName") or country_id)

        government_data = await self._get_government(country_id)
        government = government_data.get("government") if isinstance(government_data.get("government"), dict) else government_data

        def role_text(obj: Any) -> str:
            if not isinstance(obj, dict):
                return ""
            values = [obj.get("role"), obj.get("title"), obj.get("position"), obj.get("type")]
            return " ".join(str(value).lower() for value in values if value)

        # Government endpoint shape can vary between API revisions. We inspect
        # the government object plus common user-side flags without assuming
        # that the employment company field means official status.
        gov_text = role_text(government)
        user_text = role_text(data)
        roles = {str(value).lower() for value in (data.get("roles") or []) if isinstance(value, (str, int))}

        return WarEraProfile(
            user_id=canonical_id,
            profile_url=f"https://warera.io/profile/{canonical_id}",
            username=str(data.get("username") or data.get("name") or canonical_id),
            country_id=country_id,
            country_name=country_name,
            is_president=bool(data.get("isPresident") or "president" in roles or "president" in user_text or "president" in gov_text),
            is_vice_president=bool(data.get("isVicePresident") or "vice president" in roles or "vice_president" in roles or "vice president" in user_text),
            is_eam_or_mofa=bool(data.get("isEamOrMofa") or data.get("isForeignMinister") or "eam" in roles or "foreign minister" in roles or "mofa" in roles or "foreign affairs" in gov_text),
        )

    async def get_companies(self, user_id: str) -> list[WarEraCompany]:
        companies: list[WarEraCompany] = []
        cursor: str | None = None

        while True:
            payload = {"userId": user_id, "perPage": 100}
            if cursor:
                payload["cursor"] = cursor
            data = self._object(await self._post(self.companies_endpoint, payload))
            items = data.get("items") or data.get("companies") or []
            if not isinstance(items, list):
                raise WarEraAPIError("WarEra company list returned an unexpected items field")

            for item in items:
                company_id = str(item.get("_id") or item.get("id") or item) if isinstance(item, dict) else str(item)
                if company_id:
                    companies.append(WarEraCompany(company_id=company_id, owner_user_id=user_id, name=str(item.get("name") or "") if isinstance(item, dict) else ""))

            next_cursor = data.get("nextCursor") or data.get("next_cursor") or data.get("cursor")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)

        return companies

    async def get_company(self, company_id: str) -> WarEraCompany:
        data = self._object(await self._post(self.company_by_id_endpoint, {"companyId": company_id}))
        company = data.get("company") if isinstance(data.get("company"), dict) else data
        return WarEraCompany(
            company_id=str(company.get("_id") or company.get("id") or company_id),
            owner_user_id=str(company.get("user") or company.get("userId") or ""),
            name=str(company.get("name") or ""),
        )

    async def get_company_names(self, user_id: str) -> list[str]:
        """Return names from every company owned by the user.

        The company list endpoint is used only to discover IDs. Each ID is
        resolved through company.getById before its name is trusted.
        """
        discovered = await self.get_companies(user_id)
        names: list[str] = []
        for company in discovered:
            detail = await self.get_company(company.company_id)
            if detail.owner_user_id and detail.owner_user_id != user_id:
                continue
            if detail.name:
                names.append(detail.name)
        return names
