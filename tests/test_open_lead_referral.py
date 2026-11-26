"""Open-registration leads can refer without pre-existing attribution."""
import unittest
import json
import time

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, CAROL, init_data


class OpenLeadReferralTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    webhook_start = HttpHarness.webhook_start

    def test_open_lead_can_issue_reusable_attributed_link(self):
        status, created = self.as_user('/api/register', ALICE, consent=True, adult_confirmed=True)
        self.assertEqual(status, 200, created)
        self.assertEqual(created['user']['status'], 'active')
        self.assertIsNone(created['user']['source'])
        self.assertIsNone(created['user']['referrer_id'])
        status, invitation = self.as_user('/api/invitations/referral', ALICE)
        self.assertEqual(status, 200, invitation)
        code = invitation['code']
        self.assertRegex(code, r'^[A-Z0-9]{6}$')
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[1]['code'], code)
        self.assertEqual(self.webhook_start(990701, BOB, code)[0], 200)
        status, referred = self.as_user('/api/register', BOB, consent=True, adult_confirmed=True)
        self.assertEqual(status, 200, referred)
        self.assertEqual(referred['user']['source'], 'referral')
        self.assertEqual(referred['user']['referrer_id'], ALICE)
        with db.transaction() as conn:
            self.assertEqual(db.get_user(conn, BOB)['introduced_by_id'], ALICE)
        self.assertEqual(self.webhook_start(990702, CAROL, code)[0], 200)
        self.assertEqual(self.as_user('/api/register', CAROL, consent=True, adult_confirmed=True)[1]['user']['referrer_id'], ALICE)

    def test_requires_verified_identity_and_consent_and_prevents_self_use(self):
        self.assertEqual(self.post('/api/invitations/referral', {'initData': 'invalid'})[0], 401)
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[0], 403)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=False)[0], 400)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True, adult_confirmed=True)[0], 200)
        code = self.as_user('/api/invitations/referral', ALICE)[1]['code']
        with db.transaction() as conn:
            self.assertFalse(db.valid_invitation_source(conn, ALICE, code))
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True, adult_confirmed=True, invite_code=code)[1]['user']['source'], None)
        with db.transaction() as conn:
            conn.execute("UPDATE users SET status='blocked' WHERE id=?", (ALICE,))
            self.assertFalse(db.valid_invitation_source(conn, BOB, code))
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[0], 403)
        self.assertEqual(self.webhook_start(990703, BOB, code)[0], 200)
        self.assertEqual(self.as_user('/api/register', BOB, consent=True, adult_confirmed=True)[0], 200)
        with db.transaction() as conn:
            self.assertIsNone(db.get_user(conn, BOB)['source'])

    def test_legacy_active_lead_without_consent_cannot_issue_or_use_link(self):
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True, adult_confirmed=True)[0], 200)
        code = self.as_user('/api/invitations/referral', ALICE)[1]['code']
        with db.transaction() as conn:
            conn.execute('UPDATE users SET consent_at=NULL WHERE id=?', (ALICE,))
            self.assertFalse(db.valid_invitation_source(conn, BOB, code))
        self.assertEqual(self.as_user('/api/invitations/referral', ALICE)[0], 403)

    def test_staff_participant_details_include_scoped_safe_offer_events(self):
        from server import mvp, offer_workflow

        self.assertEqual(self.as_user('/api/register', ALICE, consent=True, adult_confirmed=True)[0], 200)
        self.assertEqual(self.as_user('/api/register', BOB, consent=True, adult_confirmed=True)[0], 200)
        staff, outsider = 990711, 990712
        now = int(time.time())
        with db.transaction() as conn:
            db.ensure_owner(conn, OWNER)
            mvp.schema(conn)
            offer_workflow.schema(conn)
            for uid in (staff, outsider):
                conn.execute("INSERT INTO users(id,internal_id,first_name,role,status,agency_id,registered_at,updated_at) "
                             "VALUES(?,?,?,'staff','active',?,?,?)",
                             (uid, db.allocate_internal_id(conn), 'Manager', OWNER, now, now))
            conn.execute('UPDATE users SET manager_id=? WHERE id=?', (staff, ALICE))
            conn.execute('UPDATE users SET manager_id=? WHERE id=?', (outsider, BOB))
            conn.execute("INSERT INTO manual_offers(id,name,category,target_action,payout_rub,hold_days,created_at,updated_at) "
                         "VALUES('offer-test','Test','Cards','Apply',100,1,?,?)", (now, now))
            conn.execute("INSERT INTO manual_offer_events(id,telegram_id,offer_id,kind,lead_stage,proof_url,"
                         "evidence_data,evidence_type,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                         ('e1', ALICE, 'offer-test', 'stage', 'application_sent', 'https://example.test/proof',
                          b'private-content', json.dumps({'name': 'proof.pdf', 'mime': 'application/pdf'}), now))
        detail = db.admin_participant_detail(staff, OWNER, ALICE)
        events = detail['offer_events']
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['file_name'], events[0]['file_mime'], events[0]['has_screenshot']),
                         ('proof.pdf', 'application/pdf', True))
        self.assertEqual(events[0]['proof_url'], 'https://example.test/proof')
        self.assertNotIn('evidence_data', events[0])
        self.assertIn('finance', detail)
        self.assertIn('statistics', detail)
        self.assertIn('finance', db.admin_participant_detail(outsider, OWNER, ALICE))
        self.assertIn('finance', self.as_user('/api/admin/participant', OWNER, user_id=ALICE)[1])


if __name__ == '__main__':
    unittest.main()
