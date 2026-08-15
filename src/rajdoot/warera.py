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
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.warera_api_base_url.rstrip("/")
        self.profile_path = settings.warera_api_profile_path
        self.token = settings.warera_api_token

    async def get_profile(self, user_id: str) -> WarEraProfile | None:
        if not self.token or self.token.startswith("<PUT_"):
            return None
        url = f"{self.base_url}{self.profile_path}"
        headers = {"X-API-Key": self.token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"userId": str(user_id)}, headers=headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("user"), dict):
            profile = payload["user"]
        elif isinstance(payload, dict) and isinstance(payload.get("result"), dict):
            profile = payload["result"]
        else:
            profile = payload if isinstance(payload, dict) else {"data": payload}
        return WarEraProfile(user_id=str(user_id), raw=profile)
