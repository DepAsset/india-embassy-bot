from __future__ import annotations

import re
from dataclasses import dataclass

import discord

from rajdoot.config import settings
from rajdoot.database import Database


@dataclass(frozen=True)
class EmbassyMemberImportResult:
    embassies_scanned: int
    access_roles_found: int
    assignments_seen: int
    foreign_diplomats: int
    indian_ambassadors: int
    unchanged: int
    deactivated: int
    unmatched_embassies: int


class EmbassyMemberImporter:
    """Read current Discord embassy-role memberships into the Supabase registry.

    Every person holding an embassy-specific access role is registered as one of:
    - foreign_diplomat: embassy access role, but no Indian Citizen role
    - indian_ambassador: embassy access role AND Indian Citizen role
    """

    @staticmethod
    def _norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.casefold())

    @classmethod
    def _role_matches_country(cls, role_name: str, country_name: str) -> bool:
        role = cls._norm(role_name)
        country = cls._norm(country_name)
        return "embassyaccess" in role and country in role

    @staticmethod
    def _is_indian_citizen(member: discord.Member, citizen_role_id: int | None) -> bool:
        if citizen_role_id is not None:
            return any(role.id == citizen_role_id for role in member.roles)
        return any(role.name.casefold().strip() == "indian citizen" for role in member.roles)

    @staticmethod
    def _as_id(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    async def import_current_members(
        self,
        guild: discord.Guild,
        database: Database,
    ) -> EmbassyMemberImportResult:
        embassies = await database.fetch_active_embassies()
        legacy_roles = await database.fetch_legacy_roles()

        # Legacy-role data is the strongest mapping because it contains the
        # exact Discord role ID. Country-name matching is only a safe fallback.
        role_to_embassy: dict[int, str] = {}
        for row in legacy_roles:
            try:
                role_id = int(row["role_id"])
            except (TypeError, ValueError):
                continue
            embassy_id = self._as_id(row.get("embassy_id"))
            if embassy_id:
                role_to_embassy[role_id] = embassy_id

        embassy_by_id = {
            self._as_id(row.get("id")): row
            for row in embassies
            if self._as_id(row.get("id"))
        }

        matched_roles: dict[int, str] = {}
        for role in guild.roles:
            mapped_embassy_id = role_to_embassy.get(role.id)
            if mapped_embassy_id and mapped_embassy_id in embassy_by_id:
                matched_roles[role.id] = mapped_embassy_id
                continue

            for embassy in embassies:
                embassy_id = self._as_id(embassy.get("id"))
                country_name = self._as_id(embassy.get("country_name"))
                if embassy_id and country_name and self._role_matches_country(role.name, country_name):
                    matched_roles[role.id] = embassy_id
                    break

        citizen_role_id = getattr(settings, "indian_citizen_role_id", None)
        assignments_seen = 0
        foreign_diplomats = 0
        indian_ambassadors = 0
        unchanged = 0
        deactivated = 0

        # An embassy should have one country-specific access role. If multiple
        # roles accidentally map to it, process each role independently and
        # preserve the exact role ID on the registry record.
        for role_id, embassy_id in matched_roles.items():
            role = guild.get_role(role_id)
            if role is None:
                continue

            seen_user_ids: set[str] = set()
            for member in role.members:
                user_id = str(member.id)
                seen_user_ids.add(user_id)
                assignments_seen += 1

                member_type = (
                    "indian_ambassador"
                    if self._is_indian_citizen(member, citizen_role_id)
                    else "foreign_diplomat"
                )

                changed = await database.upsert_embassy_member(
                    embassy_id=embassy_id,
                    discord_user_id=user_id,
                    discord_username=str(member),
                    member_type=member_type,
                    embassy_role_id=str(role.id),
                )
                if changed:
                    if member_type == "indian_ambassador":
                        indian_ambassadors += 1
                    else:
                        foreign_diplomats += 1
                else:
                    unchanged += 1

            deactivated += await database.deactivate_missing_embassy_members(
                embassy_id=embassy_id,
                embassy_role_id=str(role.id),
                seen_user_ids=seen_user_ids,
            )

        matched_embassies = set(matched_roles.values())
        return EmbassyMemberImportResult(
            embassies_scanned=len(embassies),
            access_roles_found=len(matched_roles),
            assignments_seen=assignments_seen,
            foreign_diplomats=foreign_diplomats,
            indian_ambassadors=indian_ambassadors,
            unchanged=unchanged,
            deactivated=deactivated,
            unmatched_embassies=max(0, len(embassies) - len(matched_embassies)),
        )
