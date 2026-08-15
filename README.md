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

The new Embassy System foundation and first end-to-end access workflow are implemented on the feature branch.

### Implemented chunks

1. Canonical embassy/member registry and legacy-role reconciliation baseline.
2. Supabase-backed embassy access requests and durable request state.
3. WarEra full-profile lookup and company-based OTP verification.
4. Five-attempt verification guard with 30-minute OTP expiry and audit events.
5. Own-country vs other-country embassy routing.
6. Government-official auto-approval for President, Vice President and Minister of Foreign Affairs when requesting their own-country embassy.
7. Pre-approval records that can be consumed automatically by a matching visitor request.
8. Automatic embassy creation/revival path when an own-country embassy does not exist.
9. Persistent embassy approval controls that are re-registered after bot restart.
10. Ambassador/diplomat assignment lifecycle, direct Discord permissions, welcome messages and revocation.
11. Top-level diplomacy commands: `/assignambassador`, `/dismissambassador`, `/removediplomat`, `/listembassies`, `/listdiplomats`, `/diplomatprofile`.
12. Automated Ruff + pytest CI gate.

## Database

The migration chain is in `supabase/migrations/`.

Apply migrations in order in the Supabase SQL Editor before running the application layer.

Important workflow migrations include:

- `20260815_embassy_members.sql`
- `20260815_embassy_request_flow.sql`
- `20260815_embassy_flow_v2.sql`
- `20260815_embassy_request_guard.sql`

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
    +---- Supabase PostgreSQL  <-- source of truth
    |
    +---- WarEra integration   <-- identity/profile/company data
    |
    +---- Discord projection   <-- roles, permissions, channels
```

## Next build chunks

- Visitor access / embassy visit workflow.
- Government Control Center request queue and statistics.
- Diplomat profile dashboard and embassy member management UI.
- Logs/audit dashboard with filtering and request timeline.
- Reconciliation and production hardening.
