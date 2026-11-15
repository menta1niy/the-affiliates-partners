# Partners administrator cabinet — capability and acceptance inventory

Checked against `web/admin/index.html`, `web/admin/admin.js`, `server/api.py`,
and `server/db.py` on 2026-11-15. This is a functional inventory, **not**
evidence of live Telegram end-to-end acceptance.

| Activity | Partners admin UI/API | Operational limitation |
| --- | --- | --- |
| View participant counts, pending requests and statuses | Present | `/api/admin/users` returns 50 users per page, with server-side name/ID/username search and status/role filters; pending requests are paginated separately |
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
- The historical dashboard response retains its 200-user cap for compatible
  summary consumers. The user and pending screens now use a distinct
  `/api/admin/users` endpoint with 50-row pages and SQL-level tenant/manager
  restrictions on every page. Search and filters cover older users, not just
  the first dashboard response. A typing indicator prevents clicking stale
  results during asynchronous searches.
- Smoke tests cover agency isolation, read-only card data, desktop/mobile
  rendering, stale-request switching, cross-agency paging, manager scope,
  malformed filters and browser-driven search across more than 200 users.
- The browser test server now serves `telegram-layout.js` as the production
  static bundle does, rather than emitting a misleading 404 during tests.

## Remaining acceptance requirements

1. Deploy and validate the new server-side pagination together with the updated
   admin static bundle; **do not deploy the HTML/JS alone** because older API
   versions lack `/api/admin/users`.
2. Verify the complete CRM offer-management UI and its permission model; do not
   label read-only offer snapshots in Partners as editable bank offers.
3. Complete CRM owner/Team initialization and CRM↔Partners signed event flows.
4. Run authenticated admin/user browser flows with real Telegram `initData`,
   including authorization failures and mobile UX.

No production deployment or database migration is implied by this document.
