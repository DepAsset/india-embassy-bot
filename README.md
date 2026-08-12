# India Embassy Bot

A dedicated Discord bot for the WarEra India Embassy Management System.

## Source of truth

The bot is implemented against the **Embassy System Master AI Coding Handoff v3.0**. Business rules must not be invented or changed by implementation defaults.

## Architecture

- Python 3.13+
- discord.py
- aiohttp health server
- MongoDB for persistent state
- Render-compatible Docker deployment
- Direct Discord member/channel permissions for embassy access
- One global `@Foreign Diplomat` role
- Dashboard-first administration

## Runtime data

GitHub stores source code, configuration templates, documentation and migration scripts. MongoDB stores live requests, assignments, pre-approvals, audit logs, snapshots and system state.

## Local setup

1. Copy `.env.example` to `.env`.
2. Fill required secrets/configuration.
3. Install dependencies with `pip install -r requirements.txt`.
4. Run `python -m app`.

Never commit `.env` or credentials.
