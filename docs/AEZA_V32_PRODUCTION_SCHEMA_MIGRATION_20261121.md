# The Affiliates Partners v3.2 — выполненная миграция схемы на Aeza (2026-11-21)

## Результат

**Рабочая схема `partners` расширена с 18 до 28 таблиц.** Изменение выполнено на Aeza через авторизованную root-сессию Termius, после успешного восстановления и проверки на временных базах. `deployment/mvp-schema.sql` применён транзакционно через `psql -X -v ON_ERROR_STOP=1` к рабочей базе `the_affiliates`; код выхода `0` и финальный `COMMIT` подтверждены. Схема CRM `public` содержит прежние 33 таблицы, 4 записи `partners.users` сохранены. Старые `ta-partners-api` и `ta-crm-api` остались `active`, `/api/health` — HTTP 200.

## Копия до изменения и проверка восстановления

- Перед production DDL создан свежий полный `pg_dump -Fc` в `/var/backups/the-affiliates/the_affiliates-pre-v32-20261121T002452Z.dump`, приблизительно 354 KB, только root-доступ (`-rw-------`). Проверка `pg_restore --list` прошла.
- Архив **реально восстановлен** в новую временную базу `ta_v32_latest_backup_dryrun_20261121` с сохранением ACL (`pg_restore --exit-on-error --no-owner`). Результат: `FRESH_RESTORE_PASS`.
- На восстановленной копии SQL-миграция прошла (`FRESH_MIGRATION_EXIT=0`), получены 28 таблиц `partners` и 4 записи пользователей. Runtime-роль `ta-partners` выполнила `database.postgres.validate_ready(...)` из нового backend без ошибок (`FRESH_ROLE_VALIDATION_PASS`).
- Дополнительно миграция повторно проверена на предыдущих двух независимых тестовых БД, включая идемпотентность и `prepare_schema --confirm-ddl`. На третьей копии от runtime-роли подтверждены `INSERT`, `UPDATE`, `DELETE` в `partners.finance_withdrawals` внутри транзакции `ROLLBACK` (`DML_PERMISSION_EXIT=0`); тестовые данные не сохранены.
- Все три тестовые БД удалены (`SCRATCH_DATABASES_REMOVED=yes`). Остались только штатные прикладная база `the_affiliates` и служебная `postgres`.

## Backend и CRM

- Локальный пакет backend создан из `server/` и `database/` текущей ветки и передан через Termius SFTP в `/root/_partners_v32_backend_20261121.tar.gz`; SHA-256 совпал по обеим сторонам: `dc71d5b40b8b640d812d4e5cfe4b45f61a0a69e883b437759d851f4b43942910`. Пакет распакован **только во временный staging** `/tmp/ta_v32_backend_staging_20261121`, `compileall` пройден.
- Стандартный `prepare_schema --confirm-ddl` из новой версии успешно отработал на тестовой БД; `validate_ready` пройден на тестовой и затем **на рабочей схеме** от имени `ta-partners` (`LIVE_RUNTIME_SCHEMA_VALIDATED=yes`).
- Сверены два критичных файла CRM-интеграции (`app/models/offer_assignment.py`, `app/modules/partners/outbox.py`): их SHA-256 на Aeza совпали с совместимым локальным CRM worktree. Ранее три проблемных двухсервисных E2E прошли изолированно на одноразовых БД; это не тест реальных платежей/Telegram.
- Новый API запускался **только временно** на `127.0.0.1:8898` с отдельной тестовой БД и без Telegram-секретов. Его health отвечал HTTP 200; без токена запрос к защищённому endpoint ответил HTTP 503. Временный процесс остановлен, порт освобождён. Текущая работающая служба на 8788 не заменялась.
- В рабочем venv нет `cryptography`, а в текущем `.env.local` не задан `PARTNERS_PROFILE_ENCRYPTION_KEY`. Linux wheels успешно загружены в `/tmp/ta_v32_wheels_20261121`, отдельная установка в `/tmp/ta_v32_vendor_20261121` проверена тестовым Fernet encrypt/decrypt. В рабочее venv ничего не устанавливалось, ключ не создавался.

## Почему backend/frontend пока не переключены

**Выявлена несовместимость работающего старого frontend с новой регистрацией**: старая форма содержит один checkbox согласия, а новая реализация API требует дату рождения, четыре счётчика кредитных продуктов, принятие политики и условий и версию документов. Одностороннее обновление backend нарушило бы регистрацию. Нужен согласованный backend+frontend cutover с реальной проверкой и единым rollback-планом.

Статический релиз по-прежнему останавливает `tools/check_legal_release.py`: отсутствует `deployment/legal-approval.json` с подтверждёнными операционными/юридическими условиями. Отменять fail-closed gate или создавать фиктивное утверждение нельзя. Требуются также стабильный секрет Fernet с защищённой внешней копией и контролируемая установка `cryptography` в runtime venv. Реальный Telegram iOS/Android WebView остаётся непроверенным.

## Итоговое состояние

Production затронут **только** явной, проверенной расширяющей миграцией `partners` и созданием новой защищённой резервной копии; CRM `public`, конфигурация, работающий backend, Telegram webhook, Nginx, frontend и GitHub не изменены. Конечные smoke-проверки: `ta-partners-api` active, `ta-crm-api` active, `/partners/` и `/partners/admin/` HTTP 200 с проверенным TLS (`ssl_verify_result=0`). **Полный релиз v3.2 ещё не выполнен.**
