# Supabase setup

1. Create a Supabase project.
2. Open the SQL Editor.
3. Run `migrations/0001_initial_schema.sql` once.
4. Confirm these tables exist:
   - `embassies`
   - `embassy_requests`
   - `embassy_assignments`
   - `preapprovals`
   - `request_events`
   - `audit_logs`
   - `discord_configuration`
5. Copy the PostgreSQL connection string for the application and use it as `DATABASE_URL`.

The application does not use Supabase Auth. Discord remains the identity layer for RAJDOOT.

Do not insert production embassy data yet. We will load and verify the embassy registry from the supplied legacy data in a dedicated migration step after the schema is confirmed.
