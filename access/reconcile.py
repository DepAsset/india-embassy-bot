from __future__ import annotations

import discord

from access.service import AccessService


class AccessReconciler:
    """Repairs Discord projection from MongoDB assignments after restarts or drift."""

    def __init__(self, access: AccessService):
        self.access = access

    async def user_assignments(self, member: discord.Member) -> list[dict]:
        return await self.access.active_for_user(member.id)

    async def needs_foreign_diplomat_role(self, member: discord.Member) -> bool:
        assignments = await self.user_assignments(member)
        return any(item.get("assignment_type") == "FOREIGN_DIPLOMAT" for item in assignments)

    async def needs_ambassador_role(self, member: discord.Member) -> bool:
        assignments = await self.user_assignments(member)
        return any(item.get("assignment_type") == "AMBASSADOR" for item in assignments)

    async def active_embassy_ids(self, member: discord.Member) -> set[str]:
        return {item["embassy_id"] for item in await self.user_assignments(member)}
