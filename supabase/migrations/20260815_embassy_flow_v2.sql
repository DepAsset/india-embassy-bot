-- Embassy System v2: durable workflow state for OTP/company verification,
-- embassy routing, government-official auto approval and long-lived Discord actions.

alter table public.embassy_requests
    add column if not exists flow_stage text not null default 'created',
    add column if not exists government_position text,
    add column if not exists government_country_id text,
    add column if not exists government_auto_approved boolean not null default false,
    add column if not exists request_thread_id bigint,
    add column if not exists approval_message_id bigint,
    add column if not exists request_log_message_id bigint,
    add column if not exists target_country_id text,
    add column if not exists target_embassy_id uuid references public.embassies(id) on delete set null,
    add column if not exists preapproval_id uuid references public.preapprovals(id) on delete set null;

create index if not exists idx_embassy_requests_flow_stage
    on public.embassy_requests(flow_stage, created_at desc);
create index if not exists idx_embassy_requests_target_embassy
    on public.embassy_requests(target_embassy_id, request_status);

alter table public.preapprovals
    add column if not exists used_request_id uuid references public.embassy_requests(id) on delete set null;

create index if not exists idx_preapprovals_used_request
    on public.preapprovals(used_request_id);

alter table public.discord_configuration
    add column if not exists request_channel_id bigint,
    add column if not exists foreign_diplomat_role_id bigint,
    add column if not exists ambassador_role_id bigint;
