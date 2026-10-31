"""Agency admins must not see or mutate records from another agency."""
import json
import time
import unittest

from server import db
from tests.test_registration import HttpHarness, OWNER


class AdminAgencyScopeTests(unittest.TestCase):
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    stop_server = HttpHarness.stop_server

    def setUp(self):
        HttpHarness.setUp(self)
        db.initialize()
        self.a, self.b = 881011, 881012
        self.admin, self.other_admin = 881021, 881022
        self.lead_a, self.lead_b = 881031, 881032
        self.staff_a, self.staff_b = 881041, 881042
        now = int(time.time())
        with db.transaction() as conn:
            db.ensure_owner(conn, OWNER)
            for uid, role, agency in [
                (self.a, 'staff', self.a), (self.b, 'staff', self.b),
                (self.admin, 'admin', self.a), (self.other_admin, 'admin', self.b),
                (self.staff_a, 'staff', self.a), (self.staff_b, 'staff', self.b),
                (self.lead_a, 'lead', self.a), (self.lead_b, 'lead', self.b),
            ]:
                conn.execute("INSERT INTO users(id,first_name,role,status,agency_id,registered_at,updated_at) VALUES(?, 'Test', ?, 'active', ?, ?, ?)", (uid, role, agency, now, now))
            conn.execute("INSERT INTO invitations(code,kind,issuer_id,created_at) VALUES('ref_AAAAAAAA','referral',?,?)", (self.staff_a, now))
            conn.execute("INSERT INTO invitations(code,kind,issuer_id,created_at) VALUES('ref_BBBBBBBB','referral',?,?)", (self.staff_b, now))
            db.audit(conn, self.staff_a, 'local', self.lead_a, 'local-only')
            db.audit(conn, self.staff_b, 'foreign', self.lead_b, 'foreign-secret')

    def test_admin_dashboard_and_audit_scoped_but_owner_global(self):
        status, dashboard = self.as_user('/api/admin/dashboard', self.admin)
        self.assertEqual(status, 200)
        self.assertEqual({x['id'] for x in dashboard['users']}, {self.a, self.admin, self.staff_a, self.lead_a})
        self.assertEqual({x['code'] for x in dashboard['invites']}, {'ref_AAAAAAAA'})
        self.assertNotIn('foreign-secret', json.dumps(dashboard))
        self.assertNotIn('ref_BBBBBBBB', json.dumps(dashboard))
        status, events = self.as_user('/api/admin/audit', self.admin)
        self.assertEqual(status, 200)
        self.assertNotIn('foreign-secret', json.dumps(events))
        self.assertEqual(self.as_user('/api/admin/dashboard', OWNER)[0], 200)
        self.assertIn('ref_BBBBBBBB', json.dumps(self.as_user('/api/admin/dashboard', OWNER)[1]))

    def test_cross_agency_access_denied_and_local_assignment_allowed(self):
        for path, payload in [
            ('/api/admin/decision', {'user_id': self.lead_b, 'decision': 'block', 'reason': 'test'}),
            ('/api/admin/assign', {'user_id': self.lead_b, 'manager_id': self.staff_a}),
            ('/api/admin/assign', {'user_id': self.lead_a, 'manager_id': self.staff_b}),
        ]:
            with self.subTest(path=path, payload=payload):
                self.assertEqual(self.as_user(path, self.admin, **payload)[0], 403)
        self.assertEqual(self.as_user('/api/admin/assign', self.admin, user_id=self.lead_a, manager_id=self.staff_a)[0], 200)

    def test_unscoped_admin_fails_closed(self):
        with db.transaction() as conn:
            conn.execute('UPDATE users SET agency_id=NULL WHERE id=?', (self.admin,))
        for path, payload in [('/api/admin/dashboard', {}), ('/api/admin/audit', {}),
                              ('/api/admin/assign', {'user_id': self.lead_a, 'manager_id': self.staff_a})]:
            self.assertEqual(self.as_user(path, self.admin, **payload)[0], 403)
