from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import discord

from core.audit import AuditLogger
from core.database import Database
from embassy.registry import Embassy, EmbassyRegistry
from .snapshot import MigrationSnapshotService

# Bump this when the legacy Embassy mapping seed changes. MongoDB keeps the
# previous migration record and the new version gets its own safety snapshot.
MIGRATION_ID = "legacy_embassy_channels_v2"
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "legacy_embassies.tsv"


def _country_name(source_name: str) -> str:
    value = source_name.removesuffix("-embassy").replace("-", " ").strip()
    return value.title()


def _read_seed() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in SEED_PATH.read_text(encoding="utf-8").splitlines():
        if not raw or raw.startswith("#"):
            continue
        embassy_id, channel_id, role_id, category_id, active, source_name = raw.split("|", 5)
        rows.append({
            "embassy_id": embassy_id,
            "channel_id": int(channel_id),
            "access_role_id": int(role_id) if role_id else None,
            "category_id": int(category_id) if category_id else None,
            "active": active == "1",
            "source_name": source_name,
        })
    return rows


async def seed_legacy_embassies(database: Database, guild: discord.Guild) -> dict[str, int]:
    state = database.collection("migration_state")
    if await state.find_one({"migration_id": MIGRATION_ID}):
        return {"status": 0, "inserted": 0, "updated": 0, "missing_channels": 0}

    registry = EmbassyRegistry(database)
    snapshots = MigrationSnapshotService(database)
    audit = AuditLogger(database)

    existing = await database.collection("embassies").find({}).to_list(length=None)
    snapshot = await snapshots.create_snapshot(
        created_by=guild.me.id if guild.me else guild.owner_id or 0,
        role_memberships=[],
        embassy_mappings=existing,
    )

    inserted = updated = missing_channels = 0
    for row in _read_seed():
        channel = guild.get_channel(int(row["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            missing_channels += 1

        current = await registry.get_by_id(str(row["embassy_id"]))
        embassy = Embassy(
            embassy_id=str(row["embassy_id"]),
            country_key=str(row["embassy_id"]),
            country_name=_country_name(str(row["source_name"])),
            channel_id=int(row["channel_id"]),
            access_role_id=row["access_role_id"],
            category_id=row["category_id"],
            active=bool(row["active"]),
            archived_at=None if bool(row["active"]) else datetime.now(timezone.utc),
        )
        await registry.upsert(embassy)
        if current is None:
            inserted += 1
        else:
            updated += 1

    await state.insert_one({
        "migration_id": MIGRATION_ID,
        "snapshot_id": snapshot.snapshot_id,
        "completed_at": datetime.now(timezone.utc),
        "inserted": inserted,
        "updated": updated,
        "missing_channels": missing_channels,
    })
    await audit.log(
        action="LEGACY_EMBASSY_SEED_COMPLETED",
        actor_id=guild.me.id if guild.me else guild.owner_id or 0,
        metadata={
            "migration_id": MIGRATION_ID,
            "snapshot_id": snapshot.snapshot_id,
            "inserted": inserted,
            "updated": updated,
            "missing_channels": missing_channels,
        },
    )
    return {
        "status": 1,
        "inserted": inserted,
        "updated": updated,
        "missing_channels": missing_channels,
    }
