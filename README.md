# The Affiliates Partners — clean slate

This is a **new implementation**, independent of the previous CRM integrations,
status database, generated mock statistics, build pipeline, and React/Vite stack.
No old business logic is imported.

## What works

- A fresh responsive HTML/CSS/JavaScript Mini App at `/partners/`.
- Server-side HMAC verification of Telegram Mini App signed `initData`.
- Private profile (name, Telegram ID, owner/partner role).
- Minimal Telegram webhook bot: `/start`, `/app`, `/help`.
- Health check, one API service, automatic release deployment from `main`.

**Not implemented yet:** CRM sync, offers, personal tracking links, partner approval,
revenue, payouts, and reporting. No misleading demonstration data is displayed.

## Minimal configuration

The live private `.env.local` is preserved on the VPS and never committed.
Copy `.env.example` only for a new local setup, then fill:

- `TELEGRAM_BOT_TOKEN` — existing verified BotFather secret.
- `MINI_APP_URL` — HTTPS app link.
- `ADMIN_TELEGRAM_ID` — verified numeric owner Telegram ID.
- `SERVER_PORT` — API port, default 8788.

Old CRM credentials and SQLite data are archived separately and never loaded
by this version.

## Run and test

```bash
python3 -m unittest discover -s tests -v
python3 -m server.api
```

Static files are under `web/`; no `npm install` or build is needed.
Open the HTML only through HTTPS on Telegram to receive signed `initData`.

Telegram commands/menu and HTTPS webhook (dry-run unless `--apply`):

```bash
python3 -m tools.configure_telegram
python3 -m tools.configure_telegram --apply
```

## Deployment

Use existing domain/TLS and the dedicated Partners systemd units. The
Partners-only timer invokes `deployment/deploy.sh` and pulls `main`.
It validates Python tests and the new API on port 8799 before switching
the static symlink. Telegram handles incoming bot updates and executes replies
included in our HTTPS webhook response, without an outbound VPS connection.
The old polling worker is removed. Does not touch the main CRM deployment.

## Backup / rollback

Before reset: archived Git tag `archive/pre-clean-slate-20261031`.
Private full Git bundle, secrets and SQLite snapshot remain on the Windows
computer and under `/root/partners-before-clean-slate-20261031/` on VPS.
Do not publish those files or upload private tokens to GitHub.
