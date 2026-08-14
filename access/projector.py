from __future__ import annotations

import discord

from app.config import settings
from core.audit import AuditLogger
from core.database import Database
from embassy.registry import EmbassyRegistry
from .service import AccessService


class AccessProjector:
    """Projects MongoDB assignments into Discord permissions and global roles."""

    def __init__(self, database: Database) -> None:
        self.db = database
        self.assignments = AccessService(database)
        self.registry = EmbassyRegistry(database)
        self.audit = AuditLogger(database)

    async def grant(self, guild: discord.Guild, user_id: int, embassy_id: str, actor_id: int | None, reason: str) -> bool:
        embassy = await self.registry.get_by_id(embassy_id)
        if not embassy or not embassy.active:
            raise ValueError("Embassy does not exist or is archived")
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        channel = guild.get_channel(embassy.channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Embassy channel is missing")
        overwrite = channel.overwrites_for(member)
        overwrite.view_channel = True
        overwrite.send_messages = True
        overwrite.read_message_history = True
        await channel.set_permissions(member, overwrite=overwrite, reason=reason)
        await self.audit.log(action="DISCORD_ACCESS_GRANTED", actor_id=actor_id, target_id=str(user_id), embassy_id=embassy_id, metadata={"channel_id": channel.id})
        return True

    async def revoke(self, guild: discord.Guild, user_id: int, embassy_id: str, actor_id: int, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("A revocation reason is required")
        embassy = await self.registry.get_by_id(embassy_id)
        if not embassy:
            return False
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        channel = guild.get_channel(embassy.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return False
        await channel.set_permissions(member, overwrite=None, reason=reason)
        await self.audit.log(action="DISCORD_ACCESS_REVOKED", actor_id=actor_id, target_id=str(user_id), embassy_id=embassy_id, reason=reason)
        return True

    async def ensure_role(self, guild: discord.Guild, user_id: int, role_id: int, reason: str) -> bool:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        role = guild.get_role(role_id)
        if role is None or role in member.roles:
            return False
        await member.add_roles(role, reason=reason)
        return True

    async def reconcile_member(self, guild: discord.Guild, user_id: int) -> dict[str, int]:
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        active = await self.assignments.active_for_user(user_id)
        active_embassies = {str(item["embassy_id"]) for item in active}
        granted = revoked = 0

        # Restore every assignment-backed direct permission.
        for embassy_id in active_embassies:
            try:
                if await self.grant(guild, user_id, embassy_id, None, "Embassy access reconciliation"):
                    granted += 1
            except (discord.HTTPException, ValueError):
                continue

        # Remove stale direct overrides for Embassy channels no longer assigned.
        for embassy in await self.registry.get_active():
            if embassy.embassy_id in active_embassies:
                continue
            channel = guild.get_channel(embassy.channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            overwrite = channel.overwrites_for(member)
            if overwrite.view_channel is True or overwrite.send_messages is True or overwrite.read_message_history is True:
                try:
                    await channel.set_permissions(member, overwrite=None, reason="Embassy access reconciliation")
                    revoked += 1
                except discord.HTTPException:
                    continue

        # Ambassadors are also Foreign Diplomats for global dashboard access.
        has_diplomat = any(item.get("assignment_type") in {"FOREIGN_DIPLOMAT", "AMBASSADOR"} for item in active)
        has_ambassador = any(item.get("assignment_type") == "AMBASSADOR" for item in active)
        for role_id, should_have in (
            (settings.role_foreign_diplomat_id, has_diplomat),
            (settings.role_ambassador_id, has_ambassador),
        ):
            role = guild.get_role(role_id)
            if not role:
                continue
            try:
                if should_have and role not in member.roles:
                    await member.add_roles(role, reason="Embassy access reconciliation")
                elif not should_have and role in member.roles:
                    await member.remove_roles(role, reason="Embassy access reconciliation")
            except discord.HTTPException:
                continue

        return {"active_assignments": len(active), "channels_granted": granted, "channels_revoked": revoked}
