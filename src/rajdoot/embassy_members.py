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
    unmatched_embassies: int


class EmbassyMemberImporter:
    """Read current Discord embassy-role memberships into Supabase."""

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
        if citizen_role_id:
            return any(role.id == citizen_role_id for role in member.roles)
        return any(role.name.casefold().strip() == "indian citizen" for role in member.roles)

    async def import_current_members(
        self,
        guild: discord.Guild,
        database: Database,
    ) -> EmbassyMemberImportResult:
        embassies = await database.fetch_active_embassies()
        legacy_roles = await database.fetch_legacy_roles()

        role_to_embassy: dict[int, int] = {}
        for row in legacy_roles:
            try:
                role_id = int(row["role_id"])
                embassy_id = int(row["embassy_id"])
            except (TypeError, ValueError):
                continue
            role_to_embassy[role_id] = embassy_id

        embassy_by_id = {int(row["id"]): row for row in embassies}
        matched_roles: dict[int, int] = {}
        for role in guild.roles:
            if role.id in role_to_embassy and role_to_embassy[role.id] in embassy_by_id:
                matched_roles[role.id] = role_to_embassy[role.id]
                continue
            for embassy in embassies:
                if self._role_matches_country(role.name, str(embassy["country_name"])):
                    matched_roles[role.id] = int(embassy["id"])
                    break

        citizen_role_id = getattr(settings, "indian_citizen_role_id", None)
        assignments_seen = 0
        foreign_diplomats = 0
        indian_ambassadors = 0
        unchanged = 0

        for role_id, embassy_id in matched_roles.items():
            role = guild.get_role(role_id)
            if role is None:
                continue
            for member in role.members:
                assignments_seen += 1
                member_type = (
                    "indian_ambassador"
                    if self._is_indian_citizen(member, citizen_role_id)
                    else "foreign_diplomat"
                )
                changed = await database.upsert_embassy_member(
                    embassy_id=embassy_id,
                    discord_user_id=str(member.id),
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

        matched_embassies = {v for v in matched_roles.values()}
        return EmbassyMemberImportResult(
            embassies_scanned=len(embassies),
            access_roles_found=len(matched_roles),
            assignments_seen=assignments_seen,
            foreign_diplomats=foreign_diplomats,
            indian_ambassadors=indian_ambassadors,
            unchanged=unchanged,
            unmatched_embassies=max(0, len(embassies) - len(matched_embassies)),
        )
