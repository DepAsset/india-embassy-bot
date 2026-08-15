-- Canonical embassy member registry.
-- IMPORTANT: embassy IDs are UUIDs in the canonical schema.
create table if not exists public.embassy_members (
    id uuid primary key default gen_random_uuid(),
    embassy_id uuid not null references public.embassies(id) on delete cascade,
    discord_user_id text not null,
    discord_username text,
    member_type text not null check (member_type in ('foreign_diplomat', 'indian_ambassador')),
    embassy_role_id text,
    active boolean not null default true,
    assigned_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (embassy_id, discord_user_id)
);

create index if not exists idx_embassy_members_user
    on public.embassy_members(discord_user_id);
create index if not exists idx_embassy_members_embassy
    on public.embassy_members(embassy_id);
create index if not exists idx_embassy_members_type
    on public.embassy_members(member_type);
create unique index if not exists uq_embassy_members_active_role_assignment
    on public.embassy_members(embassy_id, discord_user_id)
    where active = true;

drop trigger if exists embassy_members_set_updated_at on public.embassy_members;
create trigger embassy_members_set_updated_at
before update on public.embassy_members
for each row execute function public.set_updated_at();
