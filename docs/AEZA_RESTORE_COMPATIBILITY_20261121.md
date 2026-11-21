# Aeza — проверка восстановления и совместимости Partners v3.2 (2026-11-21)

## Ограничения

Проверка проведена в авторизованной пользовательской сессии Termius `root@ready-orange` на Aeza (`82.148.243.63`). Ни работающая база `the_affiliates`, ни работающие службы/файлы, ни GitHub не изменялись. Для восстановления создавались только одноразовые тестовые PostgreSQL-базы; обе удалены после проверки. **Развёртывание не проводилось.**

## Восстановление backup: PASS

- Кластер PostgreSQL 16; единственная прикладная база `the_affiliates`, приблизительно 10 MB. Исходный архив: `/var/backups/the-affiliates/the_affiliates-20261120T041912Z.dump` (последний найденный обычный `.dump`, 362199 B). Архив доступен в формате `pg_restore` и содержит CRM `public` и Partners `partners`.
- Создана уникальная временная БД из `template0`, `pg_restore --exit-on-error --no-owner --no-acl` из указанного архива завершился с `RESTORE_EXIT=0`.
- На **восстановленной**, а не рабочей БД подтверждены `PARTNERS_TABLES=18`, `CRM_TABLES=33`, `PARTNERS_USERS=4`; `RESTORE_CHECK_DONE=yes`. Временная БД удалена (`TEMP_DB_REMOVED=yes`). Предварительный тест также восстановил архив успешно, но его диагностический SQL был некорректно экранирован, поэтому для фактического подтверждения использован второй чистый тест.
- Ограничение: эта проверка не доказывает восстановимость нового снимка Restic, корректность ролей и ACL после восстановления (запущено с `--no-owner --no-acl`), а также сохранение транзакций после времени создания выбранного архива. Не подтверждать RPO/RTO или целостность всех данных лишь по числу таблиц.

## Сверка текущего backend: NOT COMPATIBLE WITHOUT MIGRATION

- Рабочий `ta-partners-api.service` активен, выполняется пользователем `ta-partners` из `/opt/the-affiliates-partners`; внутренний `/api/health` отвечает HTTP 200. CRM API активен. Установленный `/opt/the-affiliates-partners` — директория без `.git` metadata, поэтому точно установленный commit по Git не определяется.
- SHA256 установленных `server/api.py` и `server/db.py` **не совпадают** с локальными файлами релиза `D:\GPT\.partners-green-theme-20261114` commit `44bcaa7`. Это подтверждает отличающийся backend, но само по себе не определяет API-совместимость.
- Живая схема `partners` насчитывает **18 таблиц**, тогда как локальный `database/postgres.py` v3.2 определяет **28 таблиц**. На Aeza отсутствуют: `registration_profiles`, `participant_identities`, `offer_logos`, `manual_offer_events`, `finance_accruals`, `finance_withdrawals`, `referral_rewards`, `blogger_campaigns`, `blogger_attributions`, `blogger_rewards`.
- Уже существуют `manual_offers`, `manual_assignments`, `crm_assigned_offers`, `crm_offer_snapshot_versions`, `crm_registration_outbox`, `participant_task_reports` и другие таблицы старого MVP. Предполагаемое обновление может требовать **не только CREATE TABLE**, но также ALTER TABLE, ограничения/индексы и проверку DML привилегий. Разность списков таблиц не заменяет migration/diff analysis.
- Роли с префиксом `ta-` не имеют атрибутов superuser/createdb/createrole в проверенном выводе. Полный аудит `GRANT` и разделения CRM/Partners не выполнен. Релизное ПО не мигрировалось, неподписанные production API запросы не производились.

## Решение для следующего релизного шага

**NO-GO для прямой замены frontend.** Требуется подготовить совместимый backend rollout с миграцией только схемы `partners`, после чего на изолированной восстановленной базе прогнать миграцию и CRM↔Partners интеграционные проверки. Затем проверить права runtime-роли, backup+rollback, выполнить переход backend/API и только затем ставить статический интерфейс. Отдельно остаётся неизменённый legal release gate; создавать фиктивное согласование нельзя.

По состоянию на этот аудит: **восстановление существующего архивного дампа PASS; совместимость без миграции FAIL; production не изменялся**.

**Последующее изменение 2026-11-21:** описанный разрыв 18→28 таблиц устранён отдельной проверенной миграцией на рабочей `partners` схеме. Это был первоначальный аудит до изменения; актуальное выполненное действие, новый backup и оставшиеся блокировки backend/frontend описаны в `docs/AEZA_V32_PRODUCTION_SCHEMA_MIGRATION_20261121.md`.
