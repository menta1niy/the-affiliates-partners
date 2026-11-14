# Partners administrator cabinet — capability and acceptance inventory

Checked against `web/admin/index.html`, `web/admin/admin.js`, `server/api.py`,
and `server/db.py` on 2026-11-15. This is a functional inventory, **not**
evidence of live Telegram end-to-end acceptance.

| Activity | Partners admin UI/API | Operational limitation |
| --- | --- | --- |
| View participant counts, pending requests and statuses | Present | Dashboard returns up to 200 most recently registered users; counts cover the scope, but on-screen search and pending queue do not cover older rows |
| Approve, reject, block and unblock | Present, server-authorized | Reject/block require a reason; staff permissions are narrower |
| Change participant roles/manager | Present, server-authorized | Owner-only admin assignment; manager hierarchy validated by backend |
| Create/revoke invitations, agency assignment | Present | Revoke and share availability checked on server |
| Correct an existing attribution | Owner-only UI/API | Reason is required and audited; attribution correction is not an unrestricted self-service action |
| Inspect CRM-bound participant offers, reports, stages and payouts | Read-only participant card | Requires functioning CRM↔Partners synchronization |
| Create/edit bank offers, publish instructions, assign offers | **Not in Partners admin UI** | CRM owns offer management and assignment; a dedicated authorized CRM UI/workflow is required |
| Confirm banking stages, accruals and payouts | **Not in Partners admin UI** | CRM-only operations; do not introduce financial mutation endpoints in Partners |
| Use authenticated Telegram sessions end to end | Not yet live-accepted | Real Telegram `initData`, permissions and callback/webhook flows must be tested |

## Stage 4 local improvements

- A stale async response must never overwrite a newly opened participant card.
- When the dashboard exceeds its 200-user response cap, the UI must explicitly
  disclose that the on-screen list, filters and pending queue are incomplete.
  The warning persists after filtering. Server-side pagination **remains
  necessary** for operational use beyond 200 participants.
- Smoke tests cover agency isolation, read-only card data, desktop/mobile
  rendering, stale-request switching and the truncated-dashboard warning.
- The browser test server now serves `telegram-layout.js` as the production
  static bundle does, rather than emitting a misleading 404 during tests.

## Remaining acceptance requirements

1. Implement server-side pagination (including search, status and role filters)
   for users and pending requests, retaining agency/manager scope on each page.
2. Verify the complete CRM offer-management UI and its permission model; do not
   label read-only offer snapshots in Partners as editable bank offers.
3. Complete CRM owner/Team initialization and CRM↔Partners signed event flows.
4. Run authenticated admin/user browser flows with real Telegram `initData`,
   including authorization failures and mobile UX.

No production deployment or database migration is implied by this document.
