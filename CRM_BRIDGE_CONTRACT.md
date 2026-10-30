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
