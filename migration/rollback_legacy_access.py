from __future__ import annotations

import os
from datetime import datetime, timezone

import discord

from core.audit import AuditLogger
from core.database import Database
from migration.snapshot import MigrationSnapshotService

ROLLBACK_ID = "legacy_embassy_direct_access_rollback_v1"


class LegacyAccessRollback:
    """Restore legacy Embassy role membership and remove only migration-created overrides."""

    def __init__(self, database: Database) -> None:
        self.db = database
        self.snapshots = MigrationSnapshotService(database)
        self.audit = AuditLogger(database)

    async def rollback_latest(self, guild: discord.Guild, actor_id: int = 0) -> dict:
        state = self.db.collection("migration_state")
        if await state.find_one({"migration_id": ROLLBACK_ID, "status": "COMPLETED"}):
            return {"status": "ALREADY_COMPLETED"}

        snapshot = await self.db.collection("migration_snapshots").find_one(
            {"status": {"$in": ["READY", "ROLLBACK_STARTED"]}},
            sort=[("created_at", -1)],
        )
        if not snapshot:
            return {"status": "NO_SNAPSHOT"}

        snapshot_id = str(snapshot["snapshot_id"])
        if not await self.snapshots.mark_rollback_started(snapshot_id):
            return {"status": "ROLLBACK_ALREADY_RUNNING", "snapshot_id": snapshot_id}

        result = {
            "migration_id": ROLLBACK_ID,
            "snapshot_id": snapshot_id,
            "roles_restored": 0,
            "role_restore_failures": 0,
            "overrides_removed": 0,
            "override_failures": 0,
            "started_at": datetime.now(timezone.utc),
        }

        try:
            # 1. Restore every member to the legacy Embassy access role exactly as
            # recorded immediately before the direct-access migration.
            for item in snapshot.get("role_memberships", []):
                role = guild.get_role(int(item["role_id"]))
                if role is None:
                    result["role_restore_failures"] += len(item.get("member_ids", []))
                    continue
                for raw_member_id in item.get("member_ids", []):
                    try:
                        member = guild.get_member(int(raw_member_id)) or await guild.fetch_member(int(raw_member_id))
                        if role not in member.roles:
                            await member.add_roles(role, reason="Rollback legacy Embassy direct-access migration")
                            result["roles_restored"] += 1
                    except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                        result["role_restore_failures"] += 1

            # 2. Remove only the three permission fields the migration projector
            # controlled. Do not blindly delete a member overwrite because a
            # future/parallel system may have legitimate per-user permissions.
            channel_ids = {
                int(item["channel_id"])
                for item in snapshot.get("embassy_mappings", [])
                if item.get("channel_id")
            }
            member_ids = {
                int(member_id)
                for item in snapshot.get("role_memberships", [])
                for member_id in item.get("member_ids", [])
            }

            for channel_id in channel_ids:
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    continue
                for member_id in member_ids:
                    member = guild.get_member(member_id)
                    if member is None:
                        continue
                    overwrite = channel.overwrites_for(member)
                    if not any(
                        getattr(overwrite, field) is True
                        for field in ("view_channel", "send_messages", "read_message_history")
                    ):
                        continue
                    overwrite.view_channel = None
                    overwrite.send_messages = None
                    overwrite.read_message_history = None
                    try:
                        if overwrite.is_empty():
                            await channel.set_permissions(member, overwrite=None, reason="Rollback legacy Embassy direct-access migration")
                        else:
                            await channel.set_permissions(member, overwrite=overwrite, reason="Rollback legacy Embassy direct-access migration")
                        result["overrides_removed"] += 1
                    except (discord.HTTPException, discord.Forbidden):
                        result["override_failures"] += 1

            result["completed_at"] = datetime.now(timezone.utc)
            result["status"] = "COMPLETED" if result["role_restore_failures"] == 0 and result["override_failures"] == 0 else "COMPLETED_WITH_FAILURES"
            await state.insert_one(result)
            await self.snapshots.mark_rolled_back(snapshot_id, result)
            await self.audit.log(
                action="LEGACY_DIRECT_ACCESS_ROLLBACK_COMPLETED",
                actor_id=actor_id,
                metadata={k: v for k, v in result.items() if k not in {"started_at", "completed_at"}},
            )
            return result
        except Exception:
            await state.insert_one({**result, "status": "FAILED", "completed_at": datetime.now(timezone.utc)})
            await self.audit.log(
                action="LEGACY_DIRECT_ACCESS_ROLLBACK_FAILED",
                actor_id=actor_id,
                metadata={"snapshot_id": snapshot_id},
            )
            raise


async def rollback_if_requested(database: Database, guild: discord.Guild) -> dict | None:
    """One-shot deployment hook. It is inert unless explicitly enabled."""
    if os.getenv("LEGACY_ACCESS_ROLLBACK", "").strip().lower() not in {"1", "true", "yes"}:
        return None
    return await LegacyAccessRollback(database).rollback_latest(guild)
