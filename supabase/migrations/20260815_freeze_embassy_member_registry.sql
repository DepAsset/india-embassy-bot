-- Make the imported embassy-member registry a one-way, immutable baseline.
-- Multiple legacy Discord roles for one embassy are already merged by
-- (embassy_id, discord_user_id) in embassy_members. No Discord roles are touched.

create table if not exists public.embassy_member_registry_state (
    id smallint primary key check (id = 1),
    frozen boolean not null default false,
    frozen_at timestamptz
);

-- If the 193-member baseline was imported before this state table existed,
-- recognize those existing assignments as the baseline and freeze it.
insert into public.embassy_member_registry_state (id, frozen, frozen_at)
values (
    1,
    exists (select 1 from public.embassy_members limit 1),
    case when exists (select 1 from public.embassy_members limit 1) then now() else null end
)
on conflict (id) do update set
    frozen = case
        when public.embassy_member_registry_state.frozen then true
        when exists (select 1 from public.embassy_members limit 1) then true
        else false
    end,
    frozen_at = case
        when public.embassy_member_registry_state.frozen_at is not null
            then public.embassy_member_registry_state.frozen_at
        when exists (select 1 from public.embassy_members limit 1)
            then now()
        else null
    end;

create index if not exists idx_embassy_member_registry_state_frozen
    on public.embassy_member_registry_state(frozen);
