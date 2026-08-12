from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import discord

from core.audit import AuditLogger
from core.database import Database
from .snapshot import MigrationSnapshotService, RoleMembershipSnapshot


class MigrationManager:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.snapshots = MigrationSnapshotService(database)
        self.audit = AuditLogger(database)

    async def snapshot_roles(self, guild: discord.Guild, actor_id: int, role_ids: list[int]) -> str:
        memberships: list[RoleMembershipSnapshot] = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is None:
                continue
            memberships.append(RoleMembershipSnapshot(role.id, role.name, tuple(member.id for member in role.members)))
        snapshot = await self.snapshots.create_snapshot(actor_id, memberships, [])
        await self.audit.log(action="MIGRATION_SNAPSHOT_CREATED", actor_id=actor_id, metadata={"snapshot_id": snapshot.snapshot_id, "roles": [x.role_id for x in memberships]})
        return snapshot.snapshot_id

    async def rollback(self, guild: discord.Guild, snapshot_id: str, actor_id: int) -> dict[str, int]:
        snapshot = await self.snapshots.get(snapshot_id)
        if not snapshot:
            raise ValueError("Migration snapshot not found")
        if not await self.snapshots.mark_rollback_started(snapshot_id):
            raise ValueError("Snapshot is already being rolled back or is not ready")
        restored = 0
        removed = 0
        try:
            for item in snapshot.get("role_memberships", []):
                role = guild.get_role(int(item["role_id"]))
                if role is None:
                    continue
                wanted = {int(x) for x in item.get("member_ids", [])}
                for member in guild.members:
                    should_have = member.id in wanted
                    has = role in member.roles
                    if should_have and not has:
                        await member.add_roles(role, reason=f"Embassy migration rollback {snapshot_id}")
                        restored += 1
                    elif not should_have and has:
                        await member.remove_roles(role, reason=f"Embassy migration rollback {snapshot_id}")
                        removed += 1
            summary = {"roles_restored": restored, "roles_removed": removed, "snapshot_id": snapshot_id}
            await self.snapshots.mark_rolled_back(snapshot_id, summary)
            await self.audit.log(action="MIGRATION_ROLLBACK_COMPLETED", actor_id=actor_id, metadata=summary)
            return summary
        except Exception:
            await self.audit.log(action="MIGRATION_ROLLBACK_FAILED", actor_id=actor_id, metadata={"snapshot_id": snapshot_id})
            raise
