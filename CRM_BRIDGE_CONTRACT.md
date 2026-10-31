# CRM bridge: verified integration boundary

## Existing sources (inspected locally)

- The Affiliates CRM: FastAPI + PostgreSQL. Protected offers endpoint is
  `GET /api/v1/workspaces/{workspace_id}/offers` and requires a CRM
  `WorkspaceMembership`, not a Telegram `initData` signature.
- CRM users/workspaces/offers have UUID keys. CRM roles and finance permissions
  are distinct from Partners' Telegram IDs and its `pending/active/rejected` state.
- Telegram Partners: `server/partners.sqlite3` is the authoritative database
  only for Telegram onboarding, approval and local offer publication.

## Minimal production-safe bridge that remains to be provisioned

Partners now exposes an **opt-in receiver** at `POST /api/internal/crm/offers`
for an authorized CRM-side publisher. It is disabled unless both
`CRM_FEED_TOKEN` (at least 32 characters) and `CRM_WORKSPACE_ID` are supplied
in the private environment. The publisher sends the secret in the
`X-CRM-Feed-Token` header over HTTPS. Allowed payload:

```json
{
  "workspace_id": "configured-workspace-uuid",
  "offers": [{
    "id": "crm-offer-uuid",
    "name": "Offer name",
    "offer_type": "Bank",
    "target_action": "Confirmed card",
    "is_active": true
  }]
}
```

The receiver rejects unrecognized keys (including private finance values),
cross-workspace imports, duplicate UUIDs and missing credentials. Imported
offers are initially drafts, require administrator publication and do not
claim a rate/hold value unless those become available through a separate
authorized source. Deactivated upstream offers become paused. The CRM-side
publisher and verified production credentials have **not** yet been installed.

### Standalone read-only publisher (implemented, opt-in)

**Interrupted snapshot recovery:** the publisher accepts `--run-id UUID`.
If an HTTP batch or commit acknowledgement fails, its error reports that
run ID without printing credentials. Re-run against **the same CRM source
snapshot** with `--send --run-id UUID` before the one-hour lease expires.
The server safely accepts already-staged identical batches and checks the
SHA-256 digest on a completed run; it will reject changed content for the
same run ID. If the underlying CRM data has changed, allow the unfinished
lease to expire and begin a fresh run rather than mixing snapshots.

**Notifications:** administrative partner status transitions and their bot
notifications are saved in one SQLite transaction. Repeated identical status
updates are acknowledged without adding duplicate events. The polling bot
retries delivery from the existing `bot_outbox`; this provides at-least-once
delivery, not an exactly-once Telegram guarantee.

**Safe update order:** the Partners deployment script now backs up the
configured server SQLite through the SQLite backup API and verifies the
backup **before** switching the Mini App release or restarting the services.
The script refuses a server-code update if its configured DB is missing.
Because the deploy runner and both services can have different environment
sources, an authorized operator must verify that all three resolve the same
`PARTNERS_DB_PATH` before approving the production merge/deploy.

**Staged protocol (current):** the publisher now uses a new UUID `run_id`
per run, `mode=begin` with the expected offer count, repeated `mode=batch`
requests (up to 100 offers per request), and `mode=commit` with a SHA-256
digest over canonical ordered public DTOs. The server stores batches in a
separate SQLite staging table. Only a complete verified commit updates the
offer catalog and pauses missing source offers in one transaction. An
incomplete/expired run (TTL one hour), interrupted request or invalid digest
does not change the published catalog. Replays are idempotent; previously
completed newer runs block stale finalization of older ones. More than 300
offers are supported. The legacy unversioned receiver is **disabled by
default**; `CRM_ALLOW_LEGACY_FEED=1` is reserved for explicitly controlled
compatibility tests and must not be enabled in production.

`server/crm_publisher.py` reads the actual CRM PostgreSQL `offers` table
through SQLAlchemy with `SET TRANSACTION READ ONLY` and a required workspace
filter. It requires a **dedicated least-privilege PostgreSQL account** restricted
to SELECT on the relevant offer fields. The DBA must provision it; do not reuse
application write credentials. No changes are required to CRM tables,
calculation code or deployment.

Set these private environment values **only on the authorized bridge host**:

- `CRM_READONLY_DATABASE_URL` — readonly PostgreSQL connection string
- `CRM_WORKSPACE_ID` — explicitly approved CRM workspace UUID, same on receiver
- `CRM_FEED_TOKEN` — new independent 32+ character service secret, same on receiver
- `PARTNERS_CRM_FEED_URL` — `https://theaffiliates.ru/partners/api/internal/crm/offers`

Use the CRM backend's existing pinned SQLAlchemy/PostgreSQL driver environment
to run `python server/crm_publisher.py` for a **dry run** (prints count and
field names, no offer data). After verifying the read-only account,
workspace and receiver authentication, run
`python server/crm_publisher.py --send` to submit batches of 100.

The receiver validates workspace, secret and DTO; duplicate source UUIDs
upsert the same draft/approved local record rather than making duplicate offers.
The publisher also reads archived source rows as inactive and sends a complete
snapshot manifest (`mode: "finalize"`, `offer_ids: [UUID...]`) **only after all
offer batches are acknowledged**. The receiving API pauses CRM offers omitted
from that complete manifest. It does not delete records. The publisher retries
transient HTTP 408/429/5xx and transport failures; reruns upsert the same UUID
without duplicates. To avoid unsafe oversized manifests, the current version
deliberately refuses snapshots over **300 offers**. A larger data set requires
a paginated/versioned snapshot protocol before synchronization is enabled.

An upstream inactive or absent offer cannot be republished through the admin
API (`409`). Upstream reactivation never restores a previous published status
automatically: an administrator must approve it again. Existing moderation of
active offers is otherwise preserved. No batch processing or finalization
removes historical local offers, and local non-CRM offers are left untouched.

Tracking links and finance statistics remain disabled without a separate
verified source. Receiver endpoint is not active in production until
independently configured.

### Explicit Telegram ↔ CRM identity association

**Operational recheck:** the administrative 'Перепроверить CRM' control
refreshes the Partners server snapshot, while the partner's profile recheck
refreshes `/api/partner/data`. Neither button launches an upstream PostgreSQL
read: only the separately authorized, read-only CRM publisher performs
identity attestations. Do not represent a screen refresh as source
verification. A successful source recheck must be run by the publisher with
`--send --verify-links`, and the owner can then refresh the UI.

The read-only bridge validates workspace IDs, Blogger UUIDs, per-mapping
versions, and the service acknowledgement. An archived or missing CRM
Blogger produces a negative attestation, not an invented identity. Local
bridge tests can use a stub SQL source, but they do not prove production
PostgreSQL connectivity or ownership of a natural person's CRM account.

**Rollback scope:** the Partners deploy script now restores the previous
web-release symlink if a post-switch health check fails. The previous
server Python code and SQLite schema are **not** automatically rolled back;
database changes remain additive. A privileged operator must inspect the
failure before deciding whether to restore the prior Git version, restart
the services or use a verified SQLite backup. The release marker is written
only after the health checks complete.

**Attestation response ordering:** each owner-selected mapping has a
`mapping_version`. The authenticated `identity/requests` call now also
issues a fresh `check_version` for that particular verification round.
The read-only publisher must echo both values and the requested Telegram ID,
CRM Blogger UUID and its explicit `exists` boolean in
`identity/attestations`. Only the currently selected mapping and most
recent verification round can change `crmLinked`. Old positive responses
cannot restore a link after a newer negative CRM check. The SQLite schema
is upgraded additively; previously verified legacy rows without versions
are reset to unverified until checked again. This is intentional fail-closed
behavior, not evidence of account deletion.

Partners stores a separate additive table `crm_partner_links`. An approved
partner with a verified Telegram contact can be proposed for linking by the
**signed Telegram owner** in the administrative UI, using the actual
`Blogger.id` UUID from CRM (not its handle, mutable username or phone).
That owner-approved association initially has `verified=0` and gives no
CRM permissions. The service endpoint
`POST /api/internal/crm/identity/requests` returns only the owner-selected
Blogger UUIDs to the authenticated read-only bridge. The publisher can then
query the existing CRM `bloggers` table for those UUIDs within the configured
workspace, excluding archived bloggers. Only an authenticated
`POST /api/internal/crm/identity` attestation marks matching associations
as verified. Use `python server/crm_publisher.py --send --verify-links` after
provisioning the read-only source credential and feed key. Repeating an
unchanged mapping does not revoke verification; moving a mapping resets it.

This two-sided confirmation verifies the CRM entity exists and that the
Partners owner explicitly selected it. It does **not** independently establish
that the same natural person owns both accounts; perform the actual identity
check before manually selecting the UUID. No CRM staff or workspace
membership role is imported, and neither a service attestation nor a linked
partner grants The Affiliates Partners administrator rights. The partner's
`/api/me` only returns a boolean `crmLinked`; no CRM UUIDs or workspace
financial values are exposed to ordinary partners.

### Isolated testing and deployment configuration

### Partner API availability contract

`POST /api/partner/data` requires signed Telegram initData and an approved,
phone-verified partner (or the verified numeric owner). The response exposes
`crmLinked` only as a boolean and explicit unavailable states for tracking,
conversions and payments. The endpoint does not fabricate balances, tracking
links, payouts, partner-specific CRM rows or agency financial fields. The
`POST /api/links/{offer_id}` route now checks partner authorization and
whether an offer is currently published and source-active **before**
returning a tracking-service-unavailable error. A real CRM-linked UUID
alone must never be treated as permission to see another partner's data.

### Crash-safe bot onboarding

First contact verification and repeat application now enqueue owner alerts
inside the same SQLite transaction as the registration state change.
Previously these were sequential commits, and an intervening crash could
leave a pending application without a notification. Repeated Telegram
updates do not re-enqueue after a committed transition. Telegram delivery
remains at-least-once, not exactly-once.

### Production acceptance before authorized deployment

**Actual VPS process comparison (read-only):** after authorized access to
the running Beget host, execute
`python3 deployment/inspect_runtime.py` from the Partners checkout under
an operator account allowed to inspect the two systemd service processes.
Unlike `server/preflight.py` (which examines the current shell's environment),
this compares the **running** API and bot processes using
`systemctl show`, their individual `/proc/<pid>/environ` entries, and the
device/inode of their SQLite databases. It reports whether their Telegram
tokens match, but prints **no token, feed key, or raw environment dump**.
Require `same_db_file=true`, `same_telegram_token=true`, both units
`active`, and matching Mini App URL configuration before treating the
identity chain as deployed. Missing permissions cause an error, not a
fabricated healthy result. A local dry-run/test cannot establish the same
facts on the VPS.

**Moderation/source independence:** a committed complete CRM snapshot now
switches `crm_offer_source.source_active` for missing or archived offers
without rewriting their owner moderation status. Visibility requires both
`status=approved` and `source_active=1`; a returning source offer retains
the previous owner decision. No incomplete snapshot changes visibility.
Keep `CRM_ALLOW_LEGACY_FEED` unset in production: its old partial-batch
compatibility mode cannot guarantee full-snapshot source-state semantics.

**Controlled rollback after deployment failure:** check the deployed Git
commit marker, existing SQLite backup integrity and old web-release path
first. Stop both Partners services before any database restore. Restore
the prior *Partners-only* server commit and systemd unit files after
reviewing any additive schema changes; verify the API and bot using
`server/preflight.py` and `deployment/inspect_runtime.py`. If database
restoration is necessary, use the previously verified SQLite backup
through an operator-controlled offline procedure while both processes are
stopped. Never overwrite a live WAL-mode SQLite file, nor reset the
unrelated main CRM repository. The deploy script automatically rolls back
only the Mini App symlink; server code and SQLite restoration are
intentionally manual to prevent data loss.

The unattended release script now uses the running systemd processes'
resolved SQLite file identity for its pre-release backup, rather than
trusting an environment variable inherited by the deploy runner. It
aborts before switching the Mini App if the API and bot do not both
report an active state, a single physical SQLite file and a matching
configured Telegram token. Authorized root/systemd inspection
permissions are therefore a deployment prerequisite. An initial install
without running services requires a separately reviewed bootstrap path,
not bypassing these checks with a guessed default SQLite path.

On the VPS, **read only**, inspect the two actual units via
`systemctl cat the-affiliates-partners-api.service the-affiliates-partners-bot.service`
and check the effective `WorkingDirectory`, service user, `ExecStart`
and any environment file references. Avoid printing `systemctl show -p Environment`
or raw environment files because they may expose secrets.
Run `python3 server/preflight.py` with each service's private environment
loaded by an authorized administrator. It reports only presence flags,
the resolved SQLite path, table existence and read-only integrity.
Both processes must report the **same absolute server SQLite path**,
not the developer PC path. The bot must have been registered with the
rotated BotFather token; the API must validate initData against that same
token, never the old compromised token.

Inspect the actual Git branch, deploy timer and current release marker
without changing them. The current deployment script only accepts
`main`; this feature branch requires an authorized review/merge before
the timer can deliver it. After authorized deployment, verify the
`/partners/` bundle, `/partners/api/health` proxy and a real owner
Telegram session; public HTTP 200 alone does not establish auth or
database consistency. Production credentials are not needed for
local isolated tests and must never be copied into this repository.

`PARTNERS_DB_PATH` optionally fixes the shared Partners SQLite location for
the bot and API. If omitted, both use `server/partners.sqlite3` under the
Partners repository; ensure the **same** path and database permissions in
both production services. Do not substitute the developer PC's local file for
the VPS database. Test-only `TELEGRAM_NOTIFICATIONS_ENABLED=0` prevents
network sends during isolated browser checks; do not enable it in production.
The test fixture generator `tests/create_browser_fixtures.py` produces
gitignored pages with synthetic signed initData and must never be treated as
proof of a real Telegram session.

1. Configure a service-to-service identity **inside the CRM authorization boundary**,
   scoped to one explicit workspace and read-only active offers. Do not reuse
   a browser cookie, owner password, CSRF token or bot token.
2. Map each approved `telegram_id` to an explicitly verified `crm_partner_id`
   and `workspace_id` in a uniquely constrained mapping table. A matching
   username or phone alone must never create a link.
3. Return only `id`, `name`, `offer_type`, `target_action`,
   `is_active`, `partner_payout` if authorized, and an explicitly
   sourced hold duration if present. Never return `agency_rate`,
   `agency_profit`, internal blogger accrual or other workspace finances.
4. Tracking links must come from the tracking system with authenticated
   partner/offer attribution and an auditable immutable ID. Never compose a
   plausible-looking URL from Telegram ID or username.
5. Conversions, actions and payouts require their own partner-scoped CRM
   endpoints; until available, render empty/unavailable UI states.
6. Implement a versioned, idempotent pull/push bridge with upstream offer UUID
   identity and tenant scoping, a staging replay and a read-only production
   verification before enabling it. Do not merge or write directly between
   SQLite and PostgreSQL.

## Current blocker

The inspected CRM currently exposes authenticated workspace-member routes
and finance-sensitive serializers, not a verified machine-to-machine
partner-scoped read-only service contract. No such credential or partner
mapping exists in this Partners repository. The bridge must not silently
substitute dummy offers or use a high-privilege CRM user session.
