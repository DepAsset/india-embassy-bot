from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: AsyncConnection | None = None

    async def connect(self) -> None:
        if self._connection is None or self._connection.closed:
            self._connection = await AsyncConnection.connect(
                self._dsn,
                row_factory=dict_row,
            )

    async def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            await self._connection.close()

    async def ping(self) -> None:
        await self.connect()
        assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select 1")
            await cursor.fetchone()

    @asynccontextmanager
    async def transaction(self):
        await self.connect()
        assert self._connection is not None
        async with self._connection.transaction():
            yield self._connection
