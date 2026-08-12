# India Embassy Bot

Complete Embassy management and access system for the India WarEra Discord server.

## Implemented end-to-end

- Private Embassy application threads
- WarEra profile URL/ID normalization and HTTP adapter
- Canonical WarEra identity and country capture
- Government/special-official detection
- Six-character alphanumeric OTP
- Company-rename OTP verification
- Five-attempt protection and ten-minute cooldown
- Persistent verification state and audit history
- Embassy selection
- Automatic route resolution:
  - valid diplomat pre-approval
  - special official
  - foreign diplomat approval
  - Indian government approval
- First-decision-wins approval records
- Global Foreign Diplomat role
- Global Ambassador role
- Foreign citizen role projection
- Per-member Embassy channel permissions
- Unlimited multi-Embassy assignments
- Pre-approval creation and expiry
- Embassy creation, archive/restore and alphabetical organizer
- Government and Foreign Diplomat dashboards
- Audit dashboard
- Reversible legacy-role migration snapshots and rollback
- Background access reconciliation after restarts and permission drift
- MongoDB indexes and durable state
- Render-compatible Docker deployment

## Architecture

```text
Applicant
  -> Private request thread
  -> WarEra profile resolution
  -> OTP/company verification
  -> Embassy selection
  -> Route resolver
      -> Pre-approved -> automatic approval
      -> Special official -> government authority
      -> Foreign diplomat -> assigned Embassy diplomat
      -> Indian government -> government authority
  -> Durable assignment
  -> Discord permission projection
  -> Audit log
```

MongoDB is the source of truth for live requests, assignments, approvals, pre-approvals, audit events and migration snapshots. GitHub stores source code and deployment configuration.

## Configuration

Copy `.env.example` to `.env` and provide the Discord token, MongoDB URI/database, and the WarEra API base URL. `WARERA_API_PROFILE_PATH` defaults to `/trpc/user.getUserLite` and can be changed if the API deployment exposes the profile endpoint under another path.

Never commit `.env` or credentials.

## Run

```text
pip install -r requirements.txt
python -m app
```
