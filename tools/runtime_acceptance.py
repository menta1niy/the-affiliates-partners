"""Isolated runtime acceptance using the *deployed* backend and real bot key.

Does NOT call Telegram or mutate production user accounts. It creates a temporary
SQLite database and runs the real HTTP handler on localhost with correctly signed
synthetic Telegram identities. It is a staging check, NOT proof of a second
human opening the Mini App from Telegram.
"""
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

from server.api import Handler
from server.settings import admin_id, bot_token, webhook_secret


class QuietHandler(Handler):
    def log_message(self, _format, *_args):
        return


def signed(uid, token, start_param=None):
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": uid, "first_name": "Acceptance", "username": "acceptance"},
            separators=(",", ":"),
        ),
    }
    if start_param is not None:
        values["start_param"] = start_param
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    values["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def request(base, route, payload, headers=None):
    url = base + route
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.load(exc)


def require(code, result, expected, description):
    if code != expected:
        raise AssertionError(f"{description}: expected HTTP {expected}, received {code}, error={result.get('error', '')!r}")
    return result


def run():
    token = bot_token()
    owner = admin_id()
    if not token or not owner or not webhook_secret():
        raise RuntimeError("Private Telegram configuration is incomplete")
    # Explicitly bound only to ephemeral files, never production database.
    previous = os.environ.get("PARTNERS_DB_PATH")
    with tempfile.TemporaryDirectory(prefix="partners-acceptance-") as temporary:
        db_path = Path(temporary) / "isolated.sqlite3"
        os.environ["PARTNERS_DB_PATH"] = str(db_path)
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        # These synthetic IDs must NEVER be sent to the production database.
        alice, bob, carol, direct = 901100001, 901100002, 901100003, 901100004
        try:
            def as_user(route, uid, **fields):
                return request(base, route, {"initData": signed(uid, token), **fields})

            def agency():
                code, result = as_user("/api/admin/invitations", owner)
                return require(code, result, 200, "agency invitation")["code"]

            code, result = as_user("/api/session", owner)
            assert require(code, result, 200, "owner login")["role"] == "owner"
            first = agency()
            code, result = request(base, "/api/register", {
                "initData": signed(alice, token, start_param=first), "consent": True,
            })
            assert require(code, result, 200, "agency registration")["user"]["status"] == "pending"
            code, result = as_user("/api/admin/dashboard", alice)
            require(code, result, 403, "lead denied admin")
            code, result = as_user("/api/invitations/referral", alice)
            require(code, result, 403, "unapproved lead denied referral")
            code, result = as_user("/api/register", bob, invite_code=first, consent=True)
            require(code, result, 400, "agency invitation one-use")
            code, result = as_user("/api/admin/decision", owner, user_id=alice, decision="approve")
            assert require(code, result, 200, "admin approval")["user"]["status"] == "active"
            code, result = as_user("/api/admin/assign", owner, user_id=alice, role="referrer")
            require(code, result, 200, "role grant")
            code, result = as_user("/api/invitations/referral", alice)
            referral = require(code, result, 200, "referral invite")["code"]

            # First verified /start wins; later valid links cannot switch owner.
            first_bob = agency()
            webhook_headers = {"X-Telegram-Bot-Api-Secret-Token": webhook_secret()}
            for update, invitation in ((900001, first_bob), (900002, referral)):
                message = {
                    "update_id": update,
                    "message": {
                        "text": "/start " + invitation,
                        "from": {"id": bob},
                        "chat": {"id": bob, "type": "private"},
                    },
                }
                code, result = request(base, "/api/telegram/webhook", message, webhook_headers)
                require(code, result, 200, "verified Telegram webhook")
            code, result = as_user("/api/register", bob, invite_code=referral, consent=True)
            require(code, result, 409, "conflicting attribution")
            code, result = as_user("/api/register", bob, consent=True)
            assert require(code, result, 200, "server retained first /start")["user"]["source"] == "agency"
            code, result = request(base, "/api/register", {
                "initData": signed(carol, token, start_param=referral), "consent": True,
            })
            assert require(code, result, 200, "referred registration")["user"]["referrer_id"] == alice
            # A direct ?startapp= link carries source in signed initData, not a
            # trusted arbitrary frontend parameter. No /start webhook required.
            signed_direct = signed(direct, token, start_param=referral)
            code, result = request(base, "/api/session", {"initData": signed_direct})
            require(code, result, 200, "signed direct Mini App launch")
            conflict = agency()
            code, result = request(base, "/api/register", {
                "initData": signed_direct, "invite_code": conflict, "consent": True,
            })
            require(code, result, 409, "signed launch source cannot be overridden")
            code, result = request(base, "/api/register", {
                "initData": signed_direct, "consent": True,
            })
            assert require(code, result, 200, "signed direct referral registration")["user"]["referrer_id"] == alice
            code, result = as_user(
                "/api/admin/attribution", bob, user_id=bob, source="referral",
                referrer_id=alice, reason="synthetic source correction check",
            )
            require(code, result, 403, "lead denied source correction")
            code, result = as_user(
                "/api/admin/attribution", owner, user_id=bob, source="referral",
                referrer_id=alice, reason="synthetic source correction check",
            )
            changed = require(code, result, 200, "owner audited correction")
            assert changed["changed"] is True
            assert changed["user"]["referrer_id"] == alice
            assert changed["user"]["manager_id"] == owner
            code, result = as_user(
                "/api/admin/attribution", owner, user_id=bob, source="referral",
                referrer_id=alice, reason="synthetic source correction check",
            )
            assert require(code, result, 200, "source correction idempotent")["changed"] is False
            code, result = as_user("/api/admin/dashboard", owner)
            assert len(require(code, result, 200, "owner pending queue")["pending"]) == 3
            code, result = as_user("/api/admin/decision", owner, user_id=bob, decision="reject", reason="Synthetic validation")
            require(code, result, 200, "admin rejection")
            code, result = as_user("/api/admin/decision", owner, user_id=carol, decision="block", reason="Synthetic validation")
            require(code, result, 200, "admin blocking")
            code, result = as_user("/api/invitations/referral", carol)
            require(code, result, 403, "blocked lead denied referral")

            with closing(__import__("sqlite3").connect(str(db_path))) as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 5
                assert connection.execute("SELECT count(*) FROM notifications_outbox WHERE sent_at IS NULL").fetchone()[0] >= 4
                assert connection.execute(
                    "SELECT source, consent_at FROM users WHERE id=?", (carol,)
                ).fetchone()[0] == "referral"
            print("ACCEPTANCE_PASS: signed HTTP, agency one-use, referral, /start attribution, queue, admin/moderation, DB integrity")
            print("ISOLATION_OK: production database and real users unchanged")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if previous is None:
                os.environ.pop("PARTNERS_DB_PATH", None)
            else:
                os.environ["PARTNERS_DB_PATH"] = previous


if __name__ == "__main__":
    run()
