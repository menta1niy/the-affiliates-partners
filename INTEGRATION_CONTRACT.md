# The Affiliates Partners: end-to-end implementation contract

## Single source of truth
- One persistent SQLite partners database is shared by the bot and Mini App API. Never overwrite production data during deploy.
- Telegram numeric user ID is the only account key; mutable username is display metadata. Verify phone contact.user_id equals message.from.id. Verify signed WebApp initData on server.
- Repeated /start must not erase a contact, restart registration, change approval or create duplicate registrations.
- Signed admin ID 758398804 exclusively controls approvals and offers, independent of phone or username.

## UI state machine
- Start with loading, never an invented demo identity or invented financial figures.
- On auth success load the same database identity the bot stores; distinguish no phone, pending, rejected, active, and admin.
- Missing/invalid initData, API errors, or timeout are explicit login errors with retry, never misrepresented as a missing phone.
- Refresh identity on Mini App reopening/return. Only active partners see approved offers. Admin alone sees applications and publication controls.

## Development and deployment
- Edit locally, test, build, commit and push to GitHub. Isolated VPS systemd deploy pulls updates. Do not manually alter website or CRM.
- Run backend tests before service restarts. Restart only modified Mini App services. Secrets and SQLite database never enter Git.

## Acceptance tests
1. First /start -> own contact -> stored phone and username by numeric ID -> pending -> single admin notification -> admin approve -> real Mini App profile.
2. Repeat /start for pending, active and rejected, without status downgrade or data loss.
3. A forwarded contact and reuse of a phone by different Telegram ID fail.
4. Admin ID receives admin interface; all other IDs get HTTP 403 even with same username.
5. Without signed initData or during API error show error, not Demo-partner, fake balances or phone prompt.
6. Confirm local tests, frontend build, deployment and live health independently. Real second-account validation must be called out if not performed.
