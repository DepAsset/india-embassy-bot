# RAJDOOT

RAJDOOT is the Embassy access and diplomatic management system for the WarEra Discord community.

## Architecture

- **Supabase PostgreSQL** is the source of truth for embassy, request, assignment, preapproval and audit state.
- **WarEra** supplies verified player, country, government-position and company data.
- **Discord** is the interaction and access-projection layer.
- Dashboards are fixed/persistent; workflows use private threads, buttons, select menus and modals.

## Embassy Access Request flow

1. Applicant starts from the fixed Verification & Access Request dashboard.
2. RAJDOOT refuses a second unfinished request for the same applicant. The database also enforces this with a partial unique index, so concurrent clicks cannot create two active requests.
3. Applicant submits a WarEra profile.
4. RAJDOOT resolves the WarEra country ID through `country.getCountryById` when the profile does not contain the canonical country name.
5. RAJDOOT issues a six-character company OTP with five attempts and a 30-minute expiry.
6. Company verification resolves company IDs to names concurrently with bounded HTTP timeouts.
7. After verification the applicant chooses their own-country embassy or another embassy. The other-embassy selector is paginated in 25-item Discord select-menu pages.
8. Own-country routing:
   - Existing active embassy + President/VP/MoFA: immediate government-official auto-approval.
   - Existing or newly created embassy with **zero active foreign diplomats**: immediate auto-approval.
   - Existing embassy with one or more active foreign diplomats: approval is sent only to those diplomats.
9. Other-country routing goes to EAM/Admin approval.
10. Valid pre-approval is consumed atomically and grants access without another approval step.
11. Approval decisions are race-safe: the database locks the request row before accepting the first decision.
12. Approved access is stored durably, projected to Discord permissions, and registered in the embassy member registry.
13. Completed or failed requests close/lock their private thread where appropriate.

## Embassy layout

Every newly created embassy triggers a deterministic layout synchronization. Active embassies are sorted alphabetically by country name, letter groups stay together, and each Discord Embassy category never exceeds Discord's 50-channel limit. Embassy categories and channels are renamed/reordered to the canonical plan without evicting unrelated channels or changing legacy access roles.

## Restart guarantees

- Fixed dashboards are singleton messages. RAJDOOT reuses the stored canonical message, repairs stale IDs, and removes duplicate RAJDOOT dashboard copies it can find in the dashboard channel.
- Dashboard reconciliation is serialized so repeated ready events cannot intentionally create competing dashboards.
- Pending request buttons are re-registered after restart for profile submission, company verification, embassy selection and approval.
- Company verification can continue after restart using the stored OTP hash; plaintext OTP is not required.

## Database migrations

Apply every file in `supabase/migrations/` in order. The migration chain contains the canonical embassy registry, durable request workflow, dashboard configuration, member registry and race-safe request guard.

## Configuration

Copy `.env.example` to `.env` and provide the Discord IDs, database URL and WarEra API settings. `REQUEST_CHANNEL_ID` is the parent text channel for private access-request threads. `VERIFICATION_DASHBOARD_CHANNEL_ID` and `VERIFICATION_DASHBOARD_MESSAGE_ID` identify the single fixed verification dashboard.

## Validation

CI compiles the package and runs the deterministic pytest suite. Ruff diagnostics are reported without masking test failures. The test suite covers embassy layout boundaries, canonical channel slugs, country parsing, government-position detection and OTP generation.
