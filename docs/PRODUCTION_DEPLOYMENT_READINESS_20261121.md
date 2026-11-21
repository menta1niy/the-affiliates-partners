# The Affiliates Partners — production deployment readiness audit (2026-11-21)

Scope: read-only local review of `feature/green-theme-20261114`, local release commands, and a non-interactive attempt to inspect the Aeza host. No push, server write, deploy, migration or server-side changes were performed.

## Decision

**NO-GO for production now.** `python -m tools.stage13_preflight --require-ready` returned exit 2 with `technical_pass=true` and `release_ready=false`. Its listed blockers are legal approval, disposable PostgreSQL restore/migration/privilege acceptance, real Telegram mobile/notification acceptance, and release authorization. This audit does not supersede test workers' independent results.

`deployment/legal-approval.json` does not exist. `python tools/build_static_release.py` returned exit 1 (`Legal approval missing: publication of draft documents is forbidden`) before producing a package. Never fabricate the approval record or disable this guard to obtain an archive. The five `web/legal/*.html` files are currently modified by another worker; their final review is not part of this audit. Builder also requires clean committed `web/` source, matching tracked files, and legal approval.

`python tools/prerelease_static_dry_run.py` returned exit 0: 14 static assets, `asset_integrity=pass`, `legal_gate=blocked`, `release_ready=false`, `publishing_performed=false`. This validates the current local asset inventory only; it is not an installable or legally approved release.

## Deployment entrypoints and danger

- `deployment/the-affiliates-partners-deploy.timer`: configured with `OnBootSec=2min`, `OnUnitInactiveSec=5min`, `Persistent=true`; it invokes `the-affiliates-partners-deploy.service`, which executes `/opt/the-affiliates-partners/deployment/deploy.sh`. Timer file presence does **not** prove it is enabled on Aeza.
- The **local** `deployment/deploy.sh` now has an unconditional `exit 1` before fetching, merging, restarting services or copying `web/`. This fail-closed change is only proven in the local checkout. The old server-side revision could still run `git fetch origin main`, `git merge --ff-only`, copy web files directly, and bypass the legal approval and manifest checks; a push is therefore hazardous until the actual server timer and script are inspected and the timer is disabled.
- `deployment/install-static-release.sh` is a separate **static-only** Linux installer: checks archive SHA-256, validates tar member safety and per-file manifest hashes, enforces required pages/design tokens/legal version and draft rejection, stages an immutable web release and atomically switches the public symlink. It does not deploy backend, migrate PostgreSQL, update runtime secrets, adjust webhook or restart API. Do not describe it as a full-stack release.
- Current `deployment/deploy.sh` cannot serve as a backend updater (retired). Backend needs an independently reviewed, compatible procedure; compare production backend commit and schema, current CRM integration, runtime/systemd user and service files, migrations and rollback compatibility before any cutover. The `deployment/the-affiliates-partners-api.service` file runs `python3 -m server.api` as `ta-partners` from `/opt/the-affiliates-partners`, port 8788, conditioned on runtime-user readiness. Do not assume current Aeza units equal the local samples.
- The `README.md` deploy section still describes the retired GitHub auto-deploy timer; `docs/FINAL_RELEASE_RUNBOOK_STAGE14.md` and `docs/LOCAL_FIRST_RELEASE.md` contain the newer safety rules. Follow those over the stale README description.

## Remote access evidence

Windows `ssh.exe` exists, and TCP connection to Aeza SSH address `82.148.243.63:22` succeeded via `Test-NetConnection`. A read-only `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=6 -o ConnectionAttempts=1 root@82.148.243.63 'systemctl is-enabled ...; systemctl is-active ...; head -n 12 ...'` returned **exit 255, `Permission denied (publickey)`**. No remote command executed. Thus server timer state, live script revision, backend runtime, backup state, and webhook remain **unknown**. Port reachability does not establish authenticated administrative access. No private key, token or credential was read, sent or displayed by this audit.

## Safe release checklist (requires a later authorized operation)

1. Complete independent legal, PostgreSQL, CRM E2E and real-device acceptance. Confirm `release_ready=true` via the actual preflight after legitimate approvals; resolve the currently modified legal pages. Review complete git diff, test results, and selected release commit.
2. Obtain authenticated, authorized **read-only** Aeza inspection using an available validated SSH identity. Record deployed commit, Nginx/API/static paths, `systemctl is-enabled/is-active` for the legacy deploy timer, its service and *actual remote script contents*, health status, schema migration revision, webhook state, and rollback references. Do not infer these from local files.
3. **Before any GitHub push**, establish that the legacy timer is disabled on the server using a separately authorized administrative change; verify it is inactive/disabled afterward. A local `exit 1` is insufficient until that revision is installed on the host.
4. Verify backup provenance and practice restore to isolated PostgreSQL; confirm permissions and separation from CRM `public`. Prepare independently reviewed backend deployment/migration/health/rollback steps and ensure old/new frontend/backend API compatibility.
5. After explicit authorization, push only the reviewed commit, keep auto-deploy off, and upgrade backend through the approved runtime-specific procedure. Confirm API smoke tests and PostgreSQL compatibility before switching static UI.
6. Once legal approval is real and `web/` is clean and committed, build static archive locally, preserve manifest+SHA-256, transfer via approved secure channel, run `install-static-release.sh` under authorized server admin, and verify HTTPS, admin/user routes, JS/CSS, five legal pages, signed auth, event queues and logs. Record deployed SHA and rollback target.

This document is an audit record, not an authorization or executable deployment plan. Production remains unchanged.

## Follow-up: authenticated Termius inspection, 2026-11-21

The user pointed out an **already authenticated** Termius root session (`root@ready-orange`, Ubuntu 24.04.5) to Aeza `82.148.243.63`. Through the existing desktop terminal, **read-only** commands ran successfully. The earlier Windows OpenSSH `Permission denied (publickey)` was a limitation of that separate SSH client, not proof that Aeza was unreachable. Do not report SSH access as universally blocked.

- The legacy unit `the-affiliates-partners-deploy.timer` is **not found**, and its `is-active` reports inactive. No legacy Partners deployment timer was shown in `systemctl list-timers --all` (which did show backup timers). This resolves the specific old-timer concern for the inspected live host, though it is not a complete system audit.
- Actual unit names are `ta-partners-api.service` and `ta-crm-api.service`: both enabled and active. `nginx.service`, `postgresql16-main.service` active. The old `the-affiliates-partners-api.service` was inactive because it is not the production unit.
- `/opt/the-affiliates-partners` contains deployed source without `.git` metadata. The public static path `/var/www/theaffiliates-partners` is a symlink into `/var/www/theaffiliates-partners.releases/7ba7da9b03cb98a6527b8733bf5e91d11ff30938`; no `manifest.json` found in that release. Do not equate its directory name with a verified Git commit without additional evidence.
- `nginx -t` passes. Correct TLS hostname is **`82-148-243-63.sslip.io`**, not `82.148.243.63.sslip.io`. The certificate's CN and SAN both specify the hyphenated hostname and is valid from November 12, 2026 until February 10, 2027. `curl` with certificate verification returns `200` for `/partners/` and `/partners/admin/`, with TLS verification result `0`. `/partners/legal/privacy.html` currently returns **404**: the five new legal pages have not been deployed.
- Local HTTP `127.0.0.1:8788/api/health` returned `200`. `ta-restic-snapshot.timer` is enabled/active; metadata of Restic snapshots includes a recent timestamp of November 21, 2026 04:17 (displayed metadata, not a verified restore). Do not claim backup integrity or recoverability from file presence.
- No production file, service, secret, Git branch, database or deployment was changed in this session. **Release remains blocked** by missing validated legal approval and recovery/device checks; `release_ready=false`. These observations improve readiness knowledge but are not a green-light to bypass fail-closed packaging.
