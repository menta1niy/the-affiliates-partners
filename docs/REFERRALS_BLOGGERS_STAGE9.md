# Этап 9/14 — рефералы и блогеры (локально)

## Инварианты

- Обычный реферер с ролью `lead`/`referrer` получает **15% сверх выплаты приглашённого**, исключительно после подтверждённой фактической выплаты (`finance_withdrawals.status='paid'`). Денежная точность — копейки; уникальность начисления задаётся `withdrawal_id`.
- Роли `owner`, `admin`, `staff` и `blogger` исключены из обычных 15% начислений. Реферал, пришедший по блогерской ссылке, остаётся лидом; его рекламный источник не делает его блогером.
- Блогеры имеют отдельную роль, внутренний `B-...` ID, индивидуальную рекламную ссылку, кампанию с фиксированной ставкой и/или процентом, и независимый реестр `blogger_rewards`.
- Процент блогеру начисляется после фактически оплаченного вывода приглашённого. Фиксированная сумма — только после ручного подтверждения реального размещения, с уникальным `placement_reference`. Выдача денег блогеру отдельно отмечается уникальным `payment_reference`.
- Ни неподтверждённые отчёты, ни ручные статусы офферов, ни начисление лида не создают реферального вознаграждения.

## Точки интеграции

- `server/referral.py`, `server/finance.py`, `server/db.py`, `server/api.py`.
- `database/postgres.py` и `deployment/mvp-schema.sql` содержат соответствующие таблицы; SQLite создаёт их локально при обращении.
- Пользовательские данные: `POST /api/finance/overview` (секция `referral`), `POST /api/blogger/overview`.
- Администрирование: `POST /api/admin/bloggers/create|list|update|fixed|paid`.
- Интерфейс: `web/app.js`, `web/admin/admin.js`, соответствующие HTML страницы.

## Проверка

- `python -m unittest tests.test_referral_stage9.Stage9ReferralTests -q`: 2 OK.
- `python -m unittest tests.test_finance_stage8 tests.test_blogger_invites_http tests.test_internal_ids -q`: 28 OK.
- `node --check web/app.js`, `node --check web/admin/admin.js`, `python -m compileall -q server database`, `git diff --check`: без ошибок.

Всё пока локально. Не выполнять push/deploy до завершения 14 этапов и отдельной команды владельца.
