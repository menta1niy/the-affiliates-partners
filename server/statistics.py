"""Participant-only dashboard: indicative offer rates versus verified money.

Manual offer stages never imply bank confirmation. All money that may be
withdrawn comes exclusively from the verified finance ledger.
"""

from server import db, finance, mvp


def overview(actor, owner_id, data):
    db.initialize()
    with db.transaction() as conn:
        user = db.get_user(conn, actor)
        if not user or user["status"] != "active" or user["role"] not in ("lead", "referrer"):
            raise db.Problem(403, "Статистика доступна подтверждённому участнику")
        mvp.schema(conn)
        finance.schema(conn)

        # The offer rate is only a potential amount. Once a bank-backed
        # accrual exists, that offer leaves the *indicative* buckets so that
        # one offer does not simultaneously appear as potential and verified.
        rows = conn.execute(
            "SELECT a.stage,o.payout_rub,o.id,"
            "EXISTS(SELECT 1 FROM finance_accruals f WHERE f.telegram_id=a.telegram_id "
            "AND f.offer_id=a.offer_id) AS verified "
            "FROM manual_assignments a JOIN manual_offers o ON o.id=a.offer_id "
            "WHERE a.telegram_id=? AND o.active=1", (actor,)
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

        balances = finance._balances(conn, actor)
        return {
            "assigned_count": len(rows), "stages": stages,
            "potential": potential,
            "verified": balances,
            "explanation": "potential_is_not_available_balance",
        }
