"""Standalone participant finance: verified accruals, reserved withdrawals.

Offer rates, lead reports, and manual completion NEVER create accruals.
All money is integral rubles and every mutation is a serialized transaction.
"""
import re
import secrets
import time

from server import db, mvp

WITHDRAWAL_ID = re.compile(r"^wd_[0-9a-f]{24}$")
REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{3,119}$")
MAX_RUB = 10_000_000


def schema(conn):
    if db.postgres_url():
        return
    mvp.schema(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS finance_accruals (
        id TEXT PRIMARY KEY,
        telegram_id INTEGER NOT NULL REFERENCES users(id),
        offer_id TEXT NOT NULL REFERENCES manual_offers(id),
        amount_rub INTEGER NOT NULL CHECK(amount_rub>0),
        source_reference TEXT NOT NULL UNIQUE,
        note TEXT NOT NULL DEFAULT '',
        confirmed_by INTEGER NOT NULL REFERENCES users(id),
        created_at INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_finance_accruals_user ON finance_accruals(telegram_id,created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS finance_withdrawals (
        id TEXT PRIMARY KEY,
        telegram_id INTEGER NOT NULL REFERENCES users(id),
        amount_rub INTEGER NOT NULL CHECK(amount_rub>0),
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK(status IN ('pending','confirmed','rejected','paid')),
        review_note TEXT NOT NULL DEFAULT '',
        payment_reference TEXT NOT NULL DEFAULT '',
        reviewed_by INTEGER REFERENCES users(id),
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_finance_withdrawals_user ON finance_withdrawals(telegram_id,created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_finance_withdrawals_status ON finance_withdrawals(status,created_at)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_finance_withdrawals_payment_ref "
                 "ON finance_withdrawals(payment_reference) WHERE payment_reference!=''")
    from server import referral
    referral.schema(conn)


def _amount(value):
    if type(value) is not int or not 1 <= value <= MAX_RUB:
        raise db.Problem(400, "Сумма должна быть целым числом рублей от 1 до 10 000 000")
    return value


def _target(conn, staff, target_id):
    if type(target_id) is not int or target_id <= 0:
        raise db.Problem(400, "Некорректный участник")
    target = db.get_user(conn, target_id)
    db.permitted_target(conn, staff, target)
    if target["role"] not in ("lead", "referrer") or target["status"] != "active":
        raise db.Problem(409, "Аккаунт участника неактивен")
    return target


def _balances(conn, target_id):
    from server import referral
    referral.schema(conn)
    total = conn.execute("SELECT COALESCE(SUM(amount_rub),0) FROM finance_accruals WHERE telegram_id=?",
                         (target_id,)).fetchone()[0]
    referral_kopeks = conn.execute("SELECT COALESCE(SUM(amount_kopeks),0) FROM referral_rewards "
                                  "WHERE referrer_id=?", (target_id,)).fetchone()[0]
    paid = conn.execute("SELECT COALESCE(SUM(amount_rub),0) FROM finance_withdrawals "
                        "WHERE telegram_id=? AND status='paid'", (target_id,)).fetchone()[0]
    reserved = conn.execute("SELECT COALESCE(SUM(amount_rub),0) FROM finance_withdrawals "
                            "WHERE telegram_id=? AND status IN ('pending','confirmed')",
                            (target_id,)).fetchone()[0]
    available_kopeks = total * 100 + referral_kopeks - (paid + reserved) * 100
    available = available_kopeks // 100
    if min(total, paid, reserved, available_kopeks) < 0:
        raise db.Problem(503, "Нарушена целостность финансового баланса")
    return {"accrued_rub": total + referral_kopeks // 100, "paid_rub": paid,
            "reserved_rub": reserved, "available_rub": available}


def _public_withdrawal(row):
    return {key: row[key] for key in ("id","amount_rub","status","review_note",
                                     "created_at","updated_at")}


def _public_accrual(row):
    return {key: row[key] for key in ("id","offer_id","amount_rub",
                                     "source_reference","created_at")}


def overview(actor, owner_id, data):
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active" or user["role"] not in ("lead", "referrer"):
            raise db.Problem(403, "Финансы доступны подтверждённому участнику")
        balances = _balances(conn, actor)
        accruals = conn.execute("SELECT * FROM finance_accruals WHERE telegram_id=? "
                                "ORDER BY created_at DESC,id DESC LIMIT 100",(actor,)).fetchall()
        withdrawals = conn.execute("SELECT * FROM finance_withdrawals WHERE telegram_id=? "
                                   "ORDER BY created_at DESC,id DESC LIMIT 100",(actor,)).fetchall()
        from server import referral
        return {"balances": balances, "accruals":[_public_accrual(row) for row in accruals],
                "withdrawals":[_public_withdrawal(row) for row in withdrawals],
                "referral": referral.referral_view(conn, actor)}


def accrue(actor, owner_id, data):
    """Explicit independently verified record, never generated from lead stages."""
    target_id = data.get("user_id")
    offer_id = data.get("offer_id")
    amount = _amount(data.get("amount_rub"))
    reference = data.get("source_reference")
    note = data.get("note","")
    if not isinstance(offer_id,str) or not mvp.OFFER_ID.fullmatch(offer_id):
        raise db.Problem(400,"Некорректный оффер")
    if not isinstance(reference,str) or not REFERENCE.fullmatch(reference):
        raise db.Problem(400,"Укажите уникальный идентификатор подтверждённого начисления")
    if not isinstance(note,str) or len(note)>300:
        raise db.Problem(400,"Некорректный комментарий")
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        staff = db.require_staff(conn,actor,owner_id)
        if staff["role"] not in ("owner","admin"):
            raise db.Problem(403,"Начисления подтверждаются только администратором")
        _target(conn,staff,target_id)
        if not conn.execute("SELECT 1 FROM manual_assignments WHERE telegram_id=? AND offer_id=?",
                            (target_id,offer_id)).fetchone():
            raise db.Problem(409,"Оффер не назначен участнику")
        existing = conn.execute("SELECT id FROM finance_accruals WHERE source_reference=?",
                                (reference,)).fetchone()
        if existing:
            raise db.Problem(409,"Начисление с таким идентификатором уже существует")
        now=int(time.time())
        acc_id="ac_"+secrets.token_hex(12)
        conn.execute("INSERT INTO finance_accruals(id,telegram_id,offer_id,amount_rub,"
                     "source_reference,note,confirmed_by,created_at) VALUES(?,?,?,?,?,?,?,?)",
                     (acc_id,target_id,offer_id,amount,reference,note.strip(),actor,now))
        db.audit(conn,actor,"finance_accrual_confirmed",target_id,"accrual="+acc_id)
        db.enqueue(conn,"finance_accrual:"+acc_id,target_id,
                   "The Affiliates Partners\nПодтверждено начисление: "+str(amount)+" ₽.\n"
                   "Средства доступны для запроса выплаты.")
        return {"created":True,"accrual_id":acc_id,"balances":_balances(conn,target_id)}


def request(actor, owner_id, data):
    amount = _amount(data.get("amount_rub"))
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        user=db.get_user(conn,actor)
        if not user or user["status"]!="active" or user["role"] not in ("lead","referrer"):
            raise db.Problem(403,"Заявки доступны только подтверждённым участникам")
        if not conn.execute("SELECT 1 FROM participant_identities WHERE telegram_id=?",(actor,)).fetchone():
            raise db.Problem(409,"Сначала заполните ФИО и ИНН в профиле")
        balances=_balances(conn,actor)
        if amount>balances["available_rub"]:
            raise db.Problem(409,"Недостаточно доступных средств")
        now=int(time.time())
        withdrawal_id="wd_"+secrets.token_hex(12)
        conn.execute("INSERT INTO finance_withdrawals(id,telegram_id,amount_rub,status,created_at,updated_at) "
                     "VALUES(?,?,?,'pending',?,?)",(withdrawal_id,actor,amount,now,now))
        db.audit(conn,actor,"finance_withdrawal_requested",actor,"withdrawal="+withdrawal_id)
        recipients={owner_id}
        if user["manager_id"]:
            recipients.add(user["manager_id"])
        for recipient in recipients:
            db.enqueue(conn,"withdrawal:review:"+withdrawal_id+":"+str(recipient),recipient,
                       "The Affiliates Partners\nНовая заявка на выплату.\n"
                       "Внутренний ID: L-"+str(user["internal_id"]).zfill(6)+".")
        db.enqueue(conn,"withdrawal:pending:"+withdrawal_id,actor,
                   "The Affiliates Partners\nВаша заявка на выплату "+str(amount)+" ₽ "
                   "отправлена и находится на рассмотрении.")
        return {"withdrawal":{"id":withdrawal_id,"amount_rub":amount,"status":"pending"},
                "balances":_balances(conn,actor)}


def queue(actor, owner_id, data):
    status=data.get("status","pending")
    if status not in ("pending","confirmed","rejected","paid","all"):
        raise db.Problem(400,"Некорректный фильтр")
    db.initialize()
    with db.transaction() as conn:
        staff=db.require_staff(conn,actor,owner_id)
        schema(conn)
        conditions=[]
        params=[]
        agency=db.admin_agency(staff)
        if agency is not None:
            conditions.append("u.agency_id=?")
            params.append(agency)
        if staff["role"]=="staff":
            conditions.append("u.manager_id=?")
            params.append(actor)
        if status!="all":
            conditions.append("w.status=?")
            params.append(status)
        where="WHERE "+" AND ".join(conditions) if conditions else ""
        rows=conn.execute("SELECT w.*,u.internal_id FROM finance_withdrawals w "
                          "JOIN users u ON u.id=w.telegram_id "+where+
                          " ORDER BY w.created_at DESC,w.id DESC LIMIT 100",tuple(params)).fetchall()
        return {"withdrawals":[{**_public_withdrawal(row),"user_id":row["telegram_id"],
                               "display_id":"L-"+str(row["internal_id"]).zfill(6)}
                              for row in rows]}


def decide(actor, owner_id, data):
    withdrawal_id=data.get("withdrawal_id")
    decision=data.get("decision")
    note=data.get("note","")
    payment_ref=data.get("payment_reference","")
    if not isinstance(withdrawal_id,str) or not WITHDRAWAL_ID.fullmatch(withdrawal_id):
        raise db.Problem(400,"Некорректная заявка")
    if decision not in ("confirm","reject","paid") or not isinstance(note,str) or len(note)>300:
        raise db.Problem(400,"Некорректное решение")
    if decision=="reject" and not note.strip():
        raise db.Problem(400,"Укажите причину отклонения")
    if decision=="paid" and (not isinstance(payment_ref,str) or not REFERENCE.fullmatch(payment_ref)):
        raise db.Problem(400,"Нужен идентификатор фактически выполненного платежа")
    db.initialize()
    with db.transaction() as conn:
        staff=db.require_staff(conn,actor,owner_id)
        if staff["role"] not in ("owner","admin"):
            raise db.Problem(403,"Подтверждение выплат доступно только администрации")
        schema(conn)
        row=conn.execute("SELECT * FROM finance_withdrawals WHERE id=?",(withdrawal_id,)).fetchone()
        if row is None:
            raise db.Problem(404,"Заявка не найдена")
        _target(conn,staff,row["telegram_id"])
        allowed={"pending":{"confirm":"confirmed","reject":"rejected"},
                 "confirmed":{"paid":"paid","reject":"rejected"}}
        next_status=allowed.get(row["status"],{}).get(decision)
        if not next_status:
            raise db.Problem(409,"Переход статуса недоступен")
        if decision=="paid" and conn.execute("SELECT 1 FROM finance_withdrawals "
                         "WHERE payment_reference=? AND id!=?",(payment_ref,withdrawal_id)).fetchone():
            raise db.Problem(409,"Платёж с таким идентификатором уже учтён")
        now=int(time.time())
        conn.execute("UPDATE finance_withdrawals SET status=?,review_note=?,"
                     "payment_reference=?,reviewed_by=?,updated_at=? WHERE id=?",
                     (next_status,note.strip(),payment_ref if decision=="paid" else "",
                      actor,now,withdrawal_id))
        if next_status == "paid":
            from server import referral
            referral.on_paid(conn, db.get_user(conn,row["telegram_id"]), row)
        _balances(conn,row["telegram_id"])
        db.audit(conn,actor,"finance_withdrawal_"+next_status,row["telegram_id"],
                 "withdrawal="+withdrawal_id)
        status_labels={"confirmed":"подтверждена","rejected":"отклонена","paid":"выплачена"}
        db.enqueue(conn,"withdrawal:decision:"+withdrawal_id+":"+next_status,
                   row["telegram_id"],"The Affiliates Partners\nВаша заявка на выплату "+str(row["amount_rub"])+
                   " ₽ "+status_labels[next_status]+"."+
                   ("\nПричина: "+note.strip() if next_status=="rejected" else ""))
        return {"changed":True,"withdrawal_id":withdrawal_id,
                "status":next_status,"balances":_balances(conn,row["telegram_id"])}
