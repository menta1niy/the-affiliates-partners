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

User and admin pages share web/theme-green.css. The darkest #051F20 is the
main background. #0B2B26 is used for cards, #163832 for inputs,
#235347 for selected/accent bars, #8EB69B for CTA/success, and
#DAF1DE for primary text. Accent bars receive a restrained matte-glass blur.

1. Modify source in an isolated local worktree and commit only after checks.
2. Run Python unit tests and JavaScript syntax checks locally.
3. Build a reproducible static package with:

       python tools/build_static_release.py D:\GPT\_ta-partners-releases

4. Publish a reviewed GitHub branch. Do not auto-deploy feature branches.
5. Transfer only the archive and SHA-256 manifest by SFTP or approved SSH.
   On Aeza, execute deployment/install-static-release.sh with the archive
   path and its exact SHA-256. The installer verifies its contents and
   switches the public static release, preserving the previous files.
6. Verify both HTTPS pages, all JS/CSS assets, Telegram chrome and
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
- Automatic offsite replication is not yet configured. The Windows
  archive is one point-in-time backup, and the daily scheduled snapshots
  still reside on Aeza unless explicitly transferred.
- Never commit the restic password or put it in Obsidian or console logs.
  Keep a separate secured copy away from the encrypted repository.
- Plan a dedicated offsite destination, automated transfer, retention,
  alerts and periodic independent restore drills.
