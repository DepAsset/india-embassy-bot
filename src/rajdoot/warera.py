from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from rajdoot.config import Settings


@dataclass(frozen=True, slots=True)
class WarEraProfile:
    user_id: str
    raw: dict[str, Any]


class WarEraClient:
    """Small, purpose-built WarEra client.

    The embassy flow only needs three reads: lite/full user data and the user's
    companies. Keeping those calls here makes the workflow easy to test and
    prevents Discord UI code from knowing anything about tRPC wire formats.
    """

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.warera_api_base_url.rstrip("/")
        self.profile_path = settings.warera_api_profile_path
        self.full_profile_path = settings.warera_api_full_profile_path
        self.companies_path = settings.warera_api_companies_path
        self.token = settings.warera_api_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token and not self.token.startswith("<PUT_"):
            headers["X-API-Key"] = self.token
        return headers

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=self._headers())
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
        try:
            payload = await self._post(self.profile_path, {"userId": str(user_id)})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        profile = self._unwrap(payload)
        if not isinstance(profile, dict):
            return None
        return WarEraProfile(user_id=str(user_id), raw=profile)

    async def get_full_profile(self, user_id: str) -> WarEraProfile | None:
        try:
            payload = await self._post(self.full_profile_path, {"userId": str(user_id)})
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        profile = self._unwrap(payload)
        if not isinstance(profile, dict):
            return None
        return WarEraProfile(user_id=str(user_id), raw=profile)

    async def get_companies(self, user_id: str) -> list[dict[str, Any]]:
        """Return all companies owned by a user, following the cursor if needed."""
        companies: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(100):
            payload: dict[str, Any] = {"userId": str(user_id), "perPage": 100}
            if cursor:
                payload["cursor"] = cursor
            data = self._unwrap(await self._post(self.companies_path, payload))
            if isinstance(data, dict):
                items = data.get("companies") or data.get("items") or []
                next_cursor = data.get("nextCursor") or data.get("next_cursor") or data.get("cursor")
            elif isinstance(data, list):
                items = data
                next_cursor = None
            else:
                items = []
                next_cursor = None
            for item in items:
                if isinstance(item, dict):
                    companies.append(item)
            if not next_cursor or next_cursor == cursor:
                break
            cursor = str(next_cursor)
        return companies

    async def verify_company_otp(self, user_id: str, otp: str) -> bool:
        expected = otp.casefold().strip()
        companies = await self.get_companies(user_id)
        for company in companies:
            name = company.get("name") or company.get("companyName") or company.get("title")
            if isinstance(name, str) and name.casefold().strip() == expected:
                return True
        return False


def detect_government_position(profile: dict[str, Any]) -> str | None:
    """Detect President/VP/MoFA from the full user response.

    WarEra has exposed government membership under the `infos` object (for
    example `minOfForeignAffairsOf`). The recursive fallback also tolerates
    minor API shape changes without making a false positive from unrelated
    prose.
    """
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
            if "ministerofforeignaffairs" in key_norm or text in {
                "minister of foreign affairs", "foreign affairs minister", "mofa"
            }:
                return "Minister of Foreign Affairs"
            if "vicepresident" in key_norm or text == "vice president":
                return "Vice President"
            if "president" in key_norm and "vice" not in key_norm or text == "president":
                return "President"
        return None

    return walk(profile)
