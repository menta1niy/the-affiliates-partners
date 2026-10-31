"""Agency and referrer acquisition across real Partners/CRM HTTP and PostgreSQL.

Requires the same isolated test setup as test_two_service_pg_http_e2e.
"""
import json
import os
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
from uuid import uuid4

from tests import test_registration as registration
from tests.test_two_service_pg_http_e2e import SECRET


class AgencyReferralTwoServiceHTTP(unittest.TestCase):
    def setUp(self):
        pg_url = os.environ.get("TEST_DATABASE_URL")
        if pg_url:
            os.environ["PARTNERS_DATABASE_URL"] = pg_url.replace("postgresql+psycopg://", "postgresql://")
        registration.HttpHarness.setUp(self)

    stop_server = registration.HttpHarness.stop_server
    post = registration.HttpHarness.post
    as_user = registration.HttpHarness.as_user
    owner_invite = registration.HttpHarness.owner_invite
    register = registration.HttpHarness.register
    webhook_start = registration.HttpHarness.webhook_start

    def test_agency_referral_attribution_replay_and_offers(self):
        root, pg_url = os.environ.get("CRM_BACKEND_ROOT"), os.environ.get("TEST_DATABASE_URL")
        if not root or not pg_url:
            self.skipTest("CRM_BACKEND_ROOT and TEST_DATABASE_URL required")
        self.assertIn("127.0.0.1:55439", pg_url)
        self.assertIn("e2e", pg_url)
        sys.path.insert(0, str(Path(root)))
        os.environ.update(DATABASE_URL=pg_url, PARTNERS_CRM_SHARED_SECRET=SECRET,
                          PARTNERS_INTEGRATION_SECRET=SECRET, APP_ENV="test")
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
        from app.modules.partners.outbox import enqueue_offers_assigned, deliver_due
        from server import crm_registration, db

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=4))
        self.addCleanup(lambda: setattr(server, "should_exit", True))

        with SessionLocal() as session:
            owner = User(email=f"agency-e2e-{uuid4()}@example.test", nickname="Synthetic", password_hash="test")
            session.add(owner)
            session.flush()
            workspace = Workspace(name="Agency/referral E2E", kind=WorkspaceKind.TEAM, created_by=owner.id)
            session.add(workspace)
            session.commit()
            workspace_id = workspace.id
        endpoint = f"http://127.0.0.1:{port}/api/v1/workspaces/{workspace_id}/integrations/partners/leads"

        agency_code = self.owner_invite()
        self.assertEqual(self.register(registration.ALICE, agency_code)[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", registration.OWNER,
                                      user_id=registration.ALICE, decision="approve")[0], 200)
        second_agency_code = self.owner_invite()
        self.assertEqual(self.register(registration.BOB, second_agency_code)[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", registration.OWNER,
                                      user_id=registration.BOB, decision="approve")[0], 200)
        self.assertEqual(self.as_user("/api/admin/assign", registration.OWNER,
                                      user_id=registration.BOB, role="referrer")[0], 200)
        status, invitation = self.as_user("/api/invitations/referral", registration.BOB)
        self.assertEqual(status, 200, invitation)
        referral_code = invitation.get("code") or invitation.get("invite_code")
        self.assertEqual(self.register(registration.CAROL, referral_code)[0], 200)
        self.assertEqual(self.as_user("/api/admin/decision", registration.OWNER,
                                      user_id=registration.CAROL, decision="approve")[0], 200)

        with db.transaction() as conn:
            rows = conn.execute("SELECT id,source,agency_id,referrer_id,manager_id,introduced_by_id,consent_at "
                                "FROM users WHERE id IN (?,?) ORDER BY id",
                                (registration.ALICE, registration.CAROL)).fetchall()
            by_id = {row["id"]: dict(row) for row in rows}
            self.assertEqual(by_id[registration.ALICE]["source"], "agency")
            self.assertEqual(by_id[registration.CAROL]["source"], "referral")
            self.assertEqual(by_id[registration.CAROL]["referrer_id"], registration.BOB)
            self.assertEqual(by_id[registration.CAROL]["introduced_by_id"], registration.BOB)
            self.assertTrue(all(row["consent_at"] for row in rows))
            payloads = {row["telegram_id"]: json.loads(row["payload"]) for row in conn.execute(
                "SELECT telegram_id,payload FROM crm_registration_outbox").fetchall()}
        self.assertEqual(payloads[registration.ALICE]["source_type"], "agency")
        self.assertEqual(payloads[registration.CAROL]["source_type"], "referrer")
        self.assertEqual(payloads[registration.CAROL]["source_partner_id"], f"referrer:{registration.BOB}")

        # Manager assignment affects operations, never the recorded acquisition source.
        self.assertEqual(self.as_user("/api/admin/assign", registration.OWNER,
                                      user_id=registration.CAROL, manager_id=registration.OWNER)[0], 200)
        self.assertEqual(self.as_user("/api/session", registration.CAROL)[1]["user"]["referrer_id"], registration.BOB)

        # Simulate a temporarily unavailable CRM, then retry its durable outbox.
        with patch.object(crm_registration, "endpoint", return_value=endpoint):
            failed = crm_registration.dispatch_once(sender=lambda *_: (_ for _ in ()).throw(ConnectionError("offline")))
        self.assertGreaterEqual(failed["failed"], 3, failed)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM crm_registration_outbox WHERE delivered_at IS NULL").fetchone()[0], 3)
            conn.execute("UPDATE crm_registration_outbox SET next_attempt_at=0 WHERE delivered_at IS NULL")

        def send_over_http(payload, url):
            return crm_registration.submit(payload, url, opener=lambda request, timeout: urlopen(request, timeout=timeout))

        with patch.object(crm_registration, "endpoint", return_value=endpoint):
            delivered = crm_registration.dispatch_once(sender=send_over_http)
        self.assertEqual(delivered, {"claimed": 3, "delivered": 3, "failed": 0})
        # Replay the exact signed registration over HTTP; CRM must return the
        # existing identity instead of adding another lead.
        replay_id = send_over_http(payloads[registration.CAROL], endpoint)
        with SessionLocal() as session:
            leads = {lead.telegram_user_id: lead for lead in session.scalars(select(Lead).where(
                Lead.workspace_id == workspace_id)).all()}
            self.assertEqual(set(leads), {registration.ALICE, registration.BOB, registration.CAROL})
            self.assertEqual(leads[registration.ALICE].source_type, "agency")
            self.assertEqual(leads[registration.CAROL].source_type, "referrer")
            self.assertEqual(leads[registration.CAROL].source_partner_id, f"referrer:{registration.BOB}")
            original_id = leads[registration.CAROL].id
            self.assertEqual(replay_id, str(original_id))
            offer = Offer(workspace_id=workspace_id, name="Referral synthetic debit", advertiser="Test",
                          offer_type=OfferType.DEBIT, agency_rate=4000, blogger_payout=1000,
                          lead_reward=250, target_action="Apply", referral_url="https://example.test/apply")
            session.add(offer)
            session.flush()
            session.add(OfferAssignment(workspace_id=workspace_id, lead_id=original_id,
                                        offer_id=offer.id, instructions="Synthetic referral instructions"))
            enqueue_offers_assigned(session, workspace_id, original_id)
            session.commit()
            offer_id = str(offer.id)

        with SessionLocal() as session:
            delivery = deliver_due(session, endpoint=self.base + "/api/integration/crm/events", secret=SECRET)
        self.assertEqual(delivery["failed"], 0, delivery)
        status, offers = self.as_user("/api/offers", registration.CAROL)
        self.assertEqual(status, 200, offers)
        self.assertEqual([offer["id"] for offer in offers["offers"]], [offer_id])
        self.assertEqual(self.as_user("/api/offers", registration.ALICE)[1]["offers"], [])

        # Repeated registration and replay retain the first CRM lead and its source.
        new_code = self.owner_invite()
        self.assertEqual(self.as_user("/api/register", registration.CAROL, invite_code=new_code, consent=True)[0], 200)
        with SessionLocal() as session:
            lead = session.get(Lead, original_id)
            self.assertEqual((lead.source_type, lead.source_partner_id),
                             ("referrer", f"referrer:{registration.BOB}"))
            self.assertEqual(session.scalars(select(Lead).where(Lead.telegram_user_id == registration.CAROL)).all(), [lead])
