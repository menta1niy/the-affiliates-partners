# Mini App deployment at theaffiliates.ru

Existing website route / must remain unchanged. Mini App: /partners/ and API: /partners/api/.

1. Determine the actual hosting and current routing. GitHub Pages cannot run Python or use Nginx configuration; for that deployment the API must live on a separate hosted service.
2. Build with npm.cmd run build; copy dist/ into isolated /var/www/theaffiliates-partners/ on the correct server.
3. If Nginx is used, inspect the existing TLS server block for conflicting routes and add only locations from nginx-partners.example.conf.
4. Validate with nginx -t, then reload (do not restart) Nginx.
5. Run server/app.py separately with a server-side Telegram token, persistent database, and backup.
6. Verify /, /partners/, /partners/api/health, and /partners/api/offers; the first must remain unchanged.
7. Set MINI_APP_URL to https://theaffiliates.ru/partners/, restart only the bot, configure the URL in BotFather.

The API does not yet connect to CRM. Production offers and tracking links remain disabled until integration.

## GitHub auto-pull (same pattern as main website)

Repository: https://github.com/menta1niy/the-affiliates-partners

The main website uses its own deployment timer. This application has its own **separate** timer and release directory. These steps are for the Beget VPS terminal and must only be run after reading the current server state.

1. Inspect `systemctl cat the-affiliates-deploy.timer` and confirm the existing website timer remains unchanged.
2. If `/opt/the-affiliates-partners` does not exist, run `git clone https://github.com/menta1niy/the-affiliates-partners.git /opt/the-affiliates-partners`.
3. Verify `node --version`, `npm --version`, and `test -e /var/www/theaffiliates-partners`; the last target must either not exist or be a symlink managed by this project.
4. Copy only the two new service files: `cp /opt/the-affiliates-partners/deployment/the-affiliates-partners-deploy.{service,timer} /etc/systemd/system/`.
5. Run `systemctl daemon-reload && systemctl enable --now the-affiliates-partners-deploy.timer` and start the initial build using `systemctl start the-affiliates-partners-deploy.service`.
6. Inspect `systemctl status the-affiliates-partners-deploy.service` and verify `test -s /var/www/theaffiliates-partners/index.html`.

The timer polls GitHub every three minutes; there is no GitHub Actions SSH secret and no modification to the existing website timer. GitHub Actions independently builds every push. Nginx and the Python API are separate activation steps: do not claim full publication until those have been configured and verified.
