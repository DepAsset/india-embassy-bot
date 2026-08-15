from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: AsyncConnection[Any] | None = None

    async def connect(self) -> None:
        if self._connection is None or self._connection.closed:
            self._connection = await AsyncConnection.connect(self._dsn, row_factory=dict_row)

    async def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            await self._connection.close()

    async def ping(self) -> None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select 1")
            await cursor.fetchone()

    async def fetch_active_embassies(self) -> list[dict[str, Any]]:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select id, country_id, country_name, channel_id, channel_name,
                       category_id, status, display_order
                from embassies where status = 'active'
                order by country_name asc
            """)
            return list(await cursor.fetchall())

    async def fetch_all_embassies(self) -> list[dict[str, Any]]:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select id, country_id, country_name, channel_id, channel_name,
                       category_id, status, display_order
                from embassies
                order by status, display_order nulls last, country_name asc
            """)
            return list(await cursor.fetchall())

    async def fetch_legacy_roles(self) -> list[dict[str, Any]]:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select role_id, role_name, embassy_id, disposition, notes
                from embassy_legacy_roles
                order by role_name asc, role_id asc
            """)
            return list(await cursor.fetchall())

    async def embassy_member_registry_is_frozen(self) -> bool:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select frozen
                from embassy_member_registry_state
                where id = 1
            """)
            row = await cursor.fetchone()
            return bool(row and row["frozen"])

    async def freeze_embassy_member_registry(self) -> None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    insert into embassy_member_registry_state (id, frozen, frozen_at)
                    values (1, true, now())
                    on conflict (id) do update set
                        frozen = true,
                        frozen_at = coalesce(embassy_member_registry_state.frozen_at, now())
                """)

    async def fetch_embassy_member_registry_counts(self) -> dict[str, int]:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select
                    count(*)::int as total,
                    count(*) filter (where member_type = 'foreign_diplomat')::int as foreign_diplomats,
                    count(*) filter (where member_type = 'indian_ambassador')::int as indian_ambassadors
                from embassy_members
                where active = true
            """)
            row = await cursor.fetchone() or {}
            return {
                "total": int(row.get("total", 0)),
                "foreign_diplomats": int(row.get("foreign_diplomats", 0)),
                "indian_ambassadors": int(row.get("indian_ambassadors", 0)),
            }

    async def upsert_embassy_member(
        self,
        *,
        embassy_id: str,
        discord_user_id: str,
        discord_username: str,
        member_type: str,
        embassy_role_id: str,
    ) -> bool:
        """Insert/update an embassy assignment before the registry is frozen."""
        await self.connect()
        assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    insert into embassy_members (
                        embassy_id, discord_user_id, discord_username,
                        member_type, embassy_role_id, active
                    ) values (%s::uuid, %s, %s, %s, %s, true)
                    on conflict (embassy_id, discord_user_id) do update set
                        discord_username = excluded.discord_username,
                        member_type = excluded.member_type,
                        embassy_role_id = excluded.embassy_role_id,
                        active = true,
                        updated_at = now()
                    returning (xmax = 0) as inserted
                """, (
                    embassy_id, discord_user_id, discord_username,
                    member_type, embassy_role_id,
                ))
                row = await cursor.fetchone()
                return bool(row and row["inserted"])

    async def fetch_embassy_members(self, embassy_id: str) -> list[dict[str, Any]]:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select id, embassy_id, discord_user_id, discord_username,
                       member_type, embassy_role_id, active, assigned_at, updated_at
                from embassy_members
                where embassy_id = %s::uuid and active = true
                order by member_type asc, discord_username asc
            """, (embassy_id,))
            return list(await cursor.fetchall())

    async def update_embassy_layout_state(
        self,
        updates: list[tuple[str, int, int, int]],
    ) -> None:
        """Persist desired category and channel ordering after Discord reconciliation."""
        if not updates:
            return
        await self.connect()
        assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.executemany("""
                    update embassies
                    set category_id = %s, channel_id = %s,
                        display_order = %s, updated_at = now()
                    where id = %s::uuid
                """, [
                    (category_id, channel_id, display_order, embassy_id)
                    for embassy_id, category_id, channel_id, display_order in updates
                ])

    async def fetch_embassy(self, embassy_id: str) -> dict[str, Any] | None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select id, country_id, country_name, channel_id, channel_name,
                       category_id, status, display_order
                from embassies where id = %s::uuid
            """, (embassy_id,))
            return await cursor.fetchone()

    async def fetch_discord_configuration(self, guild_id: int) -> dict[str, Any] | None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select * from discord_configuration where guild_id = %s", (guild_id,))
            return await cursor.fetchone()

    async def upsert_discord_configuration(
        self,
        *,
        guild_id: int,
        request_category_id: int | None = None,
        logs_channel_id: int | None = None,
        government_dashboard_channel_id: int | None = None,
        government_dashboard_message_id: int | None = None,
        diplomat_dashboard_channel_id: int | None = None,
        diplomat_dashboard_message_id: int | None = None,
    ) -> None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    insert into discord_configuration (
                        guild_id, request_category_id, logs_channel_id,
                        government_dashboard_channel_id, government_dashboard_message_id,
                        diplomat_dashboard_channel_id, diplomat_dashboard_message_id
                    ) values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (guild_id) do update set
                        request_category_id = excluded.request_category_id,
                        logs_channel_id = excluded.logs_channel_id,
                        government_dashboard_channel_id = excluded.government_dashboard_channel_id,
                        government_dashboard_message_id = excluded.government_dashboard_message_id,
                        diplomat_dashboard_channel_id = excluded.diplomat_dashboard_channel_id,
                        diplomat_dashboard_message_id = excluded.diplomat_dashboard_message_id,
                        updated_at = now()
                """, (
                    guild_id, request_category_id, logs_channel_id,
                    government_dashboard_channel_id, government_dashboard_message_id,
                    diplomat_dashboard_channel_id, diplomat_dashboard_message_id,
                ))
