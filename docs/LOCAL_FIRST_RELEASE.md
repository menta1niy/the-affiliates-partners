# Local-first development and Aeza release policy

Editable code and designs are developed and committed locally. GitHub stores reviewed
source history. Aeza runs selected revisions and stores runtime state.

| Location | Intended contents |
|---|---|
| Local Git worktrees | UI, backend, SQL migrations, tests, scripts, documentation |
| GitHub | Source commits and release metadata; no credentials or customer data |
| Aeza | PostgreSQL, runtime credentials, TLS, Nginx/systemd environment |
| Independent backups | Encrypted data snapshots and an independently protected recovery key |

## Mini App release

User and admin pages share the consolidated `web/style.css` and the currently
approved **Rounded Float / Amber v3.2** system: graphite background `#080909`,
surface `#131416`, text `#F7F7F5`, and interactive amber `#E4A34A`.
The four-item participant dock has an icon-only floating mobile layout.

1. Modify source in an isolated local worktree and commit only after checks.
2. Run Python unit tests and JavaScript syntax checks locally.
3. Before a public build, complete the legal/operator approval and local preflight:

       python -m tools.stage13_preflight --require-ready

   This currently fails intentionally: legal approval, disposable PostgreSQL
   restore/privilege checks, real Telegram WebView testing and owner release
   permission remain outstanding. Do not bypass the guard with fake approvals.
4. After approval and explicit owner authorization, build a reproducible static package with:

       python tools/build_static_release.py D:\GPT\_ta-partners-releases

5. Publish a reviewed GitHub branch. Do not auto-deploy feature branches.
6. Transfer only the archive and SHA-256 manifest by SFTP or approved SSH.
   On Aeza, execute deployment/install-static-release.sh with the archive
   path and its exact SHA-256. The installer verifies its contents and
   switches the public static release, preserving the previous files.
7. Verify both HTTPS pages, all JS/CSS assets, Telegram chrome and
   protected API rejection tests.

The existing deployment/deploy.sh targets legacy service names and a
specific database connection layout. It is not approved for the present
Aeza runtime without compatibility review. The current local API services
are ta-crm-api and ta-partners-api. Telegram webhook cutover is separate.

## Backup status

- Aeza creates PostgreSQL dumps and daily encrypted restic snapshots with
  ta-restic-snapshot.timer, set to 04:10 UTC plus randomized delay.
- A manually transferred encrypted snapshot on Windows was independently
  verified with restic check --read-data, restic restore and dump SHA-256.
- An automatic read-only SFTP pull is configured on Windows through the
  TheAffiliates-Aeza-Offsite-Pull scheduled task. The pull checks SHA-256,
  stores up to 14 verified timestamped encrypted archives, and preserves
  the previous archives on transfer failure.
- The standalone PostgreSQL backup timer was disabled on 2026-11-14;
  ta-restic-snapshot.timer requires the PostgreSQL backup service and runs
  it once before each snapshot. Keep the service dependency intact.
- A full PostgreSQL restore from a server-side restic snapshot succeeded
  in a disposable database (49 tables, 102 foreign keys); an independent
  restore from a Windows-downloaded archive remains a separate drill.
- Server-side restic retention has been staged locally and dry-run checked
  (--keep-within 7d, --keep-weekly 4, --keep-monthly 3). It is NOT deployed
  because the live change was blocked before execution.
- Never commit the restic password or put it in Obsidian or console logs.
  Keep a separate secured copy away from the encrypted repository.
- Keep recovery key copies separately protected and periodically test the
  independent Windows archive, retention and restore procedure.
