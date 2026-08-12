from __future__ import annotations

import discord


class DiscordAccessProvisioner:
    """Applies an already-approved assignment to Discord.

    The database decision is made before this class is called. This keeps
    Discord permissions as a projection of the persistent access state.
    """

    def __init__(self, *, foreginer_role_id: int | None = None, foreign_diplomat_role_id: int | None = None, ambassador_role_id: int | None = None):
        self.foreigner_role_id = foreginer_role_id
        self.foreign_diplomat_role_id = foreign_diplomat_role_id
        self.ambassador_role_id = ambassador_role_id

    async def grant_embassy_access(
        self,
        member: discord.Member,
        channel: discord.TextChannel,
        *,
        reason: str,
    ) -> None:
        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = True
        overwrite.send_messages = True
        overwrite.read_message_history = True
        await channel.set_permissions(member, overwrite=overwrite, reason=reason)

    async def revoke_embassy_access(
        self,
        member: discord.Member,
        channel: discord.TextChannel,
        *,
        reason: str,
    ) -> None:
        await channel.set_permissions(member, overwrite=None, reason=reason)

    async def ensure_role(self, member: discord.Member, role: discord.Role, *, reason: str) -> bool:
        if role in member.roles:
            return False
        await member.add_roles(role, reason=reason)
        return True

    async def remove_role(self, member: discord.Member, role: discord.Role, *, reason: str) -> bool:
        if role not in member.roles:
            return False
        await member.remove_roles(role, reason=reason)
        return True
