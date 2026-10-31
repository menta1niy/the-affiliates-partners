"""Explicitly opt-in synthetic cross-backend copy check; never touches production."""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from database.migrate_sqlite import TABLES, copy
from server import db, tasks


class SchemaMigrationFocused(unittest.TestCase):
    def test_nonempty_sqlite_copy_to_disposable_postgres(self):
        url = os.environ.get("PARTNERS_TEST_PG_URL")
        if not url:
            self.skipTest("PARTNERS_TEST_PG_URL required")
        import psycopg

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "synthetic.sqlite3")
            with patch.dict(os.environ, {"PARTNERS_DATABASE_URL": "", "PARTNERS_DB_PATH": path}):
                owner = {"id": 900001, "first_name": "Synthetic", "last_name": "", "username": ""}
                candidate = {"id": 900002, "first_name": "Synthetic", "last_name": "", "username": ""}
                db.session(owner, owner["id"])
                invitation = db.invite(owner["id"], owner["id"], "agency")["code"]
                db.record_start(900001, candidate["id"], invitation)
                db.register(candidate, owner["id"], None)
                db.receive_crm_event({"event_id": "crm:synthetic:bound", "type": "lead.bound",
                                      "telegram_id": candidate["id"], "crm_lead_id": "synthetic-lead"})
                db.receive_crm_event({"event_id": "crm:synthetic:offers", "type": "offers.assigned",
                                      "crm_lead_id": "synthetic-lead", "offers": [{"id": "synthetic-offer", "name": "Synthetic"}]})
                db.receive_crm_event({"event_id": "crm:synthetic:state", "type": "participant.state",
                                      "crm_lead_id": "synthetic-lead",
                                      "applications": [{"application_id": "synthetic-application",
                                                        "offer_id": "synthetic-offer", "stage": "credited"}],
                                      "lead_payouts": [{"conversion_id": "synthetic-conversion",
                                                        "offer_id": "synthetic-offer", "amount": "350.00",
                                                        "status": "confirmed", "reversed": False}]})
                with closing(sqlite3.connect(path)) as conn:
                    tasks._schema(conn)
                    conn.execute("INSERT INTO crm_bloggers(blogger_uuid,channel,issuer_id,active) VALUES(?,?,?,1)",
                                 ("99999999-9999-4999-8999-999999999999", "@synthetic_channel", owner["id"]))
                    conn.execute("INSERT INTO participant_task_reports(report_id,telegram_id,crm_lead_id,offer_id,action,note,created_at) "
                                 "VALUES(?,?,?,?,?,?,?)", ("synthetic-report", candidate["id"], "synthetic-lead",
                                                    "synthetic-offer", "opened", "test", 100))
                    conn.execute("INSERT INTO participant_task_report_outbox(report_id,payload,created_at) VALUES(?,?,?)",
                                 ("synthetic-report", '{"type":"participant.task.reported"}', 100))
                    conn.commit()

            with closing(sqlite3.connect(path)) as source:
                expected = {table: source.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                            for table in TABLES}
                for table in ("crm_registration_outbox", "crm_bloggers", "crm_participant_states", "participant_task_reports",
                              "participant_task_report_outbox",
                              "users", "invitations", "audit", "notifications_outbox"):
                    self.assertGreater(expected[table], 0, table + " requires a nonempty source fixture")
                owner_seq = source.execute("SELECT internal_id FROM users WHERE id=900001").fetchone()[0]
                user_seq = source.execute("SELECT internal_id FROM users WHERE id=900002").fetchone()[0]
            actual = copy(path, url)
            self.assertEqual(expected, actual)
            with psycopg.connect(url) as pg:
                self.assertEqual(pg.execute("SELECT current_setting('server_encoding')").fetchone()[0], "UTF8")
                self.assertEqual(pg.execute("SELECT count(*) FROM information_schema.tables "
                                            "WHERE table_schema='public' AND table_name IN (" +
                                            ",".join(["%s"] * len(TABLES)) + ")", TABLES).fetchone()[0], 0)
                for table, count in expected.items():
                    self.assertEqual(pg.execute("SELECT count(*) FROM partners." + table).fetchone()[0], count, table)
                self.assertEqual(pg.execute("SELECT internal_id FROM partners.users WHERE id=900001").fetchone()[0], owner_seq)
                self.assertEqual(pg.execute("SELECT internal_id FROM partners.users WHERE id=900002").fetchone()[0], user_seq)


if __name__ == "__main__":
    unittest.main()
