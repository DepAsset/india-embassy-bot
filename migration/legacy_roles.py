from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import discord

from migration.snapshot import RoleMembershipSnapshot


@dataclass(frozen=True)
class LegacyRoleRecord:
    role_id: int
    role_name: str


class LegacyRoleMigrator:
    """Collects and later applies the legacy embassy-role migration.

    Snapshot creation is deliberately separate from role removal. No role is
    removed by this service unless an explicit, validated migration executor
    calls the removal method.
    """

    def __init__(self, guild: discord.Guild) -> None:
        self.guild = guild

    def snapshot_role(self, role: discord.Role) -> RoleMembershipSnapshot:
        return RoleMembershipSnapshot(
            role_id=role.id,
            role_name=role.name,
            member_ids=tuple(member.id for member in role.members),
        )

    def snapshot_roles(self, role_ids: Iterable[int]) -> list[RoleMembershipSnapshot]:
        result: list[RoleMembershipSnapshot] = []
        for role_id in role_ids:
            role = self.guild.get_role(int(role_id))
            if role is None:
                continue
            result.append(self.snapshot_role(role))
        return result

    async def restore_role_memberships(
        self,
        snapshot: RoleMembershipSnapshot,
        reason: str = "Embassy migration rollback",
    ) -> dict[str, int]:
        role = self.guild.get_role(snapshot.role_id)
        if role is None:
            return {"missing_role": 1, "restored": 0, "failed": 0}

        restored = failed = 0
        for member_id in snapshot.member_ids:
            member = self.guild.get_member(member_id)
            if member is None:
                failed += 1
                continue
            if role not in member.roles:
                try:
                    await member.add_roles(role, reason=reason)
                    restored += 1
                except discord.HTTPException:
                    failed += 1
        return {"missing_role": 0, "restored": restored, "failed": failed}
