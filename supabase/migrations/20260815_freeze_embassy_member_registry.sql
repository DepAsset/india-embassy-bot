-- Make the imported embassy-member registry a one-way, immutable baseline.
-- Once frozen, later Discord role deletion/removal cannot change the registry.

create table if not exists public.embassy_member_registry_state (
    id smallint primary key check (id = 1),
    frozen boolean not null default false,
    frozen_at timestamptz
);

insert into public.embassy_member_registry_state (id, frozen, frozen_at)
values (
    1,
    exists (select 1 from public.embassy_members limit 1),
    case when exists (select 1 from public.embassy_members limit 1) then now() else null end
)
on conflict (id) do nothing;

create index if not exists idx_embassy_member_registry_state_frozen
    on public.embassy_member_registry_state(frozen);
