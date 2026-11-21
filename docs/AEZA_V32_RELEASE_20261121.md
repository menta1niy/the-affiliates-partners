# The Affiliates Partners v3.2 — production cutover, 2026-11-21

## Статус

**Backend + frontend установлены на Aeza** через авторизованную сессию Termius, с отдельной проверкой SHA-256 архивов и сохранённой точкой отката. Установленная сборка основана на Git commit `11f8c8c3099782421547939611ad44b0362df555` (branch `feature/green-theme-20261114`). CRM backend не изменялся.

Оговорка: юридические документы пользователь подтвердил в чате как владелец, но государственная проверка предоставленных реквизитов остаётся ожидающей; `deployment/legal-approval.json` намеренно содержит `registry_verification=pending`, `release_ready=false` и список неподтверждённых операционных условий. Факт технического выпуска **не является заявлением о полной юридической готовности**.

## Архивы и версия

- Backend: `/root/_partners_v32_backend_11f8c8c.tar.gz`, SHA-256 `4aefc03c50a93ebd54747e18dc8e9f287c54561f588b5030486052c0b649ac53`.
- Static: `/root/_partners_v32_web_11f8c8c.tar.gz`, SHA-256 `710bc974071976e120eaff148ebba7e572af3ec592fde3eb15619b281a2a10bf`.
- Installer: `/root/_partners_v32_install_static_11f8c8c.sh`, SHA-256 `0de7e33c90a655f6b482cd77a877b47492aaa32fef844fa0fe587e268d9891c1`.
- Backend `server/`, `database/` обновлены по отдельности через `rsync -a --delete` в `/opt/the-affiliates-partners/` после проверки архивов и `compileall`. `.env.local`, CRM, статика и другие каталоги не перезаписывались.
- Статический установщик сообщил `VALIDATED_COMMIT 11f8c8c3099782421547939611ad44b0362df555`, `STATIC_RELEASE_ACTIVE` с тем же SHA и `STATIC_INSTALL_EXIT=0`; новый каталог `/var/www/theaffiliates-partners.releases/11f8c8c3099782421547939611ad44b0362df555` подключён через символьную ссылку `/var/www/theaffiliates-partners`.

## Ключ и конфигурация

- `cryptography==50.0.2` установлена в `/opt/the-affiliates-partners/.venv` из проверенных Linux wheels; Fernet encrypt/decrypt прошёл.
- Новый постоянный `PARTNERS_PROFILE_ENCRYPTION_KEY` сгенерирован непосредственно на Aeza, не выводился в терминал или чат. Основное хранение — `/etc/the-affiliates-partners/partners.env` (mode `0640`, `root:ta-partners`), резервная защищённая копия — `/etc/the-affiliates-partners/partners.env.v32-key-recovery` (mode `0600`). Каталог входит в зашифрованный Restic snapshot: ручной `systemctl start ta-restic-snapshot.service` завершился с `Result=success`, `ExecMainStatus=0`.
- Настроены `PARTNERS_LEGAL_APPROVED_VERSION=partners-legal-v2-2026-11`, `PARTNERS_REQUIRE_APPROVED_LEGAL=true` и `PARTNERS_MVP_OPEN_REGISTRATION=true`. Проверка окружения **работающего PID** `ta-partners-api` подтвердила все три флага и работоспособность Fernet без раскрытия ключа.
- Бот `@affialite_partners_bot`: через Telegram Bot API `getMe` подтверждён username, webhook ранее был не задан; теперь `setWebhook` выполнен с секретом `X-Telegram-Bot-Api-Secret-Token`, вычисленным через `server.settings.webhook_secret()`. Telegram `getWebhookInfo`: `WEBHOOK_ACTIVE=True`, URL path `/partners/api/telegram/webhook`, pending updates `0`, `LAST_ERROR_PRESENT=False`. Существующие updates не удалялись.

## Smoke-проверки

- `ta-partners-api`, `ta-crm-api`, `nginx` — `active`. Partners `/api/health` — HTTP 200. Сразу после запуска новая служба кратковременно ещё не слушала порт 8788 (первый curl получил 000), но повторная проверка и journal подтвердили успешную готовность, без рестартов; после этого установлен frontend.
- `https://82-148-243-63.sslip.io/partners/`, `/partners/admin/`, `/partners/app.js`, `/partners/style.css`, все пять URL `/partners/legal/*.html` — HTTP **200**, `ssl_verify_result=0`.
- Без подписанного Telegram initData запросы `/api/session` и `/api/finance/overview` — HTTP **401**. Публичный Telegram webhook без секретного заголовка — HTTP **403**.
- CRM `http://127.0.0.1:8000/api/v1/health` — HTTP **200**. После релиза журнал `ta-partners-api` и `ta-crm-api` не показал warning-событий в исследованном диапазоне.
- В БД `partners` — 28 таблиц (миграция и проверенное восстановление описаны в `docs/AEZA_V32_PRODUCTION_SCHEMA_MIGRATION_20261121.md`), CRM `public` — 33 таблицы. Изолированные тестовые БД удалены.

## Откат

- Точка отката backend: `/root/ta-v32-rollback-11f8c8c/server` и `/root/ta-v32-rollback-11f8c8c/database`; исходное состояние файла service env: `/root/ta-v32-rollback-11f8c8c/partners.env.before` (содержит секреты, не отправлять в Git); предыдущий frontend symlink target сохранён в `/root/ta-v32-rollback-11f8c8c/static.previous`.
- При ошибке сначала вернуть **совместимую пару** frontend/backend: атомарно переставить `/var/www/theaffiliates-partners` на предыдущий release, остановить `ta-partners-api`, `rsync -a --delete` из rollback директорий в `/opt/the-affiliates-partners/server` и `/opt/the-affiliates-partners/database`, восстановить согласованные env-флаги из резервной копии (только после проверки новых персональных данных и возможной необходимости ключа), запустить API, проверить health. Не выполнять автоматический rollback PostgreSQL, не удалять новые пользовательские/финансовые записи и не терять новый ключ Fernet, если после релиза появились зашифрованные данные.

## Что осталось проверить отдельно

1. Полноценный вход и регистрация из **реального Telegram WebView на iPhone/Android**, выдача офферов, роли, выплаты и открытие документов. Desktop/локальные браузерные тесты не заменяют этот шаг.
2. Полный финансовый путь и уведомления в реальном Telegram: webhook активен, но реальный пользовательский `/start` и подтверждённая выплата в рамках этого cutover не тестировались.
3. CRM интеграция: CRM API активен и здоров, но на момент проверки **`public.workspaces=0`, `public.leads=0`, `partners.crm_registration_outbox=0`**, переменная `PARTNERS_CRM_WORKSPACE_ID` не установлена. Автономная Mini App функционирует, однако нельзя заявлять, что исходящие регистрации доставляются в CRM. Не создавать искусственный Team workspace без отдельного решения владельца.
4. Официальная проверка реквизитов, фактические сроки хранения/удаления, порядок выплат и условия участия несовершеннолетних, перечисленные в `deployment/legal-approval.json`, остаются не подтверждены государственным реестром/отдельным документированием.

GitHub push и реальный мобильный WebView smoke вынесены в отдельную проверку после технического cutover; не считать их выполненными без фактического результата.
