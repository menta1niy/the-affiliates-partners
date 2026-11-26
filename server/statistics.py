"""Participant-only dashboard: indicative offer rates versus verified money.

Manual offer stages never imply bank confirmation. All money that may be
withdrawn comes exclusively from the verified finance ledger.
"""

from server import db, finance, mvp


def participant_snapshot(conn, actor):
    """One accounting formula for the participant and authorized admin card."""
    mvp.schema(conn)
    finance.schema(conn)

    # Offer rates are indicative only. Once verified, exclude the offer
    # from indicative sums so the same offer is not counted twice.
    rows = conn.execute(
        "SELECT a.stage,o.payout_rub,o.id,"
        "EXISTS(SELECT 1 FROM finance_accruals f WHERE f.telegram_id=a.telegram_id "
        "AND f.offer_id=a.offer_id) AS verified "
        "FROM manual_assignments a JOIN manual_offers o ON o.id=a.offer_id "
        "WHERE a.telegram_id=? AND o.active=1 AND o.deleted_at=0", (actor,)
    ).fetchall()
    stages = {"assigned": 0, "in_progress": 0, "submitted": 0,
              "completed": 0, "rejected": 0}
    potential = {"not_started_rub": 0, "in_work_rub": 0, "hold_rub": 0}
    for row in rows:
        if row["stage"] not in stages:
            continue
        stages[row["stage"]] += 1
        if row["verified"]:
            continue
        amount = row["payout_rub"]
        if row["stage"] == "assigned":
            potential["not_started_rub"] += amount
        elif row["stage"] in ("in_progress", "submitted"):
            potential["in_work_rub"] += amount
        elif row["stage"] == "completed":
            potential["hold_rub"] += amount

    # The public catalogue includes active offers that the lead has not yet
    # accepted. They contribute to the available potential once per offer,
    # separately from assigned/in-progress/verified accounting.
    unassigned = conn.execute(
        "SELECT COALESCE(SUM(o.payout_rub),0) AS total FROM manual_offers o "
        "WHERE o.active=1 AND o.deleted_at=0 "
        "AND NOT EXISTS (SELECT 1 FROM manual_assignments a "
        "WHERE a.offer_id=o.id AND a.telegram_id=?) "
        "AND NOT EXISTS (SELECT 1 FROM finance_accruals f "
        "WHERE f.offer_id=o.id AND f.telegram_id=?)", (actor, actor)
    ).fetchone()
    potential["not_started_rub"] += int(unassigned["total"])

    balances = finance._balances(conn, actor)
    return {
        "assigned_count": len(rows), "stages": stages,
        "potential": potential,
        "verified": balances,
        "explanation": "potential_is_not_available_balance",
    }


def overview(actor, owner_id, data):
    db.initialize()
    with db.transaction() as conn:
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active":
            raise db.Problem(403, "Нет доступа к статистике")
        target_id = data.get("user_id", actor)
        if user["role"] in ("owner", "admin", "staff"):
            if type(target_id) is not int or target_id <= 0:
                raise db.Problem(400, "Некорректный участник")
            target = db.get_user(conn, target_id)
            if not target or target["role"] not in ("lead", "referrer"):
                raise db.Problem(404, "Участник не найден")
        elif user["role"] not in ("lead", "referrer") or target_id != actor:
            raise db.Problem(403, "Нет доступа к статистике")
        return participant_snapshot(conn, target_id)
