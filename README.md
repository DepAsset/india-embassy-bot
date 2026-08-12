# India Embassy Bot

Dedicated Discord embassy verification and access-management bot for the WarEra India server.

## Current design

The bot replaces the legacy Ticket Tool/manual embassy workflow with a controlled verification flow:

1. A foreign diplomat starts verification.
2. The bot verifies the user's WarEra identity through the configured API client.
3. The bot generates a unique 6-digit ownership OTP.
4. Ownership is confirmed through the configured WarEra company-rename mechanism, with up to 5 attempts.
5. The bot presents the verified WarEra profile summary.
6. The applicant selects whether the embassy represents their own country or another country.
7. Pre-approved applicants can bypass manual approval.
8. Existing active embassies are routed for diplomat approval.
9. If the embassy does not exist, the bot can create the embassy channel and configure member-specific permissions.
10. If an embassy exists but has no active diplomats, the request is routed to EAM/embassy administration.
11. Every important action is written to the audit log.

## Important security rule

Secrets are never committed to GitHub. Use `.env` locally and environment variables in Render.

## Required environment variables

See `.env.example`.

## Runtime

- Python 3.12+
- discord.py 2.x
- MongoDB
- aiohttp
- Docker / Render

## Status

Initial production architecture is being built. The WarEra API adapter is intentionally isolated so the exact API contract can be configured without spreading API-specific assumptions through the bot.
