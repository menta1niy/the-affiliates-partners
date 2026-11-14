# The Affiliates — Stage 6 verification and go-live decision

**Checked:** 2026-11-15. **Decision:** NO-GO for two-cabinet production acceptance.
This document closes the *available verification work*, not the incomplete
production rollout. No CRM owner/Team creation, service restart, webhook
activation, outbox enablement, migration, or production release was performed.

## Verified evidence

| Area | Evidence | Decision |
| --- | --- | --- |
| Source revisions | CRM `0c1c8da305cc3528ea4c68d33a8123feb2bf7ea4`; Partners `168fe984d399d501756cc6e49d3ed0d9ff1d5046`; both local worktrees clean before this report | Local release candidates exist; not equal to live deployed revisions |
| Local cross-service flows | Targeted Partners suite: 9 tests, 5 conditional PostgreSQL E2E skips, 0 failures | **Partial**, not a real two-service PostgreSQL pass |
| CRM contracts and financial scope | 6 no-DB tests passed; remaining 22 selected tests require the `env`/DB fixtures from `tests/conftest.py` | **Not accepted** without an authenticated, disposable `_test` PostgreSQL database |
| Production static HTTPS | `/partners/`, `/partners/admin/`, `/partners/api/health`, `/partners/style.css` all HTTP 200 | Connectivity/serving OK, not authentication acceptance |
| Runtime services | `ta-crm-api`, `ta-partners-api`, Nginx, PostgreSQL, `ta-restic-snapshot.timer` active | Baseline running |
| Database bootstrap | Live CRM public schema: 0 users, 0 workspaces, 0 workspace memberships | **BLOCKER:** sole owner and `Team` do not exist |
| Event publisher | `CRM_PARTNERS_OUTBOX_ENABLED=0`; Partners workspace UUID not configured in last readiness check | **BLOCKER:** cross-service positive live test impossible |
| Daily backups | `ta-restic-snapshot.timer` enabled; duplicate PostgreSQL timer disabled | One daily chain preserved |
| Windows offsite | `aeza-restic-20261114-194520.tar.gz`: SHA-256 verified; gzip/tar parse OK, 276 entries, `ta-restic/config` present | Export verified, **not** an independent restored database |
| Windows pull schedule | `TheAffiliates-Aeza-Offsite-Pull` enabled, previous result 0, next scheduled 2026-11-15 12:30 (PC local time) | Automation present; run depends on Windows logon/power |
| Backup recovery | Prior server-side Restic snapshot restored into a disposable PostgreSQL database with 49 tables and 102 foreign keys | Server-side restore proven; Windows-downloaded archive restore still untested |
| Live release rollback | Static symlink points at `e16e1a5693513198f539f90b313403a7b60752f8` and `.previous.*` directory exists | Previous version available for manual rollback |

### Last verified static UI release prepared locally (NOT deployed)

- `D:\GPT\_ta-partners-releases\partners-web-168fe984d399.tar.gz`
- SHA-256: `d36053a895f461770d2f8306bfa6b361660f25207289e1616a7a07538f2db3ed`
- Six allowlisted public assets and a manifest; file hashes all verified; no secret/config/private assets
- The archive includes stage 4/5 UI fixes but **not** the corresponding changed
  backend (e.g. `users_truncated`), so publishing the archive alone does not
  complete the operational release or admin paging.

## Live acceptance blockers, in required order

1. **CRM owner and exactly one `Team`:** this remains uninitialized. The
   production bootstrap was previously blocked and must not be retried through
   alternate commands or direct SQL to circumvent that restriction. Only a
   permitted, reviewed initialization procedure may close this item. Verify
   owner count, unique Team workspace and owner membership afterward.
2. **Cross-service integration:** once the actual Team UUID exists, configure
   it in protected Partners runtime settings, verify the secrets match without
   printing them, test signed positive/negative requests, then enable CRM
   outbox and both registration/report workers in the approved order.
3. **Admin self-service:** implement scoped server-side pagination for users
   and pending queue; check CRM offer CRUD/publication/assignment and
   finance-owned UI. Partners exposes read-only financial snapshots, not
   payment authority.
4. **Telegram:** verify real signed `initData`, `/start` attribution, invite,
   registration, approval, participant offers, reports and role-denied flows in
   Telegram mobile; enable the webhook only after those prerequisites.
5. **Recovery:** restore independently from a Windows-downloaded encrypted
   Restic archive into a disposable environment. Automated *server-side*
   Restic retention is still not installed; its earlier live application was
   blocked and was not bypassed. Preserve existing recovery points.
6. **Controlled deployment:** deploy the same reviewed local server/static
   revisions with explicit rollback record, repeat live HTTPS/RBAC/
   finance-isolation checks and record final acceptance evidence.

## Test environment clarification

The CRM `tests/conftest.py` requires a dedicated PostgreSQL database whose
name ends in `_test`; it recreates `public` schema and must **never** be run
against live or development data. Initial selective execution with
`--noconftest` generated 22 missing-fixture errors (not code failures); a
connection probe to `127.0.0.1:5432/affiliates_test` subsequently reported
missing database authentication. No existing password was printed or copied.
Do not report these tests as passed. Partners conditional PostgreSQL scenarios
were skipped because `TEST_DATABASE_URL` and `CRM_BACKEND_ROOT` were not set.

## Scope closure

This verification stage is complete **as a readiness audit**. The six-stage
product goal is **not** complete. Keep steps 2–5 open and do not mark Stage 6
as successful production acceptance until the blockers above are closed.
