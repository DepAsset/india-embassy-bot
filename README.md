# RAJDOOT

RAJDOOT is the Embassy access and diplomatic management system for the WarEra Discord community.

## Product principles

- Discord is the user interface and access projection layer.
- Supabase PostgreSQL is the source of truth for RAJDOOT state.
- WarEra is the external identity and profile data source.
- Dashboard-first UX. We do not turn every feature into a slash command.
- Every major entity and workflow should be interlinked and navigable.
- Prefer embeds, buttons, select menus, links, and modals/forms when they make an interaction easier.
- Long-running work must acknowledge interactions immediately and provide friendly progress feedback.
- Discord and external API work must be rate-limit-aware, idempotent, and diff-based where possible.
- Important actions are recorded in the database and surfaced through the dedicated Discord Logs channel.
- User-facing wording should feel warm, polished, diplomatic, and joyful without becoming childish or noisy.

## Current build state

The repository has been reset for the new system. The first implementation step is the Supabase PostgreSQL foundation.

## Database

The initial migration is in `supabase/migrations/0001_initial_schema.sql`.

Run the migration in the Supabase SQL Editor before starting the application layer. The schema intentionally follows the data model already established in the project discussion and avoids inventing additional business rules that have not been finalized.

## Planned application layers

```text
Discord UI
    |
    v
Interaction and navigation layer
    |
    v
Domain services
    |
    +---- Supabase PostgreSQL
    |
    +---- WarEra integration
    |
    +---- Discord access projection
```

The application will be built around reusable dashboard components, domain services, persistent request state, access assignments, audit events, and rate-aware Discord workers.
