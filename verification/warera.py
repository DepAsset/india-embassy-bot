from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
