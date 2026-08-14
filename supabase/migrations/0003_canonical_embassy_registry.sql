-- RAJDOOT migration 0003: canonical embassy registry and legacy role reconciliation
-- Generated from 123.xlsx using the decisions confirmed in chat.
begin;

alter table embassies add column if not exists country_key text;
alter table embassies alter column country_id drop not null;
create unique index if not exists uq_embassies_country_key on embassies(country_key) where country_key is not null;

create table if not exists embassy_legacy_roles (
    id uuid primary key default gen_random_uuid(),
    embassy_id uuid references embassies(id) on delete set null,
    role_id bigint not null unique,
    role_name text not null,
    disposition text not null default 'mapped',
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_embassy_legacy_roles_embassy on embassy_legacy_roles(embassy_id);
create index if not exists idx_embassy_legacy_roles_disposition on embassy_legacy_roles(disposition);

COMMIT;
