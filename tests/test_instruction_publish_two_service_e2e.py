"""Real owner HTTP draft/publish -> signed CRM outbox -> participant HTTP offers."""
import http.cookiejar
import json
import os
import socket
import sys
import threading
import unittest
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor
from uuid import uuid4

from tests import test_registration as identities


class PublishedInstructionHTTP(unittest.TestCase):
    post = identities.HttpHarness.post
    as_user = identities.HttpHarness.as_user
    register = identities.HttpHarness.register
    owner_invite = identities.HttpHarness.owner_invite
    webhook_start = identities.HttpHarness.webhook_start
    stop_server = identities.HttpHarness.stop_server

    def setUp(self):
        url = os.environ.get('TEST_DATABASE_URL')
        root = os.environ.get('CRM_BACKEND_ROOT')
        if not url or not root:
            self.skipTest('CRM_BACKEND_ROOT and TEST_DATABASE_URL required')
        assert '127.0.0.1:55439' in url and 'e2e' in url
        os.environ['PARTNERS_DATABASE_URL'] = url.replace('postgresql+psycopg://', 'postgresql://')
        os.environ['DATABASE_URL'] = url
        os.environ['APP_ENV'] = 'test'
        os.environ['SESSION_COOKIE_SECURE'] = 'false'
        secret = 'synthetic-publish-e2e-secret-20261031-0123456789'
        os.environ['PARTNERS_CRM_SHARED_SECRET'] = secret
        os.environ['PARTNERS_INTEGRATION_SECRET'] = secret
        sys.path.insert(0, str(Path(root)))
        identities.HttpHarness.setUp(self)
        self._next_update_id = 740000
        self.secret = secret

    def test_owner_draft_publish_republish_signed_catalog(self):
        import uvicorn
        from sqlalchemy import select
        from app.main import app
        from app.core.database import SessionLocal
        from app.core.security import hash_password
        from app.models.user import User
        from app.models.workspace import Workspace, WorkspaceMembership
        from app.models.enums import WorkspaceKind, WorkspaceRole, OfferType, LeadStatus
        from app.models.offer import Offer
        from app.models.offer_assignment import OfferAssignment
        from app.models.lead import Lead
        from app.modules.partners.outbox import deliver_due, enqueue_lead_bound, enqueue_offers_assigned

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen(128)
        crm = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
        crm.install_signal_handlers = lambda: None
        thread = threading.Thread(target=crm.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(timeout=4))
        self.addCleanup(lambda: setattr(crm, 'should_exit', True))
        base = f'http://127.0.0.1:{sock.getsockname()[1]}'

        owner_email = f'instruction-{uuid4()}@example.test'
        password = 'SyntheticOwnerPassword123!'
        participant = 749201
        with SessionLocal() as session:
            owner = User(email=owner_email, nickname='Instruction owner', password_hash=hash_password(password))
            session.add(owner)
            session.flush()
            workspace = Workspace(name='Instruction HTTP E2E', kind=WorkspaceKind.TEAM, created_by=owner.id)
            session.add(workspace)
            session.flush()
            session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
            offer = Offer(workspace_id=workspace.id, name='Synthetic publish offer', advertiser='Test',
                          offer_type=OfferType.DEBIT, agency_rate=Decimal('4000'),
                          blogger_payout=Decimal('1000'), lead_reward=Decimal('250'),
                          target_action='Apply', referral_url='https://example.test/apply')
            session.add(offer)
            session.commit()
            wid, oid = workspace.id, offer.id

        self.assertEqual(self.register(participant, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', identities.OWNER,
                                      user_id=participant, decision='approve')[0], 200)
        with SessionLocal() as session:
            lead = Lead(workspace_id=wid, name='Synthetic participant', telegram_user_id=participant,
                        status=LeadStatus.IN_PROGRESS, source_type='agency',
                        source_partner_id=f'agency:{identities.OWNER}')
            session.add(lead)
            session.flush()
            session.add(OfferAssignment(workspace_id=wid, lead_id=lead.id, offer_id=oid))
            session.flush()
            enqueue_lead_bound(session, lead)
            session.commit()
            lead_id = lead.id

        def deliver():
            with SessionLocal() as session:
                result = deliver_due(session, endpoint=self.base + '/api/integration/crm/events', secret=self.secret)
            self.assertEqual(result['failed'], 0, result)
            return result

        self.assertEqual(deliver()['sent'], 1)
        with SessionLocal() as session:
            enqueue_offers_assigned(session, wid, lead_id)
            session.commit()
        self.assertEqual(deliver()['sent'], 1)
        jar = http.cookiejar.CookieJar()
        client = build_opener(HTTPCookieProcessor(jar))

        def request(path, body):
            data = json.dumps(body).encode()
            headers = {'Content-Type': 'application/json'}
            cookies = [c for c in jar if c.name == 'the_affiliates_csrf']
            if cookies:
                headers['X-CSRF-Token'] = cookies[0].value
            try:
                with client.open(Request(base + path, data, headers, method='POST'), timeout=8) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                return exc.code, json.loads(exc.read())

        self.assertEqual(request('/api/v1/auth/login', {'email': owner_email, 'password': password})[0], 200)
        root = f'/api/v1/workspaces/{wid}/offers/{oid}/instructions'

        def visible():
            status, response = self.as_user('/api/offers', participant)
            self.assertEqual(status, 200)
            self.assertEqual(len(response['offers']), 1)
            return response['offers'][0]

        first_text = 'Published v1 <script>alert(1)</script>'
        initial = {'text': first_text, 'images': ['https://example.test/image.png'],
                   'links': ['https://example.test/details']}
        status, draft = request(root + '/drafts', initial)
        self.assertEqual(status, 201, draft)
        self.assertEqual(draft['status'], 'draft')
        self.assertNotIn(first_text, json.dumps(visible()))
        self.assertEqual(deliver()['sent'], 0)

        status, published = request(root + '/' + draft['id'] + '/publish', {})
        self.assertEqual(status, 200, published)
        self.assertEqual(published['status'], 'published')
        self.assertGreaterEqual(deliver()['sent'], 1)
        snapshot = visible()['published_instruction']
        self.assertEqual(snapshot['text'], first_text)
        self.assertEqual(snapshot['images'][0]['url'], initial['images'][0])
        self.assertEqual(snapshot['links'][0]['url'], initial['links'][0])

        second_text = 'Replacement after revoking old instructions'
        status, newer = request(root + '/drafts', {'text': second_text, 'images': [], 'links': []})
        self.assertEqual(status, 201, newer)
        self.assertEqual(visible()['published_instruction']['text'], first_text)
        status, result = request(root + '/' + newer['id'] + '/publish', {})
        self.assertEqual(status, 200, result)
        self.assertGreaterEqual(deliver()['sent'], 1)
        latest = visible()['published_instruction']
        self.assertEqual(latest, {'text': second_text, 'images': [], 'links': []})
        self.assertNotIn(first_text, json.dumps(visible()))
