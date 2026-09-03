from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from rajdoot.database import Database


class WorkflowStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def _connection(self):
        await self.database.connect()
        connection = self.database._connection
        if connection is None: raise RuntimeError("Database connection is unavailable")
        return connection

    async def set_flow_state(self, request_id: str, stage: str, **fields: Any) -> None:
        connection = await self._connection()
        allowed = {"warera_user_id", "warera_profile_snapshot", "government_position", "government_country_id", "government_auto_approved", "request_thread_id", "approval_message_id", "request_log_message_id", "target_country_id", "target_embassy_id", "preapproval_id", "verification_status", "request_status", "verification_started_at", "verification_completed_at", "last_verification_error"}
        updates, values = ["flow_stage = %s", "updated_at = now()"], [stage]
        for key, value in fields.items():
            if key not in allowed: raise ValueError(f"Unsupported workflow field: {key}")
            if key == "warera_profile_snapshot": updates.append(f"{key} = %s::jsonb"); values.append(Jsonb(value or {}))
            elif key in {"target_embassy_id", "preapproval_id"}: updates.append(f"{key} = %s::uuid"); values.append(value)
            else: updates.append(f"{key} = %s"); values.append(value)
        values.append(request_id)
        async with connection.transaction():
            async with connection.cursor() as cursor: await cursor.execute(f"update embassy_requests set {', '.join(updates)} where id = %s::uuid", values)

    async def create_request(self, applicant_id: int) -> dict[str, Any]:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute("insert into embassy_requests (applicant_discord_id, verification_status, request_status, flow_stage) values (%s, 'pending', 'created', 'profile_pending') returning *", (applicant_id,))
                row = await cursor.fetchone()
                if row is None: raise RuntimeError("Request creation failed")
                return dict(row)

    async def fetch_request(self, request_id: str) -> dict[str, Any] | None:
        connection = await self._connection()
        async with connection.cursor() as cursor: await cursor.execute("select * from embassy_requests where id = %s::uuid", (request_id,)); return await cursor.fetchone()

    async def fetch_open_for_applicant(self, applicant_id: int) -> dict[str, Any] | None:
        connection = await self._connection()
        async with connection.cursor() as cursor:
            await cursor.execute("select * from embassy_requests where applicant_discord_id = %s and request_status not in ('approved', 'rejected', 'failed', 'cancelled') order by created_at desc limit 1", (applicant_id,)); return await cursor.fetchone()

    async def fetch_latest_for_applicant(self, applicant_id: int) -> dict[str, Any] | None:
        connection = await self._connection()
        async with connection.cursor() as cursor: await cursor.execute("select * from embassy_requests where applicant_discord_id = %s order by created_at desc limit 1", (applicant_id,)); return await cursor.fetchone()

    async def issue_otp(self, request_id: str, otp_hash: str) -> dict[str, Any] | None:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute("update embassy_requests set otp_hash = %s, otp_created_at = now(), otp_expires_at = now() + interval '30 minutes', verification_attempts = 0, verification_status = 'verifying', request_status = 'verifying', flow_stage = 'company_verification', updated_at = now() where id = %s::uuid and request_status not in ('approved', 'rejected', 'failed', 'cancelled') returning *", (otp_hash, request_id)); row = await cursor.fetchone(); return dict(row) if row else None

    async def record_company_attempt(self, request_id: str, company_match: bool) -> tuple[str, dict[str, Any] | None]:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute("set local lock_timeout = '3s'"); await cursor.execute("set local statement_timeout = '8s'"); await cursor.execute("select * from embassy_requests where id = %s::uuid", (request_id,)); row = await cursor.fetchone()
                if row is None: return "missing", None
                if row["request_status"] in {"failed", "approved", "rejected", "cancelled"}: return "closed", dict(row)
                expires = row.get("otp_expires_at")
                if expires and expires < datetime.now(timezone.utc): return "expired", dict(row)
                attempts, maximum = int(row.get("verification_attempts") or 0) + 1, int(row.get("verification_max_attempts") or 5)
                if company_match:
                    await cursor.execute("update embassy_requests set verification_attempts = %s, verification_status = 'verified', request_status = 'created', flow_stage = 'embassy_selection', verification_completed_at = now(), last_verification_error = null, updated_at = now() where id = %s::uuid returning *", (attempts, request_id)); result = await cursor.fetchone(); return "verified", dict(result) if result else None
                if attempts >= maximum:
                    await cursor.execute("update embassy_requests set verification_attempts = %s, verification_status = 'failed', request_status = 'failed', flow_stage = 'verification_failed', last_verification_error = 'Maximum company verification attempts reached', updated_at = now() where id = %s::uuid returning *", (attempts, request_id)); result = await cursor.fetchone(); return "max_attempts", dict(result) if result else None
                await cursor.execute("update embassy_requests set verification_attempts = %s, last_verification_error = 'Company OTP not found', updated_at = now() where id = %s::uuid returning *", (attempts, request_id)); result = await cursor.fetchone(); return "invalid", dict(result) if result else None

    async def find_preapproval(self, embassy_id: str, warera_user_id: str) -> dict[str, Any] | None:
        connection = await self._connection()
        async with connection.cursor() as cursor: await cursor.execute("select * from preapprovals where embassy_id = %s::uuid and visitor_warera_id = %s and status = 'active' and (expires_at is null or expires_at > now()) order by created_at desc limit 1", (embassy_id, warera_user_id)); return await cursor.fetchone()

    async def consume_preapproval(self, preapproval_id: str, request_id: str) -> bool:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor: await cursor.execute("update preapprovals set status = 'used', used_at = now(), used_request_id = %s::uuid, updated_at = now() where id = %s::uuid and status = 'active' and (expires_at is null or expires_at > now()) returning id", (request_id, preapproval_id)); return await cursor.fetchone() is not None

    async def create_preapproval(self, *, embassy_id: str, diplomat_discord_id: int, visitor_warera_id: str, visitor_profile_url: str | None, expires_at: datetime | None, reason: str | None) -> dict[str, Any]:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor: await cursor.execute("insert into preapprovals (embassy_id, diplomat_discord_id, visitor_warera_id, visitor_profile_url, reason, expires_at) values (%s::uuid, %s, %s, %s, %s, %s) returning *", (embassy_id, diplomat_discord_id, visitor_warera_id, visitor_profile_url, reason, expires_at)); row = await cursor.fetchone(); assert row is not None; return dict(row)

    async def active_assignments_for_user(self, discord_user_id: int) -> list[dict[str, Any]]:
        connection = await self._connection()
        async with connection.cursor() as cursor: await cursor.execute("select a.*, e.country_name, e.channel_id, e.channel_name from embassy_assignments a join embassies e on e.id = a.embassy_id where a.user_discord_id = %s and a.status = 'active' and e.status = 'active' order by e.country_name asc", (discord_user_id,)); return list(await cursor.fetchall())

    async def upsert_assignment(self, *, user_discord_id: int, embassy_id: str, assignment_type: str, granted_by: int | None) -> dict[str, Any]:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute("insert into embassy_assignments (user_discord_id, embassy_id, assignment_type, status, granted_by_discord_id) values (%s, %s::uuid, %s, 'active', %s) on conflict (user_discord_id, embassy_id) where status = 'active' do update set assignment_type = excluded.assignment_type, granted_by_discord_id = excluded.granted_by_discord_id, granted_at = now(), updated_at = now() returning *", (user_discord_id, embassy_id, assignment_type, granted_by)); row = await cursor.fetchone(); assert row is not None
                await cursor.execute("insert into embassy_members (embassy_id, discord_user_id, discord_username, member_type, active) values (%s::uuid, %s, %s, %s, true) on conflict (embassy_id, discord_user_id) do update set member_type = excluded.member_type, active = true, updated_at = now()", (embassy_id, str(user_discord_id), str(user_discord_id), assignment_type))
                return dict(row)

    async def revoke_assignment(self, user_discord_id: int, embassy_id: str, actor: int) -> bool:
        connection = await self._connection()
        async with connection.transaction():
            async with connection.cursor() as cursor:
                await cursor.execute("update embassy_assignments set status = 'revoked', revoked_at = now(), updated_at = now() where user_discord_id = %s and embassy_id = %s::uuid and status = 'active' returning id", (user_discord_id, embassy_id)); changed = await cursor.fetchone() is not None
                if changed: await cursor.execute("update embassy_members set active = false, updated_at = now() where embassy_id = %s::uuid and discord_user_id = %s and not exists (select 1 from embassy_assignments where embassy_id = %s::uuid and user_discord_id = %s and status = 'active')", (embassy_id, str(user_discord_id), embassy_id, user_discord_id))
                return changed

    async def active_embassy_members(self, embassy_id: str) -> list[dict[str, Any]]:
        connection = await self._connection()
        async with connection.cursor() as cursor: await cursor.execute("select * from embassy_members where embassy_id = %s::uuid and active = true order by discord_username asc", (embassy_id,)); return list(await cursor.fetchall())

    async def active_embassy_diplomats(self, embassy_id: str) -> list[dict[str, Any]]:
        return await self.database.fetch_active_embassy_diplomats(embassy_id)

    async def log_audit(self, *, actor: int | None, action: str, target_type: str | None, target_id: str | None, embassy_id: str | None, result: str | None, metadata: dict[str, Any] | None = None) -> None:
        connection = await self._connection()
        async with connection.cursor() as cursor: await cursor.execute("insert into audit_logs (actor_discord_id, action, target_type, target_id, embassy_id, result, metadata) values (%s, %s, %s, %s, %s::uuid, %s, %s::jsonb)", (actor, action, target_type, target_id, embassy_id, result, Jsonb(metadata or {})))
