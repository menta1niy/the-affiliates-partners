"""A deliberately small API; static frontend is served separately by nginx."""
import hmac
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from server.auth import verify_init_data
from server.bot import response_for
from server.settings import admin_id, bot_token, webhook_secret
from server import db
from server import integration
from server import tasks


def storage_error(exc):
    """Database backend can be SQLite or PostgreSQL after migration."""
    if isinstance(exc, sqlite3.Error):
        return True
    return type(exc).__module__.split('.')[0] in ('psycopg', 'psycopg2')


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlsplit(self.path).path == "/api/health":
            try:
                db.initialize()
                with db.transaction() as conn:
                    conn.execute("SELECT 1")
            except Exception:
                return self.send_json(503, {"ok": False, "service": "the-affiliates-partners-v2"})
            return self.send_json(200, {"ok": True, "service": "the-affiliates-partners-v2"})
        return self.send_json(404, {"error": "Маршрут не найден"})

    def do_POST(self):
        route = urlsplit(self.path).path
        if route == "/api/integration/crm/events":
            return self.handle_crm_event()
        routes = {"/api/session", "/api/register", "/api/invitations/referral", "/api/invitations/revoke", "/api/admin/invitations", "/api/admin/invitations/blogger",
                  "/api/admin/dashboard", "/api/admin/participant", "/api/admin/decision", "/api/admin/assign", "/api/admin/audit", "/api/admin/attribution",
                  "/api/telegram/webhook", "/api/offers", "/api/tasks", "/api/tasks/report", "/api/status", "/api/lead-view"}
        if route not in routes:
            return self.send_json(404, {"error": "Маршрут не найден"})
        if route == "/api/telegram/webhook":
            secret = webhook_secret()
            header = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not secret or not hmac.compare_digest(secret, header):
                return self.send_json(403, {"error": "Недостаточно прав"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 24000:
                return self.send_json(400, {"error": "Неверный размер запроса"})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                return self.send_json(400, {"error": "Неверный запрос"})
        except (ValueError, UnicodeError):
            return self.send_json(400, {"error": "Неверный JSON"})
        if route == "/api/telegram/webhook":
            try:
                return self.handle_webhook(body)
            except Exception as exc:
                if storage_error(exc):
                    return self.send_json(503, {"error": "Хранилище временно недоступно"})
                raise
        return self.handle_authorized(route, body)

    def handle_crm_event(self):
        """CRM-only ingress. Telegram initData is never accepted as CRM authority."""
        try:
            if not self.headers.get("X-TA-Event-ID"):
                return self.send_json(401, {"error": "Событие CRM не подтверждено"})
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= integration.MAX_BODY:
                return self.send_json(400, {"error": "Некорректный размер события"})
            raw = self.rfile.read(size)
            event = integration.verify(raw, self.headers.get("X-TA-Timestamp"),
                                       self.headers.get("X-TA-Signature"),
                                       event_id_header=self.headers.get("X-TA-Event-ID"))
        except (ValueError, integration.BridgeError):
            return self.send_json(401, {"error": "Событие CRM не подтверждено"})
        receive = getattr(db, "receive_crm_event", None)
        if receive is None:
            return self.send_json(503, {"error": "Синхронизация CRM не настроена"})
        try:
            result = receive(event)
            return self.send_json(200, result)
        except db.Problem as exc:
            return self.send_json(exc.code, {"error": str(exc)})
        except Exception as exc:
            if storage_error(exc):
                return self.send_json(503, {"error": "Хранилище временно недоступно"})
            raise

    def handle_webhook(self, body):
        if type(body.get("update_id")) is not int:
            return self.send_json(400, {"error": "Неверное обновление Telegram"})
        message = body.get("message")
        sender = message.get("from") if isinstance(message, dict) else None
        chat = message.get("chat") if isinstance(message, dict) else None
        if isinstance(sender, dict) and isinstance(chat, dict) and type(sender.get("id")) is int and sender["id"] > 0 and sender["id"] == chat.get("id") and chat.get("type") == "private":
            import re
            text = message.get("text", "")
            match = re.fullmatch(r"/start(?:@[A-Za-z0-9_]{3,32})?\s+((?:ag|ref|blog)_[A-Za-z0-9_-]{8,48})\s*", text) if isinstance(text, str) else None
            fresh = db.record_start(body["update_id"], sender["id"], match.group(1) if match else None)
        else:
            fresh = db.record_start(body["update_id"], 0, None)
        return self.send_json(200, (response_for(body) or {"ok": True}) if fresh else {"ok": True})

    def handle_authorized(self, route, body):
        token = bot_token()
        if not token:
            return self.send_json(503, {"error": "Telegram не настроен на сервере"})
        user = verify_init_data(body.get("initData"), token)
        if user is None:
            return self.send_json(401, {"error": "Telegram не подтвердил данные входа"})
        try:
            owner = admin_id()
            if route == "/api/session":
                profile = db.session(user, owner)
                pending_source = profile.pop("pending_source_info", None)
                result = {"user": profile, "role": profile["role"], "status": profile["status"], "source": "telegram"}
                if pending_source:
                    result["source_info"] = pending_source
            elif route == "/api/register":
                if body.get("consent") is not True:
                    return self.send_json(400, {"error": "Необходимо согласие"})
                code = body.get("invite_code")
                if code is not None and not isinstance(code, str):
                    return self.send_json(400, {"error": "Некорректный код"})
                profile = db.register(user, owner, code)
                result = {"user": profile, "role": profile["role"], "status": profile["status"]}
            elif route == "/api/invitations/referral":
                result = db.invite(user["id"], owner, "referral")
            elif route == "/api/invitations/revoke":
                result = db.revoke_invitation(user["id"], owner, body.get("code"))
            elif route == "/api/admin/invitations":
                result = db.invite(user["id"], owner, "agency", body.get("assignee_id"), body.get("candidate_label", ""))
            elif route == "/api/admin/invitations/blogger":
                result = db.invite_blogger(user["id"], owner, body.get("blogger_uuid"))
            elif route == "/api/admin/dashboard":
                result = db.dashboard(user["id"], owner)
            elif route == "/api/admin/participant":
                if type(body.get("user_id")) is not int or body["user_id"] <= 0:
                    return self.send_json(400, {"error": "Некорректный пользователь"})
                result = db.admin_participant_detail(user["id"], owner, body["user_id"])
            elif route == "/api/offers":
                get_offers = getattr(db, "list_assigned_offers", None)
                if get_offers is None:
                    return self.send_json(503, {"error": "Офферы CRM пока недоступны"})
                result = {"offers": get_offers(user["id"], owner)}
            elif route == "/api/status":
                result = db.participant_status(user["id"], owner)
            elif route == "/api/lead-view":
                result = db.participant_lead_view(user["id"], owner)
            elif route == "/api/tasks":
                result = tasks.list_tasks(user["id"], owner)
            elif route == "/api/tasks/report":
                result = tasks.report_action(user["id"], owner, body.get("offer_id"),
                                             body.get("action"), body.get("note", ""))
            elif route == "/api/admin/decision":
                if type(body.get("user_id")) is not int or body["user_id"] <= 0:
                    return self.send_json(400, {"error": "Некорректный пользователь"})
                profile = db.decision(user["id"], owner, body["user_id"], body.get("decision"), body.get("reason", ""))
                result = {"user": profile, "role": profile["role"], "status": profile["status"]}
            elif route == "/api/admin/assign":
                if type(body.get("user_id")) is not int or body["user_id"] <= 0:
                    return self.send_json(400, {"error": "Некорректный пользователь"})
                profile = db.assign(
                    user["id"], owner, body["user_id"], body.get("manager_id"),
                    body.get("role"), body.get("clear_manager") is True,
                )
                result = {"user": profile, "role": profile["role"], "status": profile["status"]}
            elif route == "/api/admin/attribution":
                result = db.correct_attribution(user["id"], owner, body.get("user_id"), body.get("source"),
                                                body.get("referrer_id"), body.get("agency_id"), body.get("reason", ""),
                                                body.get("introduced_by_id"))
            else:
                result = {"events": db.audit_events(user["id"], owner)}
            return self.send_json(200, result)
        except db.Problem as exc:
            return self.send_json(exc.code, {"error": str(exc)})
        except Exception as exc:
            if storage_error(exc):
                return self.send_json(503, {"error": "Хранилище временно недоступно"})
            raise
        except (ValueError, TypeError, OverflowError):
            return self.send_json(400, {"error": "Некорректные данные"})


def main():
    # Schema and additive migrations must succeed before systemd reports the
    # API port as ready. A health check alone cannot prove DB readiness.
    db.initialize()
    port = int(os.environ.get("SERVER_PORT", "8788"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Partners API listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
