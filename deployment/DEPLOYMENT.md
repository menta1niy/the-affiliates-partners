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
