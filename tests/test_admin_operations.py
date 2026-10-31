"""Read-only administrative operational signals are owner-only."""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
import app
from test_signed_auth import signed_data

class OperationsTests(unittest.TestCase):
    def test_operational_snapshot_is_not_visible_to_partner(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(app,"DB",Path(tmp)/"ops.sqlite3"), patch.object(app,"TOKEN","test-bot-token"):
                http = ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
                thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
                try:
                    with app.db() as db:
                        db.execute("""CREATE TABLE bot_outbox
                          (id INTEGER PRIMARY KEY,chat_id INTEGER NOT NULL,
                           message TEXT NOT NULL,created_at INTEGER NOT NULL)""")
                        db.execute("INSERT INTO bot_outbox(chat_id,message,created_at) VALUES(123,'queued',1)")
                    def read(uid):
                        request=urllib.request.Request(
                            f"http://127.0.0.1:{http.server_port}/api/admin/snapshot",
                            json.dumps({"initData":signed_data(uid)}).encode(),
                            headers={"Content-Type":"application/json"})
                        try:
                            with urllib.request.urlopen(request,timeout=3) as response:
                                return response.status,json.load(response)
                        except urllib.error.HTTPError as error:
                            return error.code,json.load(error)
                    self.assertEqual(read(123)[0],403)
                    code,data=read(app.ADMIN_ID)
                    self.assertEqual(code,200)
                    self.assertEqual(data["operations"]["notificationsQueued"],1)
                    self.assertIsNone(data["operations"]["lastCrmSync"])
                finally:
                    http.shutdown();thread.join(timeout=2);http.server_close()

if __name__=="__main__":
    unittest.main()
