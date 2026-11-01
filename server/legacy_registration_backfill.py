"""Explicit, conservative repair for older consented referral registrations.

Default is a read-only preview. Run only after the approved database migration;
this command never dispatches HTTP requests or recreates missing attribution.
"""
import argparse
import json
import time

from server import db


def backfill(*, apply=False, now=None):
    now = int(time.time() if now is None else now)
    result = {"eligible": 0, "created": 0, "skipped": {}}
    with db.transaction() as conn:
        # Fail if schema preparation has not been completed. Do not call
        # db.initialize(), which can modify historical users during upgrades.
        users = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        for user in users:
            reason = None
            if user["role"] != "lead" or user["status"] != "active":
                reason = "not_active_lead"
            elif not user["consent_at"] or user["source"] != "referral":
                reason = "missing_verified_source"
            elif not user["referrer_id"] or user["referrer_id"] == user["id"]:
                reason = "invalid_referrer"
            elif user["introduced_by_id"] not in (None, user["referrer_id"]):
                reason = "conflicting_introducer"
            elif not conn.execute("SELECT 1 FROM users WHERE id=?", (user["referrer_id"],)).fetchone():
                reason = "unknown_referrer"
            elif not conn.execute("SELECT 1 FROM audit WHERE target_id=? AND "
                                  "((action='register' AND details='source=referral') "
                                  "OR action='attribution_correction') LIMIT 1", (user["id"],)).fetchone():
                reason = "no_provenance_audit"
            elif conn.execute("SELECT 1 FROM crm_lead_bindings WHERE telegram_id=?", (user["id"],)).fetchone():
                reason = "already_bound"
            elif conn.execute("SELECT 1 FROM crm_registration_outbox WHERE telegram_id=?", (user["id"],)).fetchone():
                reason = "already_queued"
            if reason:
                result["skipped"][reason] = result["skipped"].get(reason, 0) + 1
                continue
            result["eligible"] += 1
            if apply:
                payload = {"name": (user["first_name"] + " " + user["last_name"]).strip() or str(user["id"]),
                           "telegram_user_id": user["id"], "telegram_username": user["username"] or None,
                           "source_type": "referrer", "source_partner_id": f"referrer:{user['referrer_id']}",
                           "source_external_id": f"partners:lead:{user['id']}"}
                conn.execute("INSERT INTO crm_registration_outbox(telegram_id,payload,created_at) VALUES(?,?,?)",
                             (user["id"], json.dumps(payload, ensure_ascii=False, sort_keys=True), now))
                result["created"] += 1
        if not apply:
            # SELECT-only transaction; rollback avoids changing even metadata.
            conn.rollback()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Queue proven referral registrations; never dispatch")
    args = parser.parse_args()
    print(json.dumps(backfill(apply=args.apply), sort_keys=True))
