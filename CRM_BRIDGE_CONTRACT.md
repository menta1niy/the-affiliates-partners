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
