-- Complete the durable verification state used by WorkflowStore.
-- These columns were added to the production database during the initial
-- rollout; keep them in the repository migration chain so fresh environments
-- receive the same schema.

alter table public.embassy_requests
    add column if not exists verification_started_at timestamptz,
    add column if not exists verification_completed_at timestamptz,
    add column if not exists last_verification_error text;

create index if not exists idx_embassy_requests_verification_state
    on public.embassy_requests(verification_status, updated_at desc);
