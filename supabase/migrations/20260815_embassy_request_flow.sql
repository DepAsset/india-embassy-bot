alter table embassy_requests
    add column if not exists verification_started_at timestamptz,
    add column if not exists verification_completed_at timestamptz,
    add column if not exists last_verification_error text;

create index if not exists idx_embassy_requests_verification
    on embassy_requests (verification_status, request_status, created_at desc);

create or replace function set_embassy_request_verifying(p_request_id uuid)
returns void
language sql
as $$
    update embassy_requests
       set verification_status = 'verifying',
           request_status = case when request_status = 'created' then 'verifying' else request_status end,
           verification_started_at = now(),
           updated_at = now()
     where id = p_request_id;
$$;
