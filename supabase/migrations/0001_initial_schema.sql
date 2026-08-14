create extension if not exists pgcrypto;

create table if not exists embassies (
    id uuid primary key default gen_random_uuid(),
    country_id text not null,
    country_name text not null,
    channel_id bigint unique,
    channel_name text,
    category_id bigint,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_embassies_country_id
    on embassies (country_id);

create index if not exists idx_embassies_status
    on embassies (status);

create unique index if not exists uq_embassies_active_country
    on embassies (country_id)
    where status = 'active';

create table if not exists embassy_requests (
    id uuid primary key default gen_random_uuid(),
    applicant_discord_id bigint not null,
    warera_user_id text,
    profile_url text,
    country_id text,
    embassy_id uuid references embassies(id) on delete set null,
    verification_status text not null default 'pending',
    government_status text,
    preapproval_status text,
    request_status text not null default 'created',
    verification_attempts integer not null default 0,
    verification_max_attempts integer not null default 5,
    otp_hash text,
    otp_created_at timestamptz,
    otp_expires_at timestamptz,
    warera_profile_snapshot jsonb,
    discord_thread_id bigint,
    discord_request_message_id bigint,
    decision_actor_discord_id bigint,
    decision_reason text,
    submitted_at timestamptz not null default now(),
    decided_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint embassy_requests_attempts_valid
        check (verification_attempts between 0 and verification_max_attempts),
    constraint embassy_requests_max_attempts_valid
        check (verification_max_attempts > 0)
);

create index if not exists idx_embassy_requests_applicant
    on embassy_requests (applicant_discord_id);

create index if not exists idx_embassy_requests_embassy_status
    on embassy_requests (embassy_id, request_status);

create index if not exists idx_embassy_requests_status
    on embassy_requests (request_status);

create index if not exists idx_embassy_requests_warera_user
    on embassy_requests (warera_user_id);

create unique index if not exists uq_open_request_per_applicant_embassy
    on embassy_requests (applicant_discord_id, embassy_id)
    where embassy_id is not null
      and request_status in ('created', 'verifying', 'verified', 'pending_approval');

create table if not exists embassy_assignments (
    id uuid primary key default gen_random_uuid(),
    user_discord_id bigint not null,
    embassy_id uuid not null references embassies(id) on delete cascade,
    assignment_type text not null,
    status text not null default 'active',
    granted_by_discord_id bigint,
    granted_at timestamptz not null default now(),
    revoked_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_embassy_assignments_user
    on embassy_assignments (user_discord_id);

create index if not exists idx_embassy_assignments_embassy
    on embassy_assignments (embassy_id);

create index if not exists idx_embassy_assignments_status
    on embassy_assignments (status);

create unique index if not exists uq_active_embassy_assignment
    on embassy_assignments (user_discord_id, embassy_id)
    where status = 'active';

create table if not exists preapprovals (
    id uuid primary key default gen_random_uuid(),
    embassy_id uuid not null references embassies(id) on delete cascade,
    diplomat_discord_id bigint not null,
    visitor_warera_id text not null,
    visitor_profile_url text,
    status text not null default 'active',
    reason text,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    used_at timestamptz,
    updated_at timestamptz not null default now()
);

create index if not exists idx_preapprovals_embassy
    on preapprovals (embassy_id);

create index if not exists idx_preapprovals_diplomat
    on preapprovals (diplomat_discord_id);

create index if not exists idx_preapprovals_visitor
    on preapprovals (visitor_warera_id);

create index if not exists idx_preapprovals_active_lookup
    on preapprovals (embassy_id, visitor_warera_id, status, expires_at);

create table if not exists request_events (
    id uuid primary key default gen_random_uuid(),
    request_id uuid not null references embassy_requests(id) on delete cascade,
    event_type text not null,
    actor_discord_id bigint,
    embassy_id uuid references embassies(id) on delete set null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_request_events_request
    on request_events (request_id, created_at);

create index if not exists idx_request_events_type
    on request_events (event_type, created_at);

create table if not exists audit_logs (
    id uuid primary key default gen_random_uuid(),
    actor_discord_id bigint,
    action text not null,
    target_type text,
    target_id text,
    embassy_id uuid references embassies(id) on delete set null,
    result text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_audit_logs_created_at
    on audit_logs (created_at desc);

create index if not exists idx_audit_logs_actor
    on audit_logs (actor_discord_id, created_at desc);

create index if not exists idx_audit_logs_target
    on audit_logs (target_type, target_id, created_at desc);

create index if not exists idx_audit_logs_embassy
    on audit_logs (embassy_id, created_at desc);

create table if not exists discord_configuration (
    id uuid primary key default gen_random_uuid(),
    guild_id bigint not null unique,
    request_category_id bigint,
    logs_channel_id bigint,
    government_dashboard_channel_id bigint,
    government_dashboard_message_id bigint,
    diplomat_dashboard_channel_id bigint,
    diplomat_dashboard_message_id bigint,
    updated_at timestamptz not null default now()
);

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists embassies_set_updated_at on embassies;
create trigger embassies_set_updated_at
before update on embassies
for each row execute function set_updated_at();

drop trigger if exists embassy_requests_set_updated_at on embassy_requests;
create trigger embassy_requests_set_updated_at
before update on embassy_requests
for each row execute function set_updated_at();

drop trigger if exists embassy_assignments_set_updated_at on embassy_assignments;
create trigger embassy_assignments_set_updated_at
before update on embassy_assignments
for each row execute function set_updated_at();

drop trigger if exists preapprovals_set_updated_at on preapprovals;
create trigger preapprovals_set_updated_at
before update on preapprovals
for each row execute function set_updated_at();

drop trigger if exists discord_configuration_set_updated_at on discord_configuration;
create trigger discord_configuration_set_updated_at
before update on discord_configuration
for each row execute function set_updated_at();
