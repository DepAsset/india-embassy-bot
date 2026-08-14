alter table embassies
    add column if not exists display_order integer,
    add column if not exists archived_at timestamptz,
    add column if not exists archived_by_discord_id bigint,
    add column if not exists archive_reason text,
    add column if not exists legacy_access_role_id bigint;

update embassies
set display_order = coalesce(display_order, 0)
where display_order is null;

create index if not exists idx_embassies_display_order
    on embassies (status, display_order);

create unique index if not exists uq_embassies_legacy_access_role
    on embassies (legacy_access_role_id)
    where legacy_access_role_id is not null;
