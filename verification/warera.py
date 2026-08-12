from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WarEraProfile:
    user_id: str
    profile_url: str
    username: str
    country_id: str
    country_name: str
    is_president: bool
    is_vice_president: bool
    is_eam_or_mofa: bool


@dataclass(frozen=True)
class WarEraCompany:
    company_id: str
    owner_user_id: str
    name: str


class WarEraClient:
    async def get_profile(self, profile_or_id: str) -> WarEraProfile:
        raise NotImplementedError

    async def get_company_names(self, user_id: str) -> list[str]:
        raise NotImplementedError
