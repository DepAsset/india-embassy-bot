# Production sync marker

This repository's `main` branch is the canonical production source for RAJDOOT.

The deployment target is configured to auto-deploy from `main`. This marker intentionally creates a fresh production commit so the deployment service consumes the complete current hardened tree rather than remaining on an older live revision.

Current canonical source commit before this marker: `ffd1fc67869fb79325b1f4a04ffd93d1ad7a2bdd`.

Key production invariants in that source:
- country IDs are resolved to WarEra country names;
- own-country embassies with no active foreign diplomats auto-approve;
- embassy approval is only used when an active diplomat exists;
- one open request thread per applicant is enforced;
- fixed dashboards are persistent singletons;
- pending workflow controls are restored after restart;
- embassy layout is synchronized after embassy creation.
