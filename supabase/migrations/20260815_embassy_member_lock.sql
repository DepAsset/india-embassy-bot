-- Preserve the current embassy member registry independently of the legacy Discord access roles.
-- This is a registry lock only: it does NOT remove roles or change Discord permissions.

alter table public.embassy_members
    add column if not exists registry_locked boolean not null default false;

create index if not exists idx_embassy_members_registry_locked
    on public.embassy_members(registry_locked);
