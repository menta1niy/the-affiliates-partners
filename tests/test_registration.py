"""Real HTTP integration contracts for the Partners registration workflow.

Each test receives an isolated SQLite file and signs its own Telegram initData.
No Telegram network calls, third-party packages or production accounts are used.
"""
import concurrent.futures
import gc
import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from server.api import Handler
from server import bot


TOKEN = "partners-registration-integration-test-token"
OWNER = 758398804
ALICE = 721001
BOB = 721002
CAROL = 721003


def init_data(uid, *, username=None, age=0, start_param=None):
    fields = {
        "auth_date": str(int(time.time()) - age),
        "user": json.dumps({"id": uid, "first_name": "Test", "username": username or f"test{uid}"}, separators=(",", ":")),
    }
    if start_param is not None:
        fields["start_param"] = start_param
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class HttpHarness(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="partners-test-"))
        self.db_path = str(Path(self.directory) / "partners.sqlite3")
        self.stack.enter_context(patch.dict(os.environ, {"PARTNERS_DB_PATH": self.db_path}))
        self.stack.enter_context(patch("server.api.bot_token", return_value=TOKEN))
        self.stack.enter_context(patch("server.api.admin_id", return_value=OWNER))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        # Collect unclosed SQLite connections before Windows removes the temp DB.
        self.addCleanup(gc.collect)
        self.addCleanup(self.stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def post(self, path, payload, *, headers=None):
        request = Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urlopen(request, timeout=6) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def as_user(self, path, uid, **payload):
        return self.post(path, {"initData": init_data(uid), **payload})

    def owner_invite(self, assignee_id=None):
        payload = {} if assignee_id is None else {"assignee_id": assignee_id}
        status, body = self.as_user("/api/admin/invitations", OWNER, **payload)
        self.assertIn(status, (200, 201), body)
        self.assertIsInstance(body, dict)
        invite = body.get("invite_code") or body.get("code")
        if not invite and isinstance(body.get("invitation"), dict):
            invite = body["invitation"].get("code")
        self.assertIsInstance(invite, str, body)
        self.assertTrue(invite)
        return invite

    def register(self, uid, code):
        return self.as_user("/api/register", uid, invite_code=code, consent=True)

    def test_owner_dashboard_and_audit_are_server_authorized(self):
        for path in ("/api/admin/dashboard", "/api/admin/audit", "/api/admin/invitations"):
            with self.subTest(path=path):
                self.assertIn(self.as_user(path, OWNER)[0], (200, 201))
                self.assertIn(self.as_user(path, ALICE)[0], (401, 403))
                self.assertEqual(self.post(path, {"initData": "invalid"})[0], 401)

    def test_registration_requires_valid_invitation_and_consent(self):
        self.assertIn(self.as_user("/api/register", ALICE, invite_code="not-an-invitation", consent=True)[0], (400, 403, 404, 422))
        invite = self.owner_invite()
        self.assertIn(self.as_user("/api/register", ALICE, invite_code=invite, consent=False)[0], (400, 403, 422))
        status, registered = self.register(ALICE, invite)
        self.assertIn(status, (200, 201), registered)
        session_status, session = self.as_user("/api/session", ALICE)
        self.assertEqual(session_status, 200)
        self.assertEqual(session["user"]["id"], ALICE)

    def test_registration_is_idempotent_and_attribution_immutable(self):
        first_invite = self.owner_invite()
        second_invite = self.owner_invite()
        status, first = self.register(ALICE, first_invite)
        self.assertIn(status, (200, 201), first)
        status, repeated = self.register(ALICE, first_invite)
        self.assertIn(status, (200, 201, 409), repeated)
        status, switched = self.register(ALICE, second_invite)
        self.assertIn(status, (200, 201, 403, 409), switched)
        _, session = self.as_user("/api/session", ALICE)
        self.assertEqual(session["user"]["id"], ALICE)
        # The audit trail exposes the attribution, even when a repeat is rejected.
        status, audit = self.as_user("/api/admin/audit", OWNER)
        self.assertEqual(status, 200)
        self.assertIsInstance(audit.get("events"), list)
        registration_events = [event for event in audit["events"] if event["action"] == "register" and event["target_id"] == ALICE]
        self.assertEqual(len(registration_events), 1)

    def test_concurrent_registration_has_one_identity(self):
        invite = self.owner_invite()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            attempts = list(executor.map(lambda _: self.register(ALICE, invite), range(12)))
        self.assertTrue(all(code in (200, 201, 409) for code, _ in attempts), attempts)
        status, session = self.as_user("/api/session", ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(session["user"]["id"], ALICE)

    def test_referral_preserves_original_issuer_and_rejects_self_referral(self):
        agency_code = self.owner_invite()
        self.assertIn(self.register(ALICE, agency_code)[0], (200, 201))
        self.assertIn(self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="approve")[0], (200, 201))
        self.assertIn(self.as_user("/api/admin/assign", OWNER, user_id=ALICE, role="referrer")[0], (200, 201))
        code_status, referral = self.as_user("/api/invitations/referral", ALICE)
        self.assertIn(code_status, (200, 201), referral)
        referral_code = referral.get("invite_code") or referral.get("code")
        self.assertTrue(referral_code, referral)
        self.assertIn(self.register(ALICE, referral_code)[0], (200, 201, 400, 409))
        status, own_session = self.as_user("/api/session", ALICE)
        self.assertEqual(status, 200)
        self.assertNotEqual(own_session["user"].get("referrer_id"), ALICE)
        self.assertIn(self.register(BOB, referral_code)[0], (200, 201))
        _, referred = self.as_user("/api/session", BOB)
        self.assertEqual(referred["user"]["referrer_id"], ALICE)
        self.assertEqual(referred["user"].get("agency_id"), own_session["user"].get("agency_id"))
        self.register(BOB, agency_code)
        _, still_referred = self.as_user("/api/session", BOB)
        self.assertEqual(still_referred["user"]["referrer_id"], ALICE)

    def test_owner_decision_is_persisted_and_rejections_are_visible(self):
        invite = self.owner_invite()
        self.assertIn(self.register(ALICE, invite)[0], (200, 201))
        status, decision = self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="reject", reason="test reason")
        self.assertIn(status, (200, 201), decision)
        _, session = self.as_user("/api/session", ALICE)
        self.assertEqual(session["user"]["status"], "rejected")
        status, dashboard = self.as_user("/api/admin/dashboard", OWNER)
        self.assertEqual(status, 200)
        self.assertTrue(any(u["id"] == ALICE and u["status"] == "rejected" for u in dashboard["users"]))

    def test_owner_cannot_be_demoted_or_moderated(self):
        self.assertIn(self.as_user("/api/admin/decision", OWNER, user_id=OWNER, decision="reject")[0], (400, 403))
        self.assertIn(self.as_user("/api/admin/assign", OWNER, user_id=OWNER, role="partner")[0], (400, 403))
        _, session = self.as_user("/api/session", OWNER)
        self.assertEqual(session["role"], "owner")

    def test_manager_hierarchy_rejects_self_and_cycles(self):
        invite = self.owner_invite()
        for uid in (ALICE, BOB):
            self.assertIn(self.register(uid, self.owner_invite())[0], (200, 201))
            self.assertIn(self.as_user("/api/admin/decision", OWNER, user_id=uid, decision="approve")[0], (200, 201))
            self.assertIn(self.as_user("/api/admin/assign", OWNER, user_id=uid, role="staff")[0], (200, 201))
        self.assertIn(self.as_user("/api/admin/assign", OWNER, user_id=ALICE, manager_id=ALICE)[0], (400, 403))
        self.assertIn(self.as_user("/api/admin/assign", OWNER, user_id=BOB, manager_id=ALICE)[0], (200, 201))
        self.assertIn(self.as_user("/api/admin/assign", OWNER, user_id=ALICE, manager_id=BOB)[0], (400, 403))
        _, first = self.as_user("/api/session", ALICE)
        self.assertNotEqual(first["user"].get("manager_id"), BOB)

    def test_database_survives_http_server_restart(self):
        invitation = self.owner_invite()
        self.assertIn(self.register(ALICE, invitation)[0], (200, 201))
        self.assertIn(self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="approve")[0], (200, 201))
        self.stop_server()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        status, session = self.as_user("/api/session", ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(session["user"]["id"], ALICE)
        self.assertEqual(session["user"]["status"], "active")
        self.assertIn(self.register(BOB, self.owner_invite())[0], (200, 201))

    def test_moderation_cannot_be_spoofed_by_regular_user(self):
        invite = self.owner_invite()
        self.assertIn(self.register(ALICE, invite)[0], (200, 201))
        for route, data in (
            ("/api/admin/decision", {"user_id": ALICE, "decision": "approve"}),
            ("/api/admin/assign", {"user_id": ALICE, "manager_id": BOB}),
        ):
            with self.subTest(route=route):
                self.assertIn(self.as_user(route, BOB, **data)[0], (401, 403))
                self.assertEqual(self.post(route, {"initData": "forged", **data})[0], 401)

    def test_rejected_webhook_has_no_registration_side_effects(self):
        update = {"update_id": 44, "message": {"from": {"id": ALICE}, "chat": {"id": ALICE, "type": "private"}, "text": "/start INVITE123"}}
        with patch("server.api.webhook_secret", return_value="header-secret"):
            self.assertEqual(self.post("/api/telegram/webhook", update)[0], 403)
            self.assertEqual(self.post("/api/telegram/webhook", update, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})[0], 403)
            self.assertEqual(self.post("/api/telegram/webhook", update, headers={"X-Telegram-Bot-Api-Secret-Token": "header-secret"})[0], 200)
            self.assertEqual(self.post("/api/telegram/webhook", update, headers={"X-Telegram-Bot-Api-Secret-Token": "header-secret"})[0], 200)

    def test_webhook_start_attribution_and_update_id_deduplication(self):
        code = self.owner_invite()
        another = self.owner_invite()
        update = {"update_id": 7001, "message": {"from": {"id": ALICE}, "chat": {"id": ALICE, "type": "private"}, "text": "/start " + code}}
        headers = {"X-Telegram-Bot-Api-Secret-Token": "header-secret"}
        with patch("server.api.webhook_secret", return_value="header-secret"):
            self.assertEqual(self.post("/api/telegram/webhook", update, headers=headers)[0], 200)
            duplicate = json.loads(json.dumps(update))
            duplicate["message"]["text"] = "/start " + another
            self.assertEqual(self.post("/api/telegram/webhook", duplicate, headers=headers)[0], 200)
        # No invite_code: only the server-persisted Telegram /start attribution can register this user.
        status, registered = self.as_user("/api/register", ALICE, consent=True)
        self.assertIn(status, (200, 201), registered)
        self.assertEqual(registered["user"]["agency_id"], OWNER)
        status, events = self.as_user("/api/admin/audit", OWNER)
        self.assertEqual(status, 200)
        self.assertEqual(sum(event["action"] == "register" and event["target_id"] == ALICE for event in events["events"]), 1)

    def webhook_start(self, update_id, uid, code):
        update = {"update_id": update_id, "message": {"from": {"id": uid}, "chat": {"id": uid, "type": "private"}, "text": "/start " + code}}
        with patch("server.api.webhook_secret", return_value="header-secret"):
            return self.post("/api/telegram/webhook", update, headers={"X-Telegram-Bot-Api-Secret-Token": "header-secret"})

    def test_invalid_first_start_does_not_lock_attribution(self):
        valid = self.owner_invite()
        self.assertEqual(self.webhook_start(8001, ALICE, "ag_invalid1234")[0], 200)
        self.assertEqual(self.webhook_start(8002, ALICE, valid)[0], 200)
        status, result = self.as_user("/api/register", ALICE, consent=True)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["user"]["agency_id"], OWNER)

    def test_valid_start_conflicting_client_invite_returns_409(self):
        valid, conflicting = self.owner_invite(), self.owner_invite()
        self.assertEqual(self.webhook_start(8011, ALICE, valid)[0], 200)
        status, result = self.register(ALICE, conflicting)
        self.assertEqual(status, 409, result)
        _, session = self.as_user("/api/session", ALICE)
        self.assertEqual(session["status"], "invited")
        self.assertEqual(self.register(ALICE, valid)[0], 200)

    def test_clear_manager_role_change_and_cycle_protection(self):
        code = self.owner_invite()
        for uid in (ALICE, BOB):
            self.assertEqual(self.register(uid, self.owner_invite())[0], 200)
            self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=uid, decision="approve")[0], 200)
            self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=uid, role="staff")[0], 200)
        self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=BOB, manager_id=ALICE)[0], 200)
        self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=BOB, role="referrer")[1]["user"]["manager_id"], ALICE)
        self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=ALICE, manager_id=BOB)[0], 400)
        self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=BOB, manager_id=OWNER, clear_manager=True)[0], 400)
        result = self.as_user("/api/admin/assign", OWNER, user_id=BOB, clear_manager=True)
        self.assertEqual(result[0], 200, result[1])
        self.assertIsNone(result[1]["user"]["manager_id"])
        self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=ALICE, manager_id=BOB)[0], 400)

    def test_outbox_deduplicates_registration_and_identical_decisions(self):
        code = self.owner_invite()
        self.assertEqual(self.register(ALICE, code)[0], 200)
        self.assertEqual(self.register(ALICE, code)[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="approve")[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="approve")[0], 200)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT event_key FROM notifications_outbox ORDER BY id").fetchall()
        keys = [row[0] for row in rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(sum(key == f"register:{ALICE}" for key in keys), 1)
        self.assertEqual(sum(key.startswith(f"decision:{ALICE}:active:") for key in keys), 1)

    def test_sqlite_failure_returns_503_over_http(self):
        with patch("server.db.initialize", side_effect=sqlite3.OperationalError("synthetic disk failure")):
            for route, payload in (("/api/session", {"initData": init_data(OWNER)}), ("/api/telegram/webhook", {"update_id": 98765})):
                headers = {"X-Telegram-Bot-Api-Secret-Token": "header-secret"} if "webhook" in route else None
                with patch("server.api.webhook_secret", return_value="header-secret"):
                    status, response = self.post(route, payload, headers=headers)
                self.assertEqual(status, 503, (route, response))

    def test_owner_start_routes_to_admin_only(self):
        with patch.object(bot, "admin_id", return_value=OWNER), patch.object(bot, "app_url", return_value="https://example.org/partners/"):
            for uid, expected in ((OWNER, "https://example.org/partners/admin/"), (ALICE, "https://example.org/partners/")):
                with self.subTest(uid=uid):
                    update = {"message": {"from": {"id": uid}, "chat": {"id": uid, "type": "private"}, "text": "/start"}}
                    reply = bot.response_for(update)
                    self.assertEqual(reply["chat_id"], uid)
                    self.assertEqual(reply["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"], expected)

    def test_source_consent_persist_and_agency_invitation_single_use(self):
        invitation = self.owner_invite()
        self.assertEqual(self.register(ALICE, invitation)[0], 200)
        self.assertEqual(self.register(BOB, invitation)[0], 400)
        with sqlite3.connect(self.db_path) as conn:
            source, consent_at = conn.execute("SELECT source,consent_at FROM users WHERE id=?", (ALICE,)).fetchone()
            active = conn.execute("SELECT active FROM invitations WHERE code=?", (invitation,)).fetchone()[0]
        self.assertEqual(source, "agency")
        self.assertIsInstance(consent_at, int)
        self.assertGreater(consent_at, 0)
        self.assertEqual(active, 0)
        self.stop_server()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        with sqlite3.connect(self.db_path) as conn:
            self.assertEqual(conn.execute("SELECT source,consent_at FROM users WHERE id=?", (ALICE,)).fetchone(), (source, consent_at))

    def test_referral_link_reusable_and_sources_are_recorded(self):
        agency = self.owner_invite()
        self.assertEqual(self.register(ALICE, agency)[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="approve")[0], 200)
        self.assertEqual(self.as_user("/api/admin/assign", OWNER, user_id=ALICE, role="referrer")[0], 200)
        status, result = self.as_user("/api/invitations/referral", ALICE)
        self.assertEqual(status, 200, result)
        code = result["invite_code"]
        for uid in (BOB, CAROL):
            self.assertEqual(self.register(uid, code)[0], 200)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT id,source,referrer_id,consent_at FROM users WHERE id IN (?,?) ORDER BY id", (BOB, CAROL)).fetchall()
            active = conn.execute("SELECT active FROM invitations WHERE code=?", (code,)).fetchone()[0]
        self.assertEqual(len(rows), 2)
        for uid, source, referrer_id, consent_at in rows:
            self.assertEqual(source, "referral")
            self.assertEqual(referrer_id, ALICE)
            self.assertGreater(consent_at, 0)
        self.assertEqual(active, 1)


if __name__ == "__main__":
    unittest.main()
