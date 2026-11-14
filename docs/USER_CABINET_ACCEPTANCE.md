# Participant cabinet and Telegram — stage 5 local acceptance

Reviewed 2026-11-15 against `web/app.js`, `web/index.html`, authenticated
`server/api.py` routes and the browser/HTTP test suites. This is **local
acceptance only**, not evidence that the production bot webhook is enabled or
that a real Telegram session was exercised.

| Workflow | Local evidence | Live gate |
| --- | --- | --- |
| Missing/invalid Telegram initData | Chromium browser smoke shows gated login and rejects synthetic 401 | Check actual Telegram WebApp initData, expiration and mobile app launch |
| Consent-based registration and attribution | Backend registration, invitation, scope and signed HTTP tests | Bot `/start` and signed `start_param` in a real Telegram session |
| Active participant offer/task list | Chromium smoke, assigned offers and tasks | CRM lead binding, published instructions, assigned-offer event delivery |
| Participant action report | Browser + backend task-report tests | Verify CRM receives report as unverified, without changing banking or payout status |
| CRM application and payout statuses | Browser fixture uses actual `/lead-view` endpoint; backend signed snapshots tested | Confirm only CRM-controlled states and role-scoped data are displayed |
| Referral link sharing | UI builds URL only from a valid server-issued `ref_` code and canonical bot address | Verify live Telegram deep-link and server-side entitlement |
| External offer and published instruction URLs | Chromium checks links/images; HTTPS only, no credentials, backslashes or control chars | Confirm CRM-approved destinations and real mobile browser behavior |
| Phone-size layout | Chromium 390 px / 1440 px tests | Manual iPhone/Android Telegram WebView check |

## Changes verified locally

- Reject remote referral link fields as authorities. Only a matching
  `ref_` invitation code received from the signed-session server endpoint may
  create a shareable link to `t.me/affialite_partners_bot`.
- Apply the existing published-material HTTPS URL parser to bank offer links;
  reject embedded credentials, control characters and backslashes, and set
  `referrerpolicy=no-referrer` on opened offer links.
- Align browser smoke's simulated CRM status with the actual `/lead-view`
  request; have its local server serve `telegram-layout.js` as production does.
- Preserve the distinction between a participant's *submitted report* and a
  banking result or payment *confirmed by CRM*.

## Not yet complete

The production CRM still requires its sole `Team` workspace and owner. Until
the signed CRM↔Partners flow is running, offers and payout snapshots are not
live end-to-end. A real Telegram session and approved webhook setup are also
pending. Do not enable the webhook or mark the cabinet launch-ready based
only on mocked browser fixtures. This file introduces no database migration or
production configuration change.
