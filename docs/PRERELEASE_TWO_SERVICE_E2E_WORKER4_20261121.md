# Two-service CRM ↔ Partners E2E: isolated local probe (2026-11-21)

## Isolation

- PostgreSQL 17 binaries: `C:\Program Files\PostgreSQL\17\bin`.
- New disposable cluster: `D:\GPT\.worker4-e2e-pg-20261121`, bound only to `127.0.0.1:55439`.
- Synthetic database: `partners_e2e_worker4`; isolated local role `e2e_admin` with local trust authentication; no production credentials.
- Local Partners repository: `D:\GPT\.partners-green-theme-20261114`.
- Local CRM backend: `D:\GPT\Website\backend`.
- Preparation succeeded: `database.prepare_schema --confirm-ddl` ("Partners schema prepared and verified"); CRM `alembic upgrade head` (exit code 0).

## Reproduction

With the isolated cluster running and the synthetic database created:

```powershell
$env:CRM_BACKEND_ROOT='D:\GPT\Website\backend'
$env:TEST_DATABASE_URL='postgresql+psycopg://e2e_admin@127.0.0.1:55439/partners_e2e_worker4'
$env:PARTNERS_DATABASE_URL='postgresql://e2e_admin@127.0.0.1:55439/partners_e2e_worker4'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
$env:APP_ENV='test'
py -3.12 -m unittest tests.test_two_service_pg_http_e2e -v
```

Result: **2 tests, FAILED (failures=1, errors=1), exit code 1**, in 7.206 seconds.

1. `test_consent_registration_binding_offers_and_tasks`: `ModuleNotFoundError: No module named 'app.models.offer_assignment'` on line 174 of `tests/test_two_service_pg_http_e2e.py`.
2. `test_agency_referrer_signed_http_registration_first_attribution`: expected `{'claimed': 2, 'delivered': 2, 'failed': 0}`; actual `{'claimed': 2, 'delivered': 0, 'failed': 2}` at line 133. Outbox `last_error` entries were `AssertionError` and `ConnectionAbortedError`.

## Root cause and decision

The checked-out CRM backend does not include the Partners integration expected by these tests: `app/api/router.py` registers no Partners integration router; `app/models/__init__.py` does not expose `OfferAssignment`; no `app/models/offer_assignment.py` exists. The API lacks the test-required `.../integrations/partners/leads` route and the corresponding outbox/import functionality. Test expectations reflect a newer CRM integration than this local checkout. Running the other integration scenarios against this backend would hit the same absent routes/models. The correct follow-up is to locate/prepare a compatible CRM version; altering tests to accept missing functionality would conceal the blocker.

## Cleanup

`pg_ctl -D D:\GPT\.worker4-e2e-pg-20261121 -m immediate -w stop` exited 0 and reported `server stopped`. The temporary cluster directory was removed. Port 55439 had no listener afterward. No CRM source/data files were changed by this probe; no Git commit or publication was performed.

## Compatible CRM rerun (same day)

Both clean CRM Git worktrees were inspected before running tests:

- `D:\GPT\.crm-partners-e2e-20261031`, HEAD `93cc636881a6acf84adc58f13e0232daa63398b5` (2026-10-31), contains offer assignments and Partners router, but lacks the task-report model and instructions API.
- **Selected** `D:\GPT\.crm-aeza-bootstrap-20261114`, HEAD `0c1c8da305cc3528ea4c68d33a8123feb2bf7ea4` (2026-11-14), contains `app/models/offer_assignment.py`, `app/models/partners_outbox.py`, `app/models/partner_task_report.py`, `app/modules/partners/router.py` and `app/modules/offers/instructions.py`. Both worktrees reported no Git changes before or after the run. Python 3.12 imports for pytest, sqlalchemy, psycopg, uvicorn and alembic succeeded.

A **new** isolated PostgreSQL 17 cluster `D:\GPT\.worker4-e2e-pg-rerun-20261121` was initialized and started only on `127.0.0.1:55439`; database `partners_e2e_rerun` was created. Partners `py -3.12 -m database.prepare_schema --confirm-ddl` exited 0 (`Partners schema prepared and verified`). CRM `py -3.12 -m alembic upgrade head` from the selected worktree's `backend` directory exited 0 through revision `20261101_0029`.

With the selected worktree's backend root, the exact run was:

```powershell
$env:CRM_BACKEND_ROOT='D:\GPT\.crm-aeza-bootstrap-20261114\backend'
$env:TEST_DATABASE_URL='postgresql+psycopg://e2e_admin@127.0.0.1:55439/partners_e2e_rerun'
$env:PARTNERS_DATABASE_URL='postgresql://e2e_admin@127.0.0.1:55439/partners_e2e_rerun'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
$env:APP_ENV='test'
py -3.12 -m unittest tests.test_two_service_pg_http_e2e tests.test_two_service_agency_referral_http_e2e tests.test_two_service_reverse_order_http tests.test_instruction_publish_two_service_e2e -q
```

**Result: 5 tests in 21.944 seconds; 2 passed, 3 failed, exit code 1.** Exact failures:

1. `tests.test_two_service_agency_referral_http_e2e.AgencyReferralTwoServiceHTTP.test_agency_referral_attribution_replay_and_offers`, line 118: expected `failed >= 3`; actual `{'claimed': 1, 'delivered': 0, 'failed': 1}`.
2. `tests.test_two_service_reverse_order_http.ReverseOrderHTTP.test_reverse_versioned_and_legacy_cutover`, line 83: expected snapshot versions `[1, 2]`, actual `[1, 1, 2]`.
3. `tests.test_instruction_publish_two_service_e2e.PublishedInstructionHTTP.test_owner_draft_publish_republish_signed_catalog`, line 108/111: expected zero event delivery failures and exactly one initial event; actual delivery `{'sent': 4, 'failed': 1}` (one HTTP 409 reported in output).

The two tests in `test_two_service_pg_http_e2e.py` passed. These later failures have a plausible shared-test-state component: all five run within one process and share the same database/outbox, and certain tests count all outstanding events rather than those generated by their own scenario. The 409 response requires separate investigation before attributing it solely to test isolation. No blanket product pass can be inferred from this run; tests were not altered or rerun, per the bounded probe request.

Full command output: `D:\GPT\.worker4-e2e-rerun-20261121-test.log` (outside repositories). The new temporary cluster was stopped successfully and its directory removed. `127.0.0.1:55439` had **no listener** after cleanup. No CRM or Partners application/test code was changed; no production access or publication occurred.

## Final isolation diagnostic (stopped at prime's request)

Inspected the three failing assertions before further testing. The agency/referrer test counts all outstanding `crm_registration_outbox` deliveries (expects 3) and the publish test calls global `deliver_due` (expects a single event), so both are vulnerable to outstanding events from other tests. The reverse-order test selects **all** `offers.assigned` outbox events, not just those for its own lead, and expects `[1,2]`; the observed `[1,1,2]` in the combined run is consistent with an additional version-1 event from a different scenario. These are plausible shared-state explanations, not proof that each scenario passes individually. The HTTP 409 observed in the combined run is also not independently classified.

Prepared a fresh isolated PostgreSQL 17 cluster `D:\GPT\.worker4-e2e-pg-isolated-20261121` on `127.0.0.1:55439` with **three separate new databases**: `partners_e2e_agency`, `partners_e2e_reverse`, and `partners_e2e_publish`. Partners schema preparation and compatible CRM worktree Alembic migrations succeeded for all three databases (each migration command exited zero). **Before any of the three individual test cases was executed, the prime requested termination of the diagnostic to finalize the release work.** Consequently the isolated rerun outcomes are **not measured**, and the 3 combined-suite failures remain unresolved. No individual rerun was attempted or reported as successful.

The isolated PostgreSQL server was stopped (`pg_ctl` exit 0), cluster directory removed, and `55439` verified to have no listener. No source, tests, or CRM worktree files were modified.
