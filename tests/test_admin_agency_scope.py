"""Global operational admin/staff permissions, with explicit owner safeguards."""
import json
import time
import unittest

from server import db
from tests.test_registration import HttpHarness, OWNER


class AdminAgencyScopeTests(unittest.TestCase):
    post = HttpHarness.post
    as_user = HttpHarness.as_user
    webhook_start = HttpHarness.webhook_start
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

    def test_admin_dashboard_and_audit_are_global_like_owner(self):
        status, dashboard = self.as_user('/api/admin/dashboard', self.admin)
        self.assertEqual(status, 200)
        self.assertTrue({self.a,self.b,self.admin,self.other_admin,self.staff_a,self.staff_b,
                         self.lead_a,self.lead_b,OWNER}.issubset({x['id'] for x in dashboard['users']}))
        self.assertEqual({x['code'] for x in dashboard['invites']},
                         {'ref_AAAAAAAA','ref_BBBBBBBB'})
        self.assertIn('foreign-secret', json.dumps(dashboard))
        self.assertIn('ref_BBBBBBBB', json.dumps(dashboard))
        status, events = self.as_user('/api/admin/audit', self.admin)
        self.assertEqual(status, 200)
        self.assertIn('foreign-secret', json.dumps(events))
        self.assertTrue(all('actor_name' in event and 'target_name' in event for event in events['events']))
        self.assertIn('Test', {event['actor_name'] for event in events['events']})
        self.assertEqual(self.as_user('/api/admin/dashboard', OWNER)[0], 200)
        self.assertIn('ref_BBBBBBBB', json.dumps(self.as_user('/api/admin/dashboard', OWNER)[1]))

    def test_dashboard_discloses_truncated_list(self):
        now = int(time.time())
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO users(id,first_name,role,status,agency_id,registered_at,updated_at) "
                "VALUES(?, 'Synthetic', 'lead', 'pending', ?, ?, ?)",
                [(900000 + i, self.a, now + i, now + i) for i in range(205)],
            )
        status, dashboard = self.as_user('/api/admin/dashboard', self.admin)
        self.assertEqual(status, 200)
        self.assertEqual(len(dashboard['users']), 200)
        self.assertTrue(dashboard['users_truncated'])
        self.assertGreater(dashboard['counts']['pending'], len(dashboard['pending']))

    def test_paginated_search_covers_older_rows_across_agencies(self):
        now = int(time.time())
        with db.transaction() as conn:
            conn.executemany(
                "INSERT INTO users(id,first_name,role,status,agency_id,registered_at,updated_at) "
                "VALUES(?, ?, 'lead', 'pending', ?, ?, ?)",
                [(920000 + i, 'Paged Agent', self.a, now + i, now + i) for i in range(207)],
            )
            conn.execute("UPDATE users SET first_name='Hidden Needle' WHERE id=?", (self.lead_b,))
        expected = 207 + 9
        pages = []
        for page in range(1, 6):
            status, result = self.as_user('/api/admin/users', self.admin, page=page)
            self.assertEqual(status, 200)
            self.assertEqual(result['total'], expected)
            self.assertLessEqual(len(result['users']), 50)
            pages.extend(user['id'] for user in result['users'])
        self.assertEqual(len(pages), expected)
        self.assertEqual(len(set(pages)), expected)
        self.assertIn(self.lead_b, pages)
        status, found = self.as_user('/api/admin/users', self.admin, query=str(920000), status='pending')
        self.assertEqual(status, 200)
        self.assertEqual([user['id'] for user in found['users']], [920000])
        self.assertEqual(self.as_user('/api/admin/users', self.admin, query='Hidden Needle')[1]['total'], 1)
        self.assertEqual(self.as_user('/api/admin/users', OWNER, query='Hidden Needle')[1]['total'], 1)

    def test_paginated_users_validate_inputs_and_staff_global_access(self):
        with db.transaction() as conn:
            conn.execute('UPDATE users SET manager_id=? WHERE id=?', (self.staff_a, self.lead_a))
        status, result = self.as_user('/api/admin/users', self.staff_a)
        self.assertEqual(status, 200)
        self.assertIn(self.lead_a, [user['id'] for user in result['users']])
        self.assertIn(self.lead_b, [user['id'] for user in result['users']])
        for bad in [{'page':0}, {'page':True}, {'page':1.5}, {'status':['pending']},
                    {'role':{'x':1}}, {'query':'x'*121}]:
            with self.subTest(bad=bad):
                self.assertEqual(self.as_user('/api/admin/users', self.admin, **bad)[0], 400)
        self.assertEqual(self.as_user('/api/admin/users', self.lead_a)[0], 403)

    def test_open_registration_and_unassigned_direct_referral_appear_in_both_admin_lists(self):
        open_id, referred_id = 991201, 991202
        status, registered = self.as_user('/api/register', open_id)
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered['user']['status'], 'active')
        status, invite = self.as_user('/api/invitations/referral', OWNER)
        self.assertEqual(status, 200, invite)
        code = invite['code']
        self.assertEqual(self.webhook_start(991203, referred_id, code)[0], 200)
        status, registered = self.as_user('/api/register', referred_id)
        self.assertEqual(status, 200, registered)
        self.assertEqual(registered['user']['source'], 'referral')
        with db.transaction() as conn:
            open_user = db.get_user(conn, open_id)
            referred_user = db.get_user(conn, referred_id)
            self.assertEqual(open_user['manager_id'], OWNER)
            self.assertIsNone(referred_user['manager_id'])
            self.assertEqual(referred_user['agency_id'], OWNER)
        for candidate in (open_id, referred_id):
            for actor in (OWNER, self.admin, self.other_admin):
                with self.subTest(candidate=candidate, actor=actor):
                    query = str(candidate)
                    code, page = self.as_user('/api/admin/users', actor, query=query, role='lead', status='active')
                    self.assertEqual(code, 200, page)
                    self.assertIn(candidate, [row['id'] for row in page['users']])
                    self.assertEqual(page['total'], 1)
                    code, candidates = self.as_user('/api/admin/mvp/assignment-candidates', actor, query=query)
                    self.assertEqual(code, 200, candidates)
                    self.assertEqual([row['id'] for row in candidates['users']], [candidate])
                    self.assertEqual(self.as_user('/api/admin/participant', actor, user_id=candidate)[0], 200)
            for actor in (self.staff_a, self.staff_b):
                self.assertEqual(self.as_user('/api/admin/users', actor, query=str(candidate))[1]['total'], 1)
                self.assertEqual(self.as_user('/api/admin/participant', actor, user_id=candidate)[0], 200)
        for actor in (self.admin, self.other_admin, self.staff_a, self.staff_b):
            dashboard = self.as_user('/api/admin/dashboard', actor)[1]
            self.assertTrue({open_id, referred_id}.issubset({u['id'] for u in dashboard['users']}))

    def test_manual_mvp_offer_assignment_is_global_for_managers(self):
        payload={"name":"Банковская карта", "category":"Карты", "target_action":"Активация",
                 "payout_rub":800, "hold_days":14, "instructions":"Инструкция", "referral_url":""}
        self.assertEqual(self.as_user('/api/admin/mvp/offer', self.staff_a, **payload)[0],200)
        status, created=self.as_user('/api/admin/mvp/offer', OWNER, **payload)
        self.assertEqual(status,200,created)
        offer=created['offer_id']
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', self.admin,
                                     user_id=self.lead_b, offer_id=offer, note='')[0],200)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', self.admin,
                                     user_id=self.lead_a, offer_id=offer, note='')[0],200)
        self.assertEqual(self.as_user('/api/admin/participant',self.admin,user_id=self.lead_a)[1]['manual']['statistics']['total'],1)
        self.assertEqual(self.as_user('/api/admin/participant',self.other_admin,user_id=self.lead_a)[0],200)

    def test_admin_and_staff_catalog_crud(self):
        payload={"name":"Offer", "category":"Card", "target_action":"Apply", "payout_rub":800, "hold_days":14}
        status, result = self.as_user('/api/admin/mvp/offer', self.admin, **payload)
        self.assertEqual(status, 200, result)
        offer = result['offer_id']
        edited = dict(payload, offer_id=offer, name='Updated offer')
        self.assertEqual(self.as_user('/api/admin/mvp/offer', self.staff_a, **edited)[0],200)
        self.assertEqual(self.as_user('/api/admin/mvp/offer', self.admin, **edited)[0],200)
        offers = self.as_user('/api/admin/mvp/catalog', OWNER)[1]['offers']
        self.assertEqual(next(x for x in offers if x['id']==offer)['name'], 'Updated offer')
        self.assertEqual(self.as_user('/api/admin/mvp/assignment',self.admin,user_id=self.lead_a,offer_id=offer)[0],200)
        self.assertEqual(self.as_user('/api/admin/mvp/offer/delete',self.staff_a,offer_id=offer)[0],200)
        # A deleted offer remains deleted; exercise the administrator's
        # independent delete privilege on a fresh catalogue entry instead.
        status, fresh = self.as_user('/api/admin/mvp/offer', self.admin, **payload)
        self.assertEqual(status,200,fresh)
        self.assertEqual(self.as_user('/api/admin/mvp/offer/delete',self.admin,
                                      offer_id=fresh['offer_id'])[0],200)
        self.assertNotIn(offer,[x['id'] for x in self.as_user('/api/admin/mvp/catalog',OWNER)[1]['offers']])
        with db.transaction() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM manual_assignments WHERE offer_id=?',(offer,)).fetchone()[0],1)

    def test_bulk_assignment_allows_managers_cross_agency_atomically(self):
        payload={"name":"Тестовый оффер","category":"Дебетовые карты","target_action":"Оформить",
                 "payout_rub":900,"hold_days":7}
        status,created=self.as_user("/api/admin/mvp/offer",OWNER,**payload)
        self.assertEqual(status,200,created)
        offer=created["offer_id"]
        status,candidates=self.as_user("/api/admin/mvp/assignment-candidates",self.admin)
        self.assertEqual(status,200,candidates)
        self.assertEqual({user["id"] for user in candidates["users"]},{self.lead_a,self.lead_b})
        self.assertEqual(self.as_user("/api/admin/mvp/assignment-candidates",self.other_admin,
            query=str(self.lead_a))[1]["total"],1)
        request={"mode":"offer_to_leads","offer_id":offer,"user_ids":[self.lead_a,self.lead_b]}
        self.assertEqual(self.as_user("/api/admin/mvp/bulk-assignment",self.admin,**request)[1]["created"],2)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM manual_assignments").fetchone()[0],2)
        request["user_ids"]=[self.lead_a]
        self.assertEqual(self.as_user("/api/admin/mvp/bulk-assignment",self.admin,**request)[1]["created"],0)
        self.assertEqual(self.as_user("/api/admin/mvp/bulk-assignment",self.staff_a,**request)[0],200)

    def test_cross_agency_access_allowed_for_admin(self):
        for path, payload in [
            ('/api/admin/decision', {'user_id': self.lead_b, 'decision': 'block', 'reason': 'test'}),
            ('/api/admin/assign', {'user_id': self.lead_b, 'manager_id': self.staff_a}),
            ('/api/admin/assign', {'user_id': self.lead_a, 'manager_id': self.staff_b}),
        ]:
            with self.subTest(path=path, payload=payload):
                self.assertEqual(self.as_user(path, self.admin, **payload)[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', self.admin, user_id=self.lead_a, manager_id=self.staff_a)[0], 200)

    def test_unscoped_active_admin_still_has_global_operational_access(self):
        with db.transaction() as conn:
            conn.execute('UPDATE users SET agency_id=NULL WHERE id=?', (self.admin,))
        for path, payload in [('/api/admin/dashboard', {}), ('/api/admin/audit', {}),
                              ('/api/admin/assign', {'user_id': self.lead_a, 'manager_id': self.staff_a})]:
            self.assertEqual(self.as_user(path, self.admin, **payload)[0], 200)

    def test_agency_invitation_can_cross_assignee_tenant(self):
        with db.transaction() as conn:
            before = conn.execute("SELECT count(*) FROM invitations").fetchone()[0]
            audits = conn.execute("SELECT count(*) FROM audit").fetchone()[0]
        status, _ = self.as_user('/api/admin/invitations', self.admin, assignee_id=self.staff_b)
        self.assertEqual(status, 200)
        with db.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM invitations").fetchone()[0], before + 1)
            self.assertGreater(conn.execute("SELECT count(*) FROM audit").fetchone()[0], audits)
        status, own = self.as_user('/api/admin/invitations', self.admin, assignee_id=self.staff_a)
        self.assertEqual(status, 200)
        self.assertEqual(own['assignee_id'], self.staff_a)
        status, global_invite = self.as_user('/api/admin/invitations', OWNER, assignee_id=self.staff_b)
        self.assertEqual(status, 200)
        self.assertEqual(global_invite['assignee_id'], self.staff_b)
        with db.transaction() as conn:
            conn.execute('UPDATE users SET agency_id=NULL WHERE id=?', (self.admin,))
        self.assertEqual(self.as_user('/api/admin/invitations', self.admin, assignee_id=self.staff_a)[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', self.admin)[0], 200)
