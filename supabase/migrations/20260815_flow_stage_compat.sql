-- Compatibility migration for deployments where embassy flow v2 was not applied.
-- Safe to run repeatedly.

alter table public.embassy_requests
    add column if not exists flow_stage text not null default 'created';

create index if not exists idx_embassy_requests_flow_stage
    on public.embassy_requests(flow_stage, created_at desc);
