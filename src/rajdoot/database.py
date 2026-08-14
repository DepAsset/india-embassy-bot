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
            await cursor.execute(
                """
                select id, country_id, country_name, channel_id, channel_name,
                       category_id, status, display_order
                from embassies
                where status = 'active'
                order by country_name asc
                """
            )
            return list(await cursor.fetchall())

    async def fetch_embassy(self, embassy_id: str) -> dict[str, Any] | None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """
                select id, country_id, country_name, channel_id, channel_name,
                       category_id, status, display_order
                from embassies
                where id = %s
                """,
                (embassy_id,),
            )
            return await cursor.fetchone()

    async def update_embassy_layout_state(
        self,
        updates: list[tuple[str, int, int, int]],
    ) -> None:
        """Persist desired category and channel ordering after Discord reconciliation.

        Each tuple is (embassy_id, category_id, channel_id, display_order).
        The update is transactional so the database never contains a partially
        written layout after a successful Discord synchronization.
        """
        if not updates:
            return
        await self.connect()
        assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.executemany(
                    """
                    update embassies
                    set category_id = %s,
                        channel_id = %s,
                        display_order = %s,
                        updated_at = now()
                    where id = %s
                    """,
                    [
                        (category_id, channel_id, display_order, embassy_id)
                        for embassy_id, category_id, channel_id, display_order in updates
                    ],
                )

    async def fetch_discord_configuration(self, guild_id: int) -> dict[str, Any] | None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "select * from discord_configuration where guild_id = %s",
                (guild_id,),
            )
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
                await cursor.execute(
                    """
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
                    """,
                    (
                        guild_id,
                        request_category_id,
                        logs_channel_id,
                        government_dashboard_channel_id,
                        government_dashboard_message_id,
                        diplomat_dashboard_channel_id,
                        diplomat_dashboard_message_id,
                    ),
                )
