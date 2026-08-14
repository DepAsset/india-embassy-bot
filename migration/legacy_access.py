from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import discord

from access.models import AccessSource, AssignmentType
from access.projector import AccessProjector
from access.service import AccessService
from core.audit import AuditLogger
from core.database import Database
from migration.embassy_seed import _read_seed
from migration.snapshot import MigrationSnapshotService, RoleMembershipSnapshot

MIGRATION_ID = "legacy_embassy_direct_access_v1"
SYNC_ID = "legacy_embassy_direct_access_sync_v2"


class LegacyAccessMigration:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.audit = AuditLogger(database)
        self.snapshots = MigrationSnapshotService(database)
        self.access = AccessService(database)
        self.projector = AccessProjector(database)

    def rows(self) -> list[dict]:
        return [row for row in _read_seed() if row["active"] and row["access_role_id"]]

    async def dry_run(self, guild: discord.Guild) -> dict:
        rows = self.rows()
        role_ids = sorted({int(row["access_role_id"]) for row in rows})
        report = {"embassies": 0, "members": 0, "permissions": 0, "missing_roles": 0, "missing_channels": 0, "already_assigned": 0}
        seen: set[tuple[int, str]] = set()
        for row in rows:
            role = guild.get_role(int(row["access_role_id"]))
            channel = guild.get_channel(int(row["channel_id"]))
            if role is None:
                report["missing_roles"] += 1
                continue
            if not isinstance(channel, discord.TextChannel):
                report["missing_channels"] += 1
                continue
            report["embassies"] += 1
            for member in role.members:
                key = (member.id, str(row["embassy_id"]))
                if key in seen:
                    continue
                seen.add(key)
                report["members"] += 1
                report["permissions"] += 1
                if await self.access.has_access(member.id, str(row["embassy_id"])):
                    report["already_assigned"] += 1
        report["role_count"] = len(role_ids)
        return report

    async def sync_direct_access(self, guild: discord.Guild, actor_id: int = 0) -> dict:
        """Safely convert legacy role membership into direct access without removing roles.

        This is idempotent and intentionally leaves legacy roles in place until an
        administrator verifies the migration report and explicitly finalizes removal.
        """
        state = self.db.collection("migration_state")
        if await state.find_one({"migration_id": SYNC_ID, "status": "COMPLETED"}):
            return {"status": "ALREADY_COMPLETED"}

        rows = self.rows()
        result = {"migration_id": SYNC_ID, "embassies": 0, "members": 0, "successful": 0, "failed": 0, "missing_roles": 0, "missing_channels": 0, "started_at": datetime.now(timezone.utc)}
        seen: set[tuple[int, str]] = set()
        for row in rows:
            role = guild.get_role(int(row["access_role_id"]))
            channel = guild.get_channel(int(row["channel_id"]))
            if role is None:
                result["missing_roles"] += 1
                continue
            if not isinstance(channel, discord.TextChannel):
                result["missing_channels"] += 1
                continue
            result["embassies"] += 1
            for member in list(role.members):
                key = (member.id, str(row["embassy_id"]))
                if key in seen:
                    continue
                seen.add(key)
                result["members"] += 1
                try:
                    await self.access.assign(member.id, str(row["embassy_id"]), AssignmentType.FOREIGN_DIPLOMAT, AccessSource.MIGRATION, assigned_by=actor_id)
                    await self.projector.grant(guild, member.id, str(row["embassy_id"]), actor_id, "Legacy Embassy role migration to direct access")
                    await self.projector.ensure_role(guild, member.id, __import__("app.config", fromlist=["settings"]).settings.role_foreign_diplomat_id, "Legacy Embassy role migration")
                    result["successful"] += 1
                except Exception:
                    result["failed"] += 1

        result["completed_at"] = datetime.now(timezone.utc)
        result["status"] = "COMPLETED" if result["failed"] == 0 and result["missing_roles"] == 0 and result["missing_channels"] == 0 else "COMPLETED_WITH_FAILURES"
        await state.insert_one(result)
        await self.audit.log(action="LEGACY_DIRECT_ACCESS_SYNC_COMPLETED", actor_id=actor_id, metadata={k: v for k, v in result.items() if k not in {"started_at", "completed_at"}})
        return result

    async def execute(self, guild: discord.Guild, actor_id: int, *, confirm_token: str) -> dict:
        if confirm_token != "MIGRATE-DIRECT-ACCESS":
            raise ValueError("Migration confirmation token is invalid")
        state = self.db.collection("migration_state")
        if await state.find_one({"migration_id": MIGRATION_ID, "status": "COMPLETED"}):
            raise ValueError("Legacy direct-access migration has already completed")

        rows = self.rows()
        role_ids = sorted({int(row["access_role_id"]) for row in rows})
        memberships: list[RoleMembershipSnapshot] = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is not None:
                memberships.append(RoleMembershipSnapshot(role.id, role.name, tuple(m.id for m in role.members)))

        snapshot = await self.snapshots.create_snapshot(actor_id, memberships, await self.db.collection("embassies").find({}).to_list(length=None))
        run_id = str(uuid4())
        result = {"migration_id": MIGRATION_ID, "run_id": run_id, "snapshot_id": snapshot.snapshot_id, "embassies": 0, "members": 0, "successful": 0, "failed": 0, "roles_removed": 0, "role_failures": 0, "started_at": datetime.now(timezone.utc)}

        try:
            for row in rows:
                role = guild.get_role(int(row["access_role_id"]))
                channel = guild.get_channel(int(row["channel_id"]))
                if role is None or not isinstance(channel, discord.TextChannel):
                    result["failed"] += len(role.members) if role else 1
                    continue
                result["embassies"] += 1
                role_failed = False
                for member in list(role.members):
                    result["members"] += 1
                    try:
                        await self.access.assign(member.id, str(row["embassy_id"]), AssignmentType.FOREIGN_DIPLOMAT, AccessSource.MIGRATION, assigned_by=actor_id)
                        await self.projector.grant(guild, member.id, str(row["embassy_id"]), actor_id, "Legacy Embassy role migration to direct access")
                        await self.projector.ensure_role(guild, member.id, __import__("app.config", fromlist=["settings"]).settings.role_foreign_diplomat_id, "Legacy Embassy role migration")
                        result["successful"] += 1
                    except Exception:
                        result["failed"] += 1
                        role_failed = True
                if not role_failed:
                    removed_all = True
                    for member in list(role.members):
                        try:
                            await member.remove_roles(role, reason=f"Legacy Embassy direct-access migration {run_id}")
                            result["roles_removed"] += 1
                        except Exception:
                            removed_all = False
                            result["role_failures"] += 1
                    if not removed_all:
                        result["role_failures"] += 1
                else:
                    result["role_failures"] += 1

            result["completed_at"] = datetime.now(timezone.utc)
            result["status"] = "COMPLETED" if result["failed"] == 0 and result["role_failures"] == 0 else "COMPLETED_WITH_FAILURES"
            await state.insert_one(result)
            await self.audit.log(action="LEGACY_DIRECT_ACCESS_MIGRATION_COMPLETED", actor_id=actor_id, metadata={k: v for k, v in result.items() if k not in {"started_at", "completed_at"}})
            return result
        except Exception:
            await state.insert_one({**result, "status": "FAILED", "completed_at": datetime.now(timezone.utc)})
            await self.audit.log(action="LEGACY_DIRECT_ACCESS_MIGRATION_FAILED", actor_id=actor_id, metadata={"run_id": run_id, "snapshot_id": snapshot.snapshot_id})
            raise
