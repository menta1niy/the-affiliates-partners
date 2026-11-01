"""Real CRM-generated HMAC events delivered in reverse order to live Partners HTTP."""
import os
import sys
import unittest
from pathlib import Path
from decimal import Decimal
from uuid import uuid4
from urllib.request import urlopen

from tests import test_registration as registration


class ReverseOrderHTTP(unittest.TestCase):
    stop_server = registration.HttpHarness.stop_server
    as_user = registration.HttpHarness.as_user
    register = registration.HttpHarness.register
    owner_invite = registration.HttpHarness.owner_invite
    webhook_start = registration.HttpHarness.webhook_start
    post = registration.HttpHarness.post

    def setUp(self):
        url, root = os.getenv('TEST_DATABASE_URL'), os.getenv('CRM_BACKEND_ROOT')
        if not url or not root:
            self.skipTest('Requires disposable TEST_DATABASE_URL and CRM_BACKEND_ROOT')
        assert '127.0.0.1:55439' in url and 'e2e' in url
        os.environ['PARTNERS_DATABASE_URL'] = url.replace('postgresql+psycopg://', 'postgresql://')
        os.environ['DATABASE_URL'] = url
        os.environ['APP_ENV'] = 'test'
        os.environ['PARTNERS_CRM_SHARED_SECRET'] = 'reverse-e2e-secret-20261101-01234567890123456789'
        os.environ['PARTNERS_INTEGRATION_SECRET'] = os.environ['PARTNERS_CRM_SHARED_SECRET']
        sys.path.insert(0, str(Path(root)))
        registration.HttpHarness.setUp(self)
        self._next_update_id = 895000

    def test_reverse_versioned_and_legacy_cutover(self):
        from app.core.database import SessionLocal
        from app.models.user import User
        from app.models.workspace import Workspace
        from app.models.enums import WorkspaceKind, LeadStatus, OfferType
        from app.models.lead import Lead
        from app.models.offer import Offer
        from app.models.offer_assignment import OfferAssignment
        from app.models.partners_outbox import PartnersOutboxEvent
        from app.modules.partners.outbox import enqueue_lead_bound, enqueue_offers_assigned, signed_request
        from server import db

        user_id = 895501
        self.assertEqual(self.register(user_id, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', registration.OWNER,
                                      user_id=user_id, decision='approve')[0], 200)
        with SessionLocal() as session:
            owner = User(email=f'reverse-{uuid4()}@example.test', nickname='Synthetic',
                         password_hash='not-a-real-login')
            session.add(owner)
            session.flush()
            workspace = Workspace(name='Reverse signed delivery', kind=WorkspaceKind.TEAM,
                                  created_by=owner.id)
            session.add(workspace)
            session.flush()
            lead = Lead(workspace_id=workspace.id, name='Synthetic', telegram_user_id=user_id,
                        status=LeadStatus.IN_PROGRESS, source_type='agency',
                        source_partner_id=f'agency:{registration.OWNER}')
            session.add(lead)
            session.flush()
            offer = Offer(workspace_id=workspace.id, name='Before revocation',
                          advertiser='Synthetic', offer_type=OfferType.DEBIT,
                          agency_rate=Decimal('300'), blogger_payout=Decimal('100'),
                          lead_reward=Decimal('10'), target_action='Apply')
            session.add(offer)
            session.flush()
            session.add(OfferAssignment(workspace_id=workspace.id, lead_id=lead.id, offer_id=offer.id))
            session.flush()
            enqueue_lead_bound(session, lead)
            enqueue_offers_assigned(session, workspace.id, lead.id)
            offer.is_active = False
            enqueue_offers_assigned(session, workspace.id, lead.id)
            session.commit()
            events = list(session.query(PartnersOutboxEvent).order_by(PartnersOutboxEvent.created_at,
                                                                      PartnersOutboxEvent.id))
            bound = next(event for event in events if event.event_type == 'lead.bound')
            offers = sorted((event for event in events if event.event_type == 'offers.assigned'),
                            key=lambda event: event.payload['snapshot_version'])
            self.assertEqual([event.payload['snapshot_version'] for event in offers], [1, 2])
            requests = [signed_request(event, os.environ['PARTNERS_CRM_SHARED_SECRET'],
                                       self.base + '/api/integration/crm/events') for event in (bound, *offers)]

        def send(request):
            with urlopen(request, timeout=8) as response:
                self.assertEqual(response.status, 200)

        send(requests[0])
        send(requests[2])  # Version 2 revokes the offer.
        self.assertEqual(self.as_user('/api/offers', user_id)[1]['offers'], [])
        send(requests[1])  # Delayed signed version 1 must not resurrect it.
        self.assertEqual(self.as_user('/api/offers', user_id)[1]['offers'], [])
        legacy = dict(offers[0].payload)
        legacy.pop('snapshot_version')
        legacy.update(type='offers.assigned', event_id=str(uuid4()))
        from server.integration import signature
        import json, time
        from urllib.request import Request
        raw = json.dumps(legacy, ensure_ascii=False, separators=(',', ':')).encode()
        stamp = int(time.time())
        old_request = Request(self.base + '/api/integration/crm/events', data=raw, method='POST', headers={
            'Content-Type': 'application/json', 'X-TA-Event-ID': legacy['event_id'],
            'X-TA-Timestamp': str(stamp),
            'X-TA-Signature': signature(raw, stamp, os.environ['PARTNERS_CRM_SHARED_SECRET'])})
        send(old_request)
        self.assertEqual(self.as_user('/api/offers', user_id)[1]['offers'], [])
        with db.transaction() as conn:
            version = conn.execute('SELECT snapshot_version FROM crm_offer_snapshot_versions WHERE crm_lead_id=?',
                                   (str(lead.id),)).fetchone()
            self.assertEqual(version['snapshot_version'], 2)
