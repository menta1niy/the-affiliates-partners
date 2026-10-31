"""Signed CRM blogger binding, Telegram attribution, and owner-only revocation."""
import json
import sqlite3
import unittest
from contextlib import closing

from server import db
from tests import test_registration as h


UUID = "123e4567-e89b-42d3-a456-426614174000"


class BloggerInvitations(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def test_verified_mapping_immutable_first_source_revoke(self):
        db.session({'id': h.OWNER, 'first_name': 'Owner', 'last_name': '', 'username': 'owner'}, h.OWNER)
        self.assertEqual(self.as_user('/api/admin/invitations/blogger', h.OWNER, blogger_uuid=UUID)[0], 404)
        self.assertEqual(self.as_user('/api/admin/invitations/blogger', h.BOB, blogger_uuid=UUID)[0], 403)
        self.assertEqual(db.receive_crm_event({
            'event_id': 'blogger:1', 'type': 'blogger.bound', 'blogger_uuid': UUID,
            'channel': '@verifiedchannel', 'issuer_id': h.OWNER, 'active': True,
        }), {'changed': True})
        status, result = self.as_user('/api/admin/invitations/blogger', h.OWNER, blogger_uuid=UUID)
        self.assertEqual(status, 200)
        code = result['code']
        self.assertTrue(code.startswith('blog_'))
        self.assertEqual(self.as_user('/api/admin/invitations/blogger', h.OWNER, blogger_uuid=UUID)[1]['code'], code)
        self.assertEqual(self.webhook_start(994001, h.ALICE, code)[0], 200)
        self.assertEqual(self.webhook_start(994002, h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/register', h.ALICE, consent=True)[0], 200)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute('SELECT source FROM users WHERE id=?', (h.ALICE,)).fetchone()
            payload = json.loads(conn.execute('SELECT payload FROM crm_registration_outbox WHERE telegram_id=?', (h.ALICE,)).fetchone()[0])
        self.assertEqual(row[0], 'blogger')
        self.assertEqual((payload['source_type'], payload['source_partner_id'], payload['source_channel']),
                         ('blogger', UUID, '@verifiedchannel'))
        self.assertEqual(self.as_user('/api/invitations/revoke', h.OWNER, code=code)[1], {'changed': True})
        self.assertEqual(self.webhook_start(994003, h.BOB, code)[0], 200)
        self.assertEqual(self.as_user('/api/register', h.BOB, consent=True)[0], 400)
        self.assertEqual(self.as_user('/api/session', h.ALICE)[1]['user']['source'], 'blogger')

    def test_mapping_revocation_and_replay_conflict(self):
        db.session({'id': h.OWNER, 'first_name': 'Owner', 'last_name': '', 'username': 'owner'}, h.OWNER)
        event = {'event_id': 'blogger:2', 'type': 'blogger.bound', 'blogger_uuid': UUID,
                 'channel': 'Channel', 'issuer_id': h.OWNER, 'active': True}
        self.assertTrue(db.receive_crm_event(event)['changed'])
        self.assertFalse(db.receive_crm_event(event)['changed'])
        with self.assertRaises(db.Problem):
            db.receive_crm_event({**event, 'channel': 'Forged'})
        code = self.as_user('/api/admin/invitations/blogger', h.OWNER, blogger_uuid=UUID)[1]['code']
        db.receive_crm_event({**event, 'event_id': 'blogger:3', 'active': False})
        self.assertEqual(self.webhook_start(994004, h.BOB, code)[0], 200)
        self.assertEqual(self.as_user('/api/register', h.BOB, consent=True)[0], 400)
        dashboard = self.as_user('/api/admin/dashboard', h.OWNER)[1]
        self.assertFalse(next(i for i in dashboard['invites'] if i['code'] == code)['usable'])


if __name__ == '__main__':
    unittest.main()
