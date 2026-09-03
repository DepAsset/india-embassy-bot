# RAJDOOT

RAJDOOT is the Embassy access and diplomatic management system for the WarEra Discord community.

## Architecture

- **Supabase PostgreSQL** is the source of truth for embassy, request, assignment, preapproval and audit state.
- **WarEra** supplies verified player, country, government-position and company data.
- **Discord** is the interaction and access-projection layer.
- Dashboards are fixed/persistent; workflows use private threads, buttons, select menus and modals.

## Embassy Access Request flow

1. Applicant starts from the fixed Verification & Access Request dashboard.
2. RAJDOOT refuses a second request while an earlier request is still open. A closed/archived request must finish before another can be created.
3. Applicant submits a WarEra profile.
4. RAJDOOT resolves the country ID through `country.getCountryById` when necessary and stores the canonical country name.
5. RAJDOOT issues a six-character company OTP with five attempts and a 30-minute expiry.
6. Company verification resolves all company IDs to their names, concurrently and with bounded API timeouts.
7. After verification the applicant chooses their own-country embassy or another embassy.
8. Own-country routing:
   - Existing active embassy + President/VP/MoFA: immediate government-official auto-approval.
   - Existing/new embassy with **zero active foreign diplomats**: immediate auto-approval.
   - Existing embassy with one or more active foreign diplomats: approval is sent only to those diplomats.
9. Other-country routing always goes to EAM/Admin approval.
10. Pre-approval, when valid and matched to the verified WarEra user, grants access without another approval step.
11. Approved access is stored durably, projected to Discord permissions, and registered in the embassy member registry.
12. Completed requests close and lock their private thread.

## Embassy layout

Every newly created/revived embassy triggers a full deterministic layout reconciliation. Active embassies are sorted alphabetically by country name, letter groups stay together, categories are numbered deterministically, and embassy channels are renamed/reordered to their canonical country slugs. No unrelated channels or legacy access roles are displaced.

## Restart guarantees

- Fixed dashboards are singleton messages: RAJDOOT reuses the canonical message, repairs stale IDs and removes nearby duplicate RAJDOOT copies.
- Dashboard reconciliation is serialized so simultaneous `on_ready` events cannot create duplicates.
- Pending request buttons are re-registered after restart for profile submission, company verification, embassy selection and approval.
- Company verification can continue after restart using the stored OTP hash; the plaintext OTP is not required for verification.

## Database migrations

Apply every file in `supabase/migrations/` in order. The migration chain contains the canonical embassy registry, durable request workflow, dashboard configuration, member registry and race-safe request guard.

## Validation

CI runs Python compilation, Ruff and pytest. The repository includes deterministic tests for embassy layout rules, country parsing, government-position detection and OTP generation.
