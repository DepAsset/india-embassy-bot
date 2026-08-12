from __future__ import annotations

from dataclasses import dataclass

import discord


@dataclass(frozen=True)
class ApprovalPermissionContext:
    can_government_override: bool
    can_foreign_diplomat_decide: bool
    can_preapprove: bool


class ApprovalPermissionPolicy:
    """Centralized authorization policy for approval actions.

    The policy intentionally accepts resolved role booleans from a Discord
    adapter. It never trusts a client-provided role name or button state.
    """

    def __init__(
        self,
        president_role_id: int,
        vice_president_role_id: int,
        nsa_role_id: int,
        minister_role_id: int,
        foreign_diplomat_role_id: int,
        admin_check,
    ) -> None:
        self.government_roles = {
            president_role_id,
            vice_president_role_id,
            nsa_role_id,
            minister_role_id,
        }
        self.foreign_diplomat_role_id = foreign_diplomat_role_id
        self.admin_check = admin_check

    def is_government_authority(self, member: discord.Member) -> bool:
        return self.admin_check(member) or any(role.id in self.government_roles for role in member.roles)

    def is_foreign_diplomat(self, member: discord.Member) -> bool:
        return any(role.id == self.foreign_diplomat_role_id for role in member.roles)

    def context(self, member: discord.Member, assigned_to_embassy: bool) -> ApprovalPermissionContext:
        government = self.is_government_authority(member)
        diplomat = self.is_foreign_diplomat(member) and assigned_to_embassy
        return ApprovalPermissionContext(
            can_government_override=government,
            can_foreign_diplomat_decide=diplomat,
            can_preapprove=diplomat,
        )
