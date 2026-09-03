from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class Database:
    """Small async PostgreSQL gateway.

    The bot deliberately uses one connection because the deployment is a single
    worker. It is configured with autocommit so read-only cursors never leave a
    transaction open and block the next interaction. Explicit transaction blocks
    are used only for multi-statement writes.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._connection: AsyncConnection[Any] | None = None

    async def connect(self) -> None:
        if self._connection is None or self._connection.closed:
            self._connection = await AsyncConnection.connect(
                self._dsn,
                row_factory=dict_row,
                autocommit=True,
                connect_timeout=10,
                options="-c statement_timeout=10000 -c lock_timeout=3000",
            )

    async def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            await self._connection.close()

    async def ping(self) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select 1")
            await cursor.fetchone()

    async def fetch_active_embassies(self) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select id, country_id, country_name, channel_id, channel_name, category_id, status, display_order from embassies where status = 'active' order by country_name asc")
            return list(await cursor.fetchall())

    async def fetch_all_embassies(self) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select id, country_id, country_name, channel_id, channel_name, category_id, status, display_order from embassies order by status, display_order nulls last, country_name asc")
            return list(await cursor.fetchall())

    async def create_embassy(self, *, country_id: str, country_name: str, channel_id: int, channel_name: str, category_id: int) -> dict[str, Any]:
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute(
                    """
                    insert into embassies (country_id, country_name, channel_id, channel_name, category_id, status)
                    values (%s, %s, %s, %s, %s, 'active')
                    on conflict do nothing
                    returning id, country_id, country_name, channel_id, channel_name, category_id, status, display_order
                    """,
                    (country_id, country_name, channel_id, channel_name, category_id),
                )
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        existing = await self.fetch_active_embassy_by_country(country_id, country_name)
        if existing:
            return existing
        raise RuntimeError("Embassy record creation failed")

    async def fetch_active_embassy_by_country(self, country_id: str | None, country_name: str | None) -> dict[str, Any] | None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            if country_id:
                await cursor.execute("select id, country_id, country_name, channel_id, channel_name, category_id, status, display_order from embassies where status = 'active' and country_id = %s limit 1", (country_id,))
                row = await cursor.fetchone()
                if row:
                    return row
            if country_name:
                await cursor.execute("select id, country_id, country_name, channel_id, channel_name, category_id, status, display_order from embassies where status = 'active' and lower(country_name) = lower(%s) limit 1", (country_name,))
                return await cursor.fetchone()
            return None

    async def fetch_legacy_roles(self) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select role_id, role_name, embassy_id, disposition, notes from embassy_legacy_roles order by role_name asc, role_id asc")
            return list(await cursor.fetchall())

    async def embassy_member_registry_is_frozen(self) -> bool:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select frozen from embassy_member_registry_state where id = 1")
            row = await cursor.fetchone()
            return bool(row and row["frozen"])

    async def freeze_embassy_member_registry(self) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("insert into embassy_member_registry_state (id, frozen, frozen_at) values (1, true, now()) on conflict (id) do update set frozen = true, frozen_at = coalesce(embassy_member_registry_state.frozen_at, now())")

    async def fetch_embassy_member_registry_counts(self) -> dict[str, int]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select count(*)::int as total, count(*) filter (where member_type = 'foreign_diplomat')::int as foreign_diplomats, count(*) filter (where member_type = 'indian_ambassador')::int as indian_ambassadors from embassy_members where active = true")
            row = await cursor.fetchone() or {}
            return {"total": int(row.get("total", 0)), "foreign_diplomats": int(row.get("foreign_diplomats", 0)), "indian_ambassadors": int(row.get("indian_ambassadors", 0))}

    async def fetch_all_active_embassy_members(self) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select em.embassy_id, em.discord_user_id, em.discord_username, em.member_type, e.country_name, e.channel_id from embassy_members em join embassies e on e.id = em.embassy_id where em.active = true and e.status = 'active' order by e.country_name asc, em.member_type asc, em.discord_username asc")
            return list(await cursor.fetchall())

    async def upsert_embassy_member(self, *, embassy_id: str, discord_user_id: str, discord_username: str, member_type: str, embassy_role_id: str) -> bool:
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("insert into embassy_members (embassy_id, discord_user_id, discord_username, member_type, embassy_role_id, active) values (%s::uuid, %s, %s, %s, %s, true) on conflict (embassy_id, discord_user_id) do update set discord_username = excluded.discord_username, member_type = excluded.member_type, embassy_role_id = excluded.embassy_role_id, active = true, updated_at = now() returning (xmax = 0) as inserted", (embassy_id, discord_user_id, discord_username, member_type, embassy_role_id))
                row = await cursor.fetchone()
                return bool(row and row["inserted"])

    async def fetch_embassy_members(self, embassy_id: str) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select id, embassy_id, discord_user_id, discord_username, member_type, embassy_role_id, active, assigned_at, updated_at from embassy_members where embassy_id = %s::uuid and active = true order by member_type asc, discord_username asc", (embassy_id,))
            return list(await cursor.fetchall())

    async def fetch_pending_government_requests(self) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select r.*, e.country_name, e.channel_id, e.channel_name
                from embassy_requests r join embassies e on e.id = r.target_embassy_id
                where r.request_status = 'pending_approval'
                  and r.flow_stage = 'awaiting_government_approval'
                  and e.status = 'active'
                order by r.created_at asc
            """)
            return list(await cursor.fetchall())

    async def fetch_request_statistics(self) -> dict[str, int]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select count(*)::int as total,
                       count(*) filter (where request_status = 'pending_approval')::int as pending,
                       count(*) filter (where request_status = 'approved')::int as approved,
                       count(*) filter (where request_status = 'rejected')::int as rejected,
                       count(*) filter (where verification_status = 'verified')::int as verified
                from embassy_requests
            """)
            row = await cursor.fetchone() or {}
            return {k: int(row.get(k, 0)) for k in ("total", "pending", "approved", "rejected", "verified")}

    async def fetch_recent_audit_logs(self, limit: int = 15) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        limit = max(1, min(int(limit), 50))
        async with self._connection.cursor() as cursor:
            await cursor.execute("select actor_discord_id, action, target_type, target_id, embassy_id, result, metadata, created_at from audit_logs order by created_at desc limit %s", (limit,))
            return list(await cursor.fetchall())

    async def fetch_user_audit_logs(self, user_id: int, limit: int = 15) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        limit = max(1, min(int(limit), 50))
        async with self._connection.cursor() as cursor:
            await cursor.execute("select actor_discord_id, action, target_type, target_id, embassy_id, result, metadata, created_at from audit_logs where actor_discord_id = %s order by created_at desc limit %s", (user_id, limit))
            return list(await cursor.fetchall())

    async def update_embassy_layout_state(self, updates: list[tuple[str, int, int, int]]) -> None:
        if not updates: return
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.executemany("update embassies set category_id = %s, channel_id = %s, display_order = %s, updated_at = now() where id = %s::uuid", [(category_id, channel_id, display_order, embassy_id) for embassy_id, category_id, channel_id, display_order in updates])

    async def fetch_embassy(self, embassy_id: str) -> dict[str, Any] | None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select id, country_id, country_name, channel_id, channel_name, category_id, status, display_order from embassies where id = %s::uuid", (embassy_id,))
            return await cursor.fetchone()

    async def fetch_discord_configuration(self, guild_id: int) -> dict[str, Any] | None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select * from discord_configuration where guild_id = %s", (guild_id,))
            return await cursor.fetchone()

    async def upsert_discord_configuration(self, *, guild_id: int, request_category_id: int | None = None, logs_channel_id: int | None = None, government_dashboard_channel_id: int | None = None, government_dashboard_message_id: int | None = None, diplomat_dashboard_channel_id: int | None = None, diplomat_dashboard_message_id: int | None = None, verification_dashboard_channel_id: int | None = None, verification_dashboard_message_id: int | None = None) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    insert into discord_configuration (guild_id, request_category_id, logs_channel_id,
                        government_dashboard_channel_id, government_dashboard_message_id,
                        diplomat_dashboard_channel_id, diplomat_dashboard_message_id,
                        verification_dashboard_channel_id, verification_dashboard_message_id)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (guild_id) do update set request_category_id = excluded.request_category_id,
                        logs_channel_id = excluded.logs_channel_id,
                        government_dashboard_channel_id = excluded.government_dashboard_channel_id,
                        government_dashboard_message_id = excluded.government_dashboard_message_id,
                        diplomat_dashboard_channel_id = excluded.diplomat_dashboard_channel_id,
                        diplomat_dashboard_message_id = excluded.diplomat_dashboard_message_id,
                        verification_dashboard_channel_id = excluded.verification_dashboard_channel_id,
                        verification_dashboard_message_id = excluded.verification_dashboard_message_id,
                        updated_at = now()
                """, (guild_id, request_category_id, logs_channel_id, government_dashboard_channel_id, government_dashboard_message_id, diplomat_dashboard_channel_id, diplomat_dashboard_message_id, verification_dashboard_channel_id, verification_dashboard_message_id))

    async def create_embassy_request(self, *, applicant_discord_id: int, embassy_id: str, warera_user_id: str | None = None, profile_url: str | None = None) -> dict[str, Any]:
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("insert into embassy_requests (applicant_discord_id, warera_user_id, profile_url, embassy_id, verification_status, request_status) values (%s, %s, %s, %s::uuid, 'pending', 'created') returning *", (applicant_discord_id, warera_user_id, profile_url, embassy_id))
                row = await cursor.fetchone(); assert row is not None
                return dict(row)

    async def fetch_embassy_request(self, request_id: str) -> dict[str, Any] | None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select * from embassy_requests where id = %s::uuid", (request_id,))
            return await cursor.fetchone()

    async def fetch_latest_request_for_applicant(self, applicant_discord_id: int) -> dict[str, Any] | None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("select * from embassy_requests where applicant_discord_id = %s order by created_at desc limit 1", (applicant_discord_id,))
            return await cursor.fetchone()

    async def fetch_pending_requests_for_member(self, discord_user_id: int) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select r.*, e.country_name, e.channel_id, e.channel_name
                from embassy_requests r join embassies e on e.id = r.target_embassy_id
                where r.request_status = 'pending_approval' and e.status = 'active'
                  and r.flow_stage = 'awaiting_embassy_approval'
                  and exists (select 1 from embassy_members em where em.embassy_id = r.target_embassy_id and em.discord_user_id = %s and em.active = true and em.member_type = 'foreign_diplomat')
                order by r.created_at asc
            """, (discord_user_id,))
            return list(await cursor.fetchall())

    async def fetch_active_embassy_diplomats(self, embassy_id: str) -> list[dict[str, Any]]:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                select distinct a.user_discord_id, e.country_name, a.assignment_type
                from embassy_assignments a join embassies e on e.id = a.embassy_id
                where a.embassy_id = %s::uuid and a.status = 'active'
                  and a.assignment_type = 'foreign_diplomat' and e.status = 'active'
                order by a.user_discord_id
            """, (embassy_id,))
            return list(await cursor.fetchall())

    async def decide_embassy_request(self, *, request_id: str, actor_discord_id: int, decision: str, assignment_type: str | None = None, reason: str | None = None) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}: raise ValueError("decision must be approved or rejected")
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("select r.*, e.country_name from embassy_requests r join embassies e on e.id = r.target_embassy_id where r.id = %s::uuid for update of r", (request_id,))
                request = await cursor.fetchone()
                if request is None: raise LookupError("Embassy request not found")
                if request["request_status"] != "pending_approval": raise ValueError("Embassy request is no longer awaiting approval")
                if request["flow_stage"] == "awaiting_embassy_approval":
                    await cursor.execute("select 1 from embassy_assignments where embassy_id = %s::uuid and user_discord_id = %s and assignment_type = 'foreign_diplomat' and status = 'active' limit 1", (request["target_embassy_id"], actor_discord_id))
                    if await cursor.fetchone() is None: raise PermissionError("Actor is not an active diplomat in this embassy")
                if decision == "approved":
                    if assignment_type not in {"foreign_diplomat", "indian_ambassador"}: raise ValueError("assignment_type is required for approval")
                    await cursor.execute("insert into embassy_assignments (user_discord_id, embassy_id, assignment_type, status, granted_by_discord_id) values (%s, %s::uuid, %s, 'active', %s) on conflict (user_discord_id, embassy_id) where status = 'active' do update set assignment_type = excluded.assignment_type, granted_by_discord_id = excluded.granted_by_discord_id, granted_at = now(), updated_at = now()", (request["applicant_discord_id"], request["target_embassy_id"], assignment_type, actor_discord_id))
                    request_status = "approved"
                else:
                    request_status = "rejected"
                await cursor.execute("update embassy_requests set request_status = %s, decision_actor_discord_id = %s, decision_reason = %s, decided_at = now(), completed_at = case when %s = 'approved' then now() else completed_at end, updated_at = now() where id = %s::uuid returning *", (request_status, actor_discord_id, reason, request_status, request_id))
                result = await cursor.fetchone(); assert result is not None
                return dict(result)

    async def mark_request_verifying(self, request_id: str) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("update embassy_requests set verification_status = 'verifying', request_status = case when request_status = 'created' then 'verifying' else request_status end, verification_started_at = now(), updated_at = now() where id = %s::uuid", (request_id,))

    async def mark_request_verified(self, request_id: str, *, warera_user_id: str, profile_snapshot: dict[str, Any]) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.transaction():
            async with self._connection.cursor() as cursor:
                await cursor.execute("update embassy_requests set warera_user_id = %s, warera_profile_snapshot = %s::jsonb, verification_status = 'verified', request_status = 'pending_approval', verification_completed_at = now(), last_verification_error = null, updated_at = now() where id = %s::uuid", (warera_user_id, Jsonb(profile_snapshot), request_id))

    async def mark_request_verification_failed(self, request_id: str, reason: str) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("update embassy_requests set verification_status = 'failed', last_verification_error = %s, verification_attempts = least(verification_attempts + 1, verification_max_attempts), updated_at = now() where id = %s::uuid", (reason, request_id))

    async def add_request_event(self, *, request_id: str, event_type: str, actor_discord_id: int | None = None, embassy_id: str | None = None, details: dict[str, Any] | None = None) -> None:
        await self.connect(); assert self._connection is not None
        async with self._connection.cursor() as cursor:
            await cursor.execute("insert into request_events (request_id, event_type, actor_discord_id, embassy_id, details) values (%s::uuid, %s, %s, %s::uuid, %s::jsonb)", (request_id, event_type, actor_discord_id, embassy_id, Jsonb(details or {})))
