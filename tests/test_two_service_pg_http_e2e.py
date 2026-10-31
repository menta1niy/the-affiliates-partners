"""Two real local HTTP services, PostgreSQL 17, signed Telegram and CRM traffic.

Requires CRM_BACKEND_ROOT and dedicated disposable UTF8 TEST_DATABASE_URL.
Run only against isolated local test databases; never production.
"""
import json
import os
import socket
import sys
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from tests import test_registration as registration

OWNER = registration.OWNER
ALICE = registration.ALICE

SECRET = "local-two-service-e2e-only-shared-secret-20261031"


class TwoServicePostgresHTTP(unittest.TestCase):
    def setUp(self):
        pg_url = os.environ.get("TEST_DATABASE_URL")
        if pg_url:
            os.environ["PARTNERS_DATABASE_URL"] = pg_url.replace("postgresql+psycopg://", "postgresql://")
        registration.HttpHarness.setUp(self)
    stop_server = registration.HttpHarness.stop_server
    post = registration.HttpHarness.post
    as_user = registration.HttpHarness.as_user
    register = registration.HttpHarness.register
    owner_invite = registration.HttpHarness.owner_invite
    webhook_start = registration.HttpHarness.webhook_start

    def test_agency_referrer_signed_http_registration_first_attribution(self):
        """Two non-blogger sources traverse the real Partners -> CRM HTTP route."""
        crm_root = os.environ.get("CRM_BACKEND_ROOT")
        pg_url = os.environ.get("TEST_DATABASE_URL")
        if not crm_root or not pg_url:
            self.skipTest("CRM_BACKEND_ROOT and TEST_DATABASE_URL required")
        assert "127.0.0.1:55439" in pg_url and "e2e" in pg_url
        sys.path.insert(0, str(Path(crm_root)))
        os.environ["DATABASE_URL"] = pg_url
        os.environ["PARTNERS_CRM_SHARED_SECRET"] = SECRET
        os.environ["PARTNERS_INTEGRATION_SECRET"] = SECRET
        os.environ["APP_ENV"] = "test"
        import time
        from uuid import uuid4
        from urllib.error import HTTPError
        import uvicorn
        from sqlalchemy import select
        from app.main import app
        from app.core.database import SessionLocal
        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.enums import WorkspaceKind
        from app.models.lead import Lead
        from app.models.finance import Conversion, ConversionPayout
        from server import crm_registration, db
        from server.integration import signature

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        crm_port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=4))
        self.addCleanup(lambda: setattr(server, "should_exit", True))
        with SessionLocal() as session:
            owner = User(email=f"e2e-source-{uuid4()}@example.test", nickname="Synthetic",
                         password_hash="synthetic-not-login")
            session.add(owner)
            session.flush()
            workspace = Workspace(name="Synthetic source attribution", kind=WorkspaceKind.TEAM,
                                  created_by=owner.id)
            session.add(workspace)
            session.commit()
            workspace_id = workspace.id
        endpoint = f"http://127.0.0.1:{crm_port}/api/v1/workspaces/{workspace_id}/integrations/partners/leads"

        def send_signed_http(payload, _endpoint):
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()
            timestamp = int(time.time())
            request = Request(endpoint, raw, {"Content-Type": "application/json",
                              "X-TA-Timestamp": str(timestamp),
                              "X-TA-Signature": signature(raw, timestamp, SECRET)}, method="POST")
            try:
                with urlopen(request, timeout=8) as response:
                    self.assertEqual(response.status, 200)
                    return json.load(response)["id"]
            except HTTPError as exc:
                raise AssertionError(f"CRM registration {exc.code}: {exc.read()!r}") from exc

        # Agency invitation is personal; an owner may issue a reusable
        # referral link. Both must keep their actual issuer.
        self.assertEqual(self.register(ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=ALICE,
                                      decision="approve")[0], 200)
        status, referral = self.as_user("/api/invitations/referral", OWNER)
        self.assertEqual(status, 200, referral)
        self.assertEqual(self.register(registration.BOB, referral["code"])[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=registration.BOB,
                                      decision="approve")[0], 200)
        expected = {ALICE: ("agency", f"agency:{OWNER}"),
                    registration.BOB: ("referrer", f"referrer:{OWNER}")}
        with db.transaction() as conn:
            for telegram_id, (source_type, partner_id) in expected.items():
                row = conn.execute("SELECT payload FROM crm_registration_outbox WHERE telegram_id=?",
                                   (telegram_id,)).fetchone()
                self.assertIsNotNone(row)
                payload = json.loads(row["payload"])
                self.assertEqual((payload["source_type"], payload["source_partner_id"]),
                                 (source_type, partner_id))
        with SessionLocal() as session:
            finance_before = (session.query(Conversion).count(), session.query(ConversionPayout).count())
        with patch.object(crm_registration, "endpoint", return_value=endpoint):
            outcome = crm_registration.dispatch_once(sender=send_signed_http)
        self.assertEqual(outcome, {"claimed": 2, "delivered": 2, "failed": 0})
        with SessionLocal() as session:
            originals = {}
            for telegram_id, (source_type, partner_id) in expected.items():
                lead = session.scalar(select(Lead).where(Lead.workspace_id == workspace_id,
                                                       Lead.telegram_user_id == telegram_id))
                self.assertIsNotNone(lead)
                self.assertEqual((lead.source_type, lead.source_partner_id), (source_type, partner_id))
                self.assertIsNone(lead.blogger_id)
                originals[telegram_id] = lead.id

        # Later valid invitations cannot rewrite either source in CRM.
        self.assertEqual(self.register(ALICE, referral["code"])[0], 200)
        self.assertEqual(self.register(registration.BOB, self.owner_invite())[0], 200)
        with SessionLocal() as session:
            for telegram_id, (source_type, partner_id) in expected.items():
                lead = session.get(Lead, originals[telegram_id])
                self.assertEqual((lead.source_type, lead.source_partner_id), (source_type, partner_id))
            self.assertEqual((session.query(Conversion).count(), session.query(ConversionPayout).count()),
                             finance_before)

    def test_consent_registration_binding_offers_and_tasks(self):
        crm_root = os.environ.get("CRM_BACKEND_ROOT")
        pg_url = os.environ.get("TEST_DATABASE_URL")
        if not crm_root or not pg_url:
            self.skipTest("CRM_BACKEND_ROOT and TEST_DATABASE_URL required")
        assert "127.0.0.1:55439" in pg_url and "e2e" in pg_url
        sys.path.insert(0, str(Path(crm_root)))
        os.environ["DATABASE_URL"] = pg_url
        os.environ["PARTNERS_CRM_SHARED_SECRET"] = SECRET
        os.environ["PARTNERS_INTEGRATION_SECRET"] = SECRET
        os.environ["APP_ENV"] = "test"
        from uuid import uuid4
        import uvicorn
        from sqlalchemy import select
        from app.main import app
        from app.core.database import SessionLocal
        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.enums import WorkspaceKind, OfferType
        from app.models.offer import Offer
        from app.models.offer_assignment import OfferAssignment
        from app.models.lead import Lead
        from app.models.partner_task_report import PartnerTaskReport
        from app.models.finance import Conversion, ConversionPayout
        from app.modules.partners.outbox import enqueue_offers_assigned, enqueue_blogger_bound, deliver_due
        from server import crm_registration, task_report_delivery, db

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        crm_port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=4))
        self.addCleanup(lambda: setattr(server, "should_exit", True))
        crm_base = f"http://127.0.0.1:{crm_port}"

        with SessionLocal() as session:
            owner = User(email=f"e2e-{uuid4()}@example.test", nickname="Synthetic", password_hash="synthetic-not-login")
            session.add(owner)
            session.flush()
            workspace = Workspace(name="E2E synthetic", kind=WorkspaceKind.TEAM, created_by=owner.id)
            session.add(workspace)
            session.commit()
            workspace_id = workspace.id

        code = self.owner_invite()
        self.assertEqual(self.register(ALICE, code)[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=ALICE, decision="approve")[0], 200)
        url = f"{crm_base}/api/v1/workspaces/{workspace_id}/integrations/partners/leads"

        def real_http_sender(payload, _url):
            # submit() enforces the HTTPS production transport; this sender uses
            # its signed canonical bytes against a real loopback HTTP FastAPI.
            from server.integration import signature
            import time
            raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
            timestamp = int(time.time())
            req = Request(url, raw, {"Content-Type": "application/json", "X-TA-Timestamp": str(timestamp),
                       "X-TA-Signature": signature(raw, timestamp, SECRET)}, method="POST")
            from urllib.error import HTTPError
            try:
                with urlopen(req, timeout=8) as response:
                    self.assertEqual(response.status, 200)
                    return json.load(response)["id"]
            except HTTPError as exc:
                detail = exc.read()
                raise AssertionError(f"CRM import HTTP {exc.code}: {detail!r}") from exc

        with patch.object(crm_registration, "endpoint", return_value=url):
            result = crm_registration.dispatch_once(sender=real_http_sender)
        self.assertEqual(result["delivered"], 1, result)

        with SessionLocal() as session:
            lead = session.scalar(select(Lead).where(Lead.workspace_id == workspace_id, Lead.telegram_user_id == ALICE))
            self.assertIsNotNone(lead)
            offer = Offer(workspace_id=workspace_id, name="Synthetic debit", advertiser="Test Bank",
                          offer_type=OfferType.DEBIT, agency_rate=Decimal("4000"),
                          blogger_payout=Decimal("1000"), lead_reward=Decimal("250"),
                          target_action="Submit application", referral_url="https://example.test/apply")
            session.add(offer)
            session.flush()
            session.add(OfferAssignment(workspace_id=workspace_id, lead_id=lead.id,
                                        offer_id=offer.id, lead_reward_override=Decimal("350"),
                                        instructions="Synthetic instructions"))
            session.flush()
            enqueue_offers_assigned(session, workspace_id, lead.id)
            session.commit()
            offer_id = str(offer.id)

        with SessionLocal() as session:
            result = deliver_due(session, endpoint=self.base + "/api/integration/crm/events", secret=SECRET)
        self.assertEqual(result["failed"], 0, result)
        self.assertGreaterEqual(result["sent"], 2, result)
        status, offers = self.as_user("/api/offers", ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(len(offers["offers"]), 1, offers)
        self.assertEqual(offers["offers"][0]["id"], offer_id)
        self.assertEqual(Decimal(offers["offers"][0]["lead_reward"]), Decimal("350"))
        status, tasks = self.as_user("/api/tasks", ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(len(tasks["tasks"]), 1)
        status, reported = self.as_user("/api/tasks/report", ALICE, offer_id=offer_id,
                                        action="submitted", note="Synthetic report")
        self.assertEqual(status, 200, reported)
        self.assertEqual(reported["status"], "reported")
        with SessionLocal() as session:
            finance_before = (session.query(Conversion).count(), session.query(ConversionPayout).count())

        def real_report_sender(event, url):
            # Actual task_report_delivery.submit constructs/signs the ISO-timestamp
            # JSON; inject only urllib's real local HTTP opener.
            return task_report_delivery.submit(event, url, opener=lambda request, timeout: urlopen(request, timeout=timeout))

        report_endpoint = f"{crm_base}/api/v1/workspaces/{workspace_id}/integrations/partners/task-reports"
        with patch.object(task_report_delivery, "endpoint", return_value=report_endpoint):
            dispatched = task_report_delivery.dispatch_once(sender=real_report_sender)
        self.assertEqual(dispatched, {"claimed": 1, "delivered": 1, "failed": 0})
        with SessionLocal() as session:
            rows = session.scalars(select(PartnerTaskReport).where(PartnerTaskReport.workspace_id == workspace_id)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(str(rows[0].report_id), reported["report_id"])
            self.assertEqual(rows[0].action, "submitted")
            self.assertEqual(rows[0].note, "Synthetic report")
            self.assertEqual((session.query(Conversion).count(), session.query(ConversionPayout).count()), finance_before)

        # Source binding is a separate CRM-authorized event. Use a synthetic
        # owner issuer and verify the signed HTTP receiver's persisted mapping.
        from uuid import uuid4
        blogger_uuid = uuid4()
        channel = "@synthetic_e2e_channel"
        with SessionLocal() as session:
            enqueue_blogger_bound(session, workspace_id=workspace_id, blogger_id=blogger_uuid,
                                 issuer_id=OWNER, channel=channel)
            session.commit()
        with SessionLocal() as session:
            delivered = deliver_due(session, endpoint=self.base + "/api/integration/crm/events", secret=SECRET)
        self.assertEqual(delivered["failed"], 0, delivered)
        self.assertEqual(delivered["sent"], 1, delivered)
        with db.transaction() as conn:
            record = conn.execute("SELECT issuer_id,channel FROM crm_bloggers WHERE blogger_uuid=?", (str(blogger_uuid),)).fetchone()
            self.assertIsNotNone(record)
            self.assertEqual(record["issuer_id"], OWNER)
            self.assertEqual(record["channel"], channel)

        from app.models.blogger import Blogger
        from app.models.enums import Platform, BloggerPostStatus
        with SessionLocal() as session:
            session.add(Blogger(id=blogger_uuid, workspace_id=workspace_id, name="Synthetic blogger",
                                platform=Platform.TELEGRAM, post_status=BloggerPostStatus.OUTREACH))
            session.commit()

        # Blogger invitations require the CRM binding and owner authority.
        self.assertEqual(self.as_user("/api/admin/invitations/blogger", ALICE,
                                      blogger_uuid=str(blogger_uuid))[0], 403)
        status, invited = self.as_user("/api/admin/invitations/blogger", OWNER, blogger_uuid=str(blogger_uuid))
        self.assertEqual(status, 200, invited)
        old_code = invited["code"]
        self.assertTrue(old_code.startswith("blog_"))
        self.assertEqual(self.as_user("/api/invitations/revoke", OWNER, code=old_code)[0], 200)
        status, replacement = self.as_user("/api/admin/invitations/blogger", OWNER, blogger_uuid=str(blogger_uuid))
        self.assertEqual(status, 200, replacement)
        self.assertNotEqual(replacement["code"], old_code)
        self.assertEqual(self.as_user("/api/register", registration.BOB, invite_code=old_code, consent=True)[0], 400)

        self.assertEqual(self.register(registration.BOB, replacement["code"])[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", OWNER, user_id=registration.BOB,
                                      decision="approve")[0], 200)
        with db.transaction() as conn:
            outbox = conn.execute("SELECT payload FROM crm_registration_outbox WHERE telegram_id=?",
                                  (registration.BOB,)).fetchone()
            self.assertIsNotNone(outbox)
            registration_payload = json.loads(outbox["payload"])
            self.assertEqual(registration_payload["source_type"], "blogger")
            self.assertEqual(registration_payload["source_partner_id"], str(blogger_uuid))
            self.assertEqual(registration_payload["source_channel"], channel)

        with patch.object(crm_registration, "endpoint", return_value=url):
            registered = crm_registration.dispatch_once(sender=real_http_sender)
        self.assertEqual(registered, {"claimed": 1, "delivered": 1, "failed": 0})
        with SessionLocal() as session:
            linked = session.scalar(select(Lead).where(Lead.workspace_id == workspace_id,
                                                      Lead.telegram_user_id == registration.BOB))
            self.assertIsNotNone(linked)
            self.assertEqual(linked.blogger_id, blogger_uuid)
            self.assertEqual(linked.source_type, "blogger")
            self.assertEqual(linked.source_partner_id, str(blogger_uuid))
            self.assertEqual(linked.source_channel, channel)
            original_lead_id = linked.id

        # A later invitation must not replace the first recorded source.
        second_code = self.owner_invite()
        self.assertEqual(self.as_user("/api/register", registration.BOB, invite_code=second_code,
                                      consent=True)[0], 200)
        with SessionLocal() as session:
            linked = session.scalar(select(Lead).where(Lead.id == original_lead_id))
            self.assertEqual((linked.source_type, linked.source_partner_id, linked.source_channel),
                             ("blogger", str(blogger_uuid), channel))
