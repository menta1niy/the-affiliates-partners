"""Runtime owner access and diagnostic DB identity checks, without Telegram calls."""
import gc
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import app
import bot
import preflight


class OwnerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_file = Path(self.temp.name) / "shared.sqlite3"
        for target in (app, preflight):
            db_patch = patch.object(target, "DB", self.db_file)
            db_patch.start()
            self.addCleanup(db_patch.stop)
        app.db().close()
        self.sent = []
        send_patch = patch.object(bot, "send", side_effect=lambda *args: self.sent.append(args))
        send_patch.start()
        self.addCleanup(send_patch.stop)
        self.addCleanup(gc.collect)

    def owner_message(self, **data):
        return {"from": {"id": app.ADMIN_ID, "username": "menta1niy"},
                "chat": {"id": app.ADMIN_ID, "type": "private"}, **data}

    def test_admin_start_and_contact_work_without_partner_row(self):
        for event in (self.owner_message(text="/start"),
                      self.owner_message(contact={"user_id": app.ADMIN_ID,
                                                  "phone_number": "+79999999999"}),
                      self.owner_message(text="/start")):
            bot.handle(event)
        self.assertEqual(len(self.sent), 3)
        self.assertTrue(all("Администратор" in sent[1] for sent in self.sent))
        with app.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM partners WHERE telegram_id=?",
                                          (app.ADMIN_ID,)).fetchone())
        self.assertEqual(preflight.check()["owner_partner_status"], "no-row")

    def test_pending_and_rejected_owner_rows_do_not_trigger_registration(self):
        for status in ("pending", "rejected"):
            with app.db() as con:
                con.execute("""INSERT INTO partners(telegram_id,status,created_at)
                               VALUES(?,?,0) ON CONFLICT(telegram_id)
                               DO UPDATE SET status=excluded.status""", (app.ADMIN_ID, status))
            bot.handle(self.owner_message(text="/start"))
            bot.handle(self.owner_message(contact={"user_id": app.ADMIN_ID,
                                                   "phone_number": "+79999999999"}))
            self.assertEqual(preflight.check()["owner_partner_status"], status)
            self.assertEqual(preflight.check()["owner_access_via_admin_id"], True)
            with app.db() as con:
                self.assertEqual(con.execute("SELECT status,phone FROM partners WHERE telegram_id=?",
                                             (app.ADMIN_ID,)).fetchone(), (status, ""))
        self.assertEqual(len(self.sent), 4)
        self.assertTrue(all("Администратор" in sent[1] for sent in self.sent))

    def test_preflight_uses_shared_runtime_db_not_late_environment_override(self):
        with patch.dict("os.environ", {"PARTNERS_DB_PATH": str(Path(self.temp.name) / "other.sqlite3")}):
            result = preflight.check()
        self.assertEqual(result["db_path"], str(self.db_file.resolve()))
        self.assertTrue(result["db_exists"])
        self.assertTrue(result["partners_table"])
        self.assertEqual(result["owner_admin_id"], bot.ADMIN_ID)


if __name__ == "__main__":
    unittest.main()
