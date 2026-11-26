"""Attribution-aware referral rewards and separate blogger advertising accounts.

Neither lead reports nor offer rates create rewards. Exactly one reward can
originate from a genuinely paid withdrawal. Kopeks preserve the exact 15%.
"""
import secrets
import time
import uuid

from server import db


def schema(conn):
    if db.postgres_url():
        return
    conn.execute("""CREATE TABLE IF NOT EXISTS referral_rewards (
        withdrawal_id TEXT PRIMARY KEY REFERENCES finance_withdrawals(id),
        referrer_id INTEGER NOT NULL REFERENCES users(id),
        referred_id INTEGER NOT NULL REFERENCES users(id),
        amount_kopeks INTEGER NOT NULL CHECK(amount_kopeks>0),
        created_at INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_referral_rewards_referrer "
                 "ON referral_rewards(referrer_id,created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS blogger_campaigns (
        blogger_uuid TEXT PRIMARY KEY REFERENCES crm_bloggers(blogger_uuid),
        telegram_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        fixed_rub INTEGER NOT NULL DEFAULT 0 CHECK(fixed_rub>=0),
        percent_bps INTEGER NOT NULL DEFAULT 0 CHECK(percent_bps BETWEEN 0 AND 10000),
        active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS blogger_attributions (
        telegram_id INTEGER PRIMARY KEY REFERENCES users(id),
        blogger_uuid TEXT NOT NULL REFERENCES crm_bloggers(blogger_uuid),
        created_at INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_blogger_attributions_uuid "
                 "ON blogger_attributions(blogger_uuid,created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS blogger_rewards (
        id TEXT PRIMARY KEY,
        blogger_uuid TEXT NOT NULL REFERENCES blogger_campaigns(blogger_uuid),
        kind TEXT NOT NULL CHECK(kind IN ('fixed','percent')),
        source_reference TEXT NOT NULL UNIQUE,
        amount_kopeks INTEGER NOT NULL CHECK(amount_kopeks>0),
        status TEXT NOT NULL DEFAULT 'earned' CHECK(status IN ('earned','paid')),
        payment_reference TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL, paid_at INTEGER
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_blogger_rewards_uuid "
                 "ON blogger_rewards(blogger_uuid,created_at)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_blogger_rewards_payment_ref "
                 "ON blogger_rewards(payment_reference) WHERE payment_reference!=''")


def on_paid(conn, participant, withdrawal):
    """Called inside the same transaction as marking a withdrawal paid."""
    schema(conn)
    referrer_id = participant["referrer_id"]
    if participant["source"] == "referral" and referrer_id and referrer_id != participant["id"]:
        referrer = db.get_user(conn, referrer_id)
        # Agency, staff, owner and admin links never receive 15%.
        if referrer and referrer["role"] in ("lead", "referrer") and referrer["status"] == "active":
            amount_kopeks = withdrawal["amount_rub"] * 15
            now = int(time.time())
            conn.execute("INSERT INTO referral_rewards(withdrawal_id,referrer_id,referred_id,"
                         "amount_kopeks,created_at) VALUES(?,?,?,?,?)",
                         (withdrawal["id"], referrer_id, participant["id"], amount_kopeks, now))
            db.audit(conn, participant["id"], "referral_reward_earned", referrer_id,
                     "withdrawal=" + withdrawal["id"])
            db.enqueue(conn, "referral:earned:" + withdrawal["id"], referrer_id,
                       "The Affiliates Partners\nВаш реферал получил выплату " +
                       str(withdrawal["amount_rub"]) + " ₽.\nВам начислено " +
                       f"{amount_kopeks // 100},{amount_kopeks % 100:02d} ₽ (15%). " +
                       "Вы можете запросить вывод доступных средств в профиле.")
    if participant["source"] != "blogger":
        return
    attribution = conn.execute("SELECT blogger_uuid FROM blogger_attributions WHERE telegram_id=?",
                               (participant["id"],)).fetchone()
    if not attribution:
        return
    campaign = conn.execute("SELECT * FROM blogger_campaigns WHERE blogger_uuid=? AND active=1",
                            (attribution["blogger_uuid"],)).fetchone()
    if not campaign or campaign["percent_bps"] <= 0:
        return
    amount_kopeks = withdrawal["amount_rub"] * campaign["percent_bps"] // 100
    if amount_kopeks < 1:
        return
    reward_id = "br_" + secrets.token_hex(12)
    conn.execute("INSERT INTO blogger_rewards(id,blogger_uuid,kind,source_reference,"
                 "amount_kopeks,created_at) VALUES(?,?,'percent',?,?,?)",
                 (reward_id, campaign["blogger_uuid"], "withdrawal:" + withdrawal["id"],
                  amount_kopeks, int(time.time())))
    db.audit(conn, participant["id"], "blogger_percent_earned", campaign["telegram_id"],
             "withdrawal=" + withdrawal["id"])
    db.enqueue(conn, "blogger:earned:" + reward_id, campaign["telegram_id"],
               "The Affiliates Partners\nПодтверждено процентное рекламное начисление: " +
               f"{amount_kopeks // 100},{amount_kopeks % 100:02d} ₽.")


def referral_view(conn, actor):
    schema(conn)
    count = conn.execute("SELECT COUNT(*) FROM users WHERE source='referral' AND referrer_id=?",
                         (actor,)).fetchone()[0]
    total = int(conn.execute("SELECT COALESCE(SUM(amount_kopeks),0) FROM referral_rewards "
                         "WHERE referrer_id=?", (actor,)).fetchone()[0])
    rows = conn.execute("SELECT r.amount_kopeks,r.created_at,u.internal_id FROM referral_rewards r "
                        "JOIN users u ON u.id=r.referred_id WHERE r.referrer_id=? "
                        "ORDER BY r.created_at DESC,r.withdrawal_id DESC LIMIT 100", (actor,)).fetchall()
    return {"invited_count": count, "earned_kopeks": total,
            "rewards": [{"amount_kopeks": row["amount_kopeks"],
                         "referred_display_id": "L-" + str(row["internal_id"]).zfill(6),
                         "created_at": row["created_at"]} for row in rows]}


def blogger_create(actor, owner_id, data):
    """Owner binds a *new* Telegram identity to a dedicated B-ID and ad link."""
    telegram_id = data.get("telegram_id")
    channel = data.get("channel")
    fixed = data.get("fixed_rub", 0)
    percent = data.get("percent_bps", 0)
    if type(telegram_id) is not int or telegram_id <= 0:
        raise db.Problem(400, "Укажите Telegram ID блогера")
    if not isinstance(channel, str) or not 2 <= len(channel.strip()) <= 120:
        raise db.Problem(400, "Укажите название канала")
    if type(fixed) is not int or not 0 <= fixed <= 10_000_000:
        raise db.Problem(400, "Некорректная фиксированная ставка")
    if type(percent) is not int or not 0 <= percent <= 10_000:
        raise db.Problem(400, "Некорректная процентная ставка")
    if fixed == 0 and percent == 0:
        raise db.Problem(400, "Укажите фиксированную и/или процентную ставку")
    db.initialize()
    with db.transaction() as conn:
        db.require_staff(conn, actor, owner_id)
        if db.get_user(conn, telegram_id):
            raise db.Problem(409, "Telegram-аккаунт уже занят")
        if conn.execute("SELECT 1 FROM crm_bloggers WHERE LOWER(channel)=LOWER(?)",
                        (channel.strip(),)).fetchone():
            raise db.Problem(409, "Канал уже используется")
        schema(conn)
        now = int(time.time())
        internal = db.allocate_internal_id(conn)
        blogger_uuid = str(uuid.uuid4())
        conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,agency_id,"
                     "registered_at,updated_at) VALUES(?,?,?,'blogger','active',?,?,?)",
                     (telegram_id, internal, "Блогер", owner_id, now, now))
        conn.execute("INSERT INTO crm_bloggers(blogger_uuid,channel,issuer_id,active) VALUES(?,?,?,1)",
                     (blogger_uuid, channel.strip(), owner_id))
        conn.execute("INSERT INTO blogger_campaigns(blogger_uuid,telegram_id,fixed_rub,percent_bps,"
                     "created_at,updated_at) VALUES(?,?,?,?,?,?)",
                     (blogger_uuid, telegram_id, fixed, percent, now, now))
        db.audit(conn, actor, "blogger_registered", telegram_id,
                 "blogger_uuid=" + blogger_uuid)
        # Blogger ad codes are owned by the real owner identity because
        # source validation binds CRM campaigns to that identity. The staff
        # operator remains recorded as the creator in the audit trail.
        code = db.new_invitation_code(conn)
        conn.execute("INSERT INTO invitations(code,kind,issuer_id,created_at,blogger_uuid) "
                     "VALUES(?,'blogger',?,?,?)", (code, owner_id, now, blogger_uuid))
        db.audit(conn, actor, "invite_blogger", owner_id, "blogger_uuid=" + blogger_uuid)
        db.enqueue(conn, "blogger:created:" + blogger_uuid, telegram_id,
                   "The Affiliates Partners\nДля вас создан блогерский кабинет. "
                   "Ваш внутренний ID: B-" + str(internal).zfill(6) + ".")
    return {"blogger_uuid": blogger_uuid, "display_id": "B-" + str(internal).zfill(6),
            "channel": channel.strip(), "fixed_rub": fixed, "percent_bps": percent,
            "invite_code": code}


def blogger_view(actor, owner_id, data):
    db.initialize()
    with db.transaction() as conn:
        schema(conn)
        user = db.get_user(conn, actor)
        if not user or user["role"] != "blogger" or user["status"] != "active":
            raise db.Problem(403, "Кабинет доступен блогеру")
        campaign = conn.execute("SELECT c.*,b.channel FROM blogger_campaigns c "
                                "JOIN crm_bloggers b ON b.blogger_uuid=c.blogger_uuid "
                                "WHERE c.telegram_id=?", (actor,)).fetchone()
        if not campaign:
            raise db.Problem(404, "Кампания не найдена")
        invite = conn.execute("SELECT code FROM invitations WHERE kind='blogger' "
                              "AND blogger_uuid=? AND active=1 ORDER BY created_at LIMIT 1",
                              (campaign["blogger_uuid"],)).fetchone()
        invited = conn.execute("SELECT COUNT(*) FROM blogger_attributions WHERE blogger_uuid=?",
                               (campaign["blogger_uuid"],)).fetchone()[0]
        earned = int(conn.execute("SELECT COALESCE(SUM(amount_kopeks),0) FROM blogger_rewards "
                              "WHERE blogger_uuid=?", (campaign["blogger_uuid"],)).fetchone()[0])
        paid = int(conn.execute("SELECT COALESCE(SUM(amount_kopeks),0) FROM blogger_rewards "
                            "WHERE blogger_uuid=? AND status='paid'",
                            (campaign["blogger_uuid"],)).fetchone()[0])
        rows = conn.execute("SELECT id,kind,amount_kopeks,status,created_at FROM blogger_rewards "
                            "WHERE blogger_uuid=? ORDER BY created_at DESC,id DESC LIMIT 100",
                            (campaign["blogger_uuid"],)).fetchall()
        return {"display_id": db.public_user(user)["display_id"], "channel": campaign["channel"],
                "fixed_rub": campaign["fixed_rub"], "percent_bps": campaign["percent_bps"],
                "active": bool(campaign["active"]), "invited_count": invited,
                "earned_kopeks": earned, "paid_kopeks": paid,
                "available_kopeks": earned - paid,
                "invite_code": invite["code"] if invite else "",
                "rewards": [dict(row) for row in rows]}


def blogger_list(actor, owner_id, data):
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        rows = conn.execute("SELECT c.*,b.channel,u.internal_id FROM blogger_campaigns c "
                            "JOIN crm_bloggers b ON b.blogger_uuid=c.blogger_uuid "
                            "JOIN users u ON u.id=c.telegram_id " +
                            " ORDER BY c.created_at DESC LIMIT 100",
                            ()).fetchall()
        result = []
        for row in rows:
            invite = conn.execute("SELECT code FROM invitations WHERE blogger_uuid=? "
                                  "AND kind='blogger' AND active=1 ORDER BY created_at LIMIT 1",
                                  (row["blogger_uuid"],)).fetchone()
            rewards = conn.execute("SELECT id,kind,amount_kopeks,status FROM blogger_rewards "
                                   "WHERE blogger_uuid=? ORDER BY created_at DESC,id DESC LIMIT 50",
                                   (row["blogger_uuid"],)).fetchall()
            result.append({"blogger_uuid": row["blogger_uuid"],
                           "telegram_id": row["telegram_id"], "channel": row["channel"],
                           "display_id": "B-" + str(row["internal_id"]).zfill(6),
                           "fixed_rub": row["fixed_rub"], "percent_bps": row["percent_bps"],
                           "active": bool(row["active"]), "invite_code": invite["code"] if invite else "",
                           "rewards": [dict(reward) for reward in rewards]})
        return {"bloggers": result}


def blogger_update(actor, owner_id, data):
    blogger_uuid = data.get("blogger_uuid")
    fixed = data.get("fixed_rub")
    percent = data.get("percent_bps")
    active = data.get("active")
    if not isinstance(blogger_uuid, str) or not db.BLOGGER_UUID.fullmatch(blogger_uuid):
        raise db.Problem(400, "Некорректный блогер")
    if type(fixed) is not int or not 0 <= fixed <= 10_000_000:
        raise db.Problem(400, "Некорректная фиксированная ставка")
    if type(percent) is not int or not 0 <= percent <= 10_000:
        raise db.Problem(400, "Некорректная процентная ставка")
    if type(active) is not bool:
        raise db.Problem(400, "Некорректный статус кампании")
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        row = conn.execute("SELECT telegram_id FROM blogger_campaigns WHERE blogger_uuid=?",
                           (blogger_uuid,)).fetchone()
        if not row:
            raise db.Problem(404, "Кампания не найдена")
        conn.execute("UPDATE blogger_campaigns SET fixed_rub=?,percent_bps=?,active=?,updated_at=? "
                     "WHERE blogger_uuid=?", (fixed, percent, int(active), int(time.time()), blogger_uuid))
        conn.execute("UPDATE crm_bloggers SET active=? WHERE blogger_uuid=?",
                     (int(active), blogger_uuid))
        db.audit(conn, actor, "blogger_terms_updated", row["telegram_id"],
                 "blogger_uuid=" + blogger_uuid)
        return {"updated": True}


def fixed_earned(actor, owner_id, data):
    """Owner confirms an actual placement before accruing the fixed tariff."""
    blogger_uuid = data.get("blogger_uuid")
    reference = data.get("placement_reference")
    if not isinstance(blogger_uuid, str) or not db.BLOGGER_UUID.fullmatch(blogger_uuid):
        raise db.Problem(400, "Некорректный блогер")
    if not isinstance(reference, str) or not 4 <= len(reference) <= 120 or not reference.isascii():
        raise db.Problem(400, "Укажите идентификатор размещения")
    from server.finance import REFERENCE
    if not REFERENCE.fullmatch(reference):
        raise db.Problem(400, "Некорректный идентификатор размещения")
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        campaign = conn.execute("SELECT * FROM blogger_campaigns WHERE blogger_uuid=? AND active=1",
                                (blogger_uuid,)).fetchone()
        if not campaign:
            raise db.Problem(404, "Кампания не найдена")
        if campaign["fixed_rub"] < 1:
            raise db.Problem(409, "У блогера нет фиксированной ставки")
        if conn.execute("SELECT 1 FROM blogger_rewards WHERE source_reference=?",
                        ("placement:" + reference,)).fetchone():
            raise db.Problem(409, "Размещение уже учтено")
        now = int(time.time())
        reward_id = "br_" + secrets.token_hex(12)
        conn.execute("INSERT INTO blogger_rewards(id,blogger_uuid,kind,source_reference,"
                     "amount_kopeks,created_at) VALUES(?,?,'fixed',?,?,?)",
                     (reward_id, blogger_uuid, "placement:" + reference,
                      campaign["fixed_rub"] * 100, now))
        db.audit(conn, actor, "blogger_fixed_earned", campaign["telegram_id"],
                 "placement=" + reference)
        db.enqueue(conn, "blogger:fixed:" + reward_id, campaign["telegram_id"],
                   "The Affiliates Partners\nФиксированное размещение подтверждено: " +
                   str(campaign["fixed_rub"]) + " ₽.")
        return {"reward_id": reward_id, "amount_kopeks": campaign["fixed_rub"] * 100}


def reward_paid(actor, owner_id, data):
    reward_id = data.get("reward_id")
    reference = data.get("payment_reference")
    from server.finance import REFERENCE
    if not isinstance(reward_id, str) or not reward_id.startswith("br_") or len(reward_id) != 27:
        raise db.Problem(400, "Некорректное начисление")
    if not isinstance(reference, str) or not REFERENCE.fullmatch(reference):
        raise db.Problem(400, "Укажите идентификатор реального платежа")
    db.initialize()
    with db.transaction() as conn:
        staff = db.require_staff(conn, actor, owner_id)
        schema(conn)
        row = conn.execute("SELECT r.*,c.telegram_id FROM blogger_rewards r JOIN blogger_campaigns c "
                           "ON c.blogger_uuid=r.blogger_uuid WHERE r.id=?", (reward_id,)).fetchone()
        if not row:
            raise db.Problem(404, "Начисление не найдено")
        if row["status"] != "earned":
            raise db.Problem(409, "Вознаграждение уже выплачено")
        if conn.execute("SELECT 1 FROM blogger_rewards WHERE payment_reference=?",
                        (reference,)).fetchone():
            raise db.Problem(409, "Платёж уже учтён")
        now = int(time.time())
        conn.execute("UPDATE blogger_rewards SET status='paid',payment_reference=?,paid_at=? WHERE id=?",
                     (reference, now, reward_id))
        db.audit(conn, actor, "blogger_reward_paid", row["telegram_id"], "reward=" + reward_id)
        db.enqueue(conn, "blogger:paid:" + reward_id, row["telegram_id"],
                   "The Affiliates Partners\nВаша рекламная выплата отмечена как полученная.")
        return {"paid": True, "reward_id": reward_id}
