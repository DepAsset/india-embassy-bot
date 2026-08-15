-- Race-safe duplicate protection for the new request-first workflow.
create unique index if not exists uq_open_embassy_request_per_applicant
    on public.embassy_requests(applicant_discord_id)
    where request_status in ('created', 'verifying', 'pending_approval');

create index if not exists idx_embassy_requests_thread
    on public.embassy_requests(request_thread_id)
    where request_thread_id is not null;

create index if not exists idx_embassy_requests_approval_message
    on public.embassy_requests(approval_message_id)
    where approval_message_id is not null;
