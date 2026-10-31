"""Focused lifecycle boundaries against actual HTTP API and isolated SQLite."""
import sqlite3
import time
import unittest
from contextlib import closing

from tests import test_registration as h


class LifecycleEdges(unittest.TestCase):
    setUp = h.HttpHarness.setUp
    stop_server = h.HttpHarness.stop_server
    post = h.HttpHarness.post
    as_user = h.HttpHarness.as_user
    owner_invite = h.HttpHarness.owner_invite
    register = h.HttpHarness.register
    webhook_start = h.HttpHarness.webhook_start

    def rows(self, sql, args=()):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(sql, args).fetchall()

    def test_independent_agency_first_source_and_issuer_eligibility(self):
        first, second = self.owner_invite(), self.owner_invite()
        self.assertNotEqual(first, second)
        self.assertEqual(self.webhook_start(81001, h.BOB, first)[0], 200)
        self.assertEqual(self.webhook_start(81002, h.BOB, second)[0], 200)
        self.assertEqual(self.as_user('/api/register', h.BOB, invite_code=second, consent=True)[0], 409)
        self.assertEqual(self.as_user('/api/register', h.BOB, consent=True)[0], 200)
        self.assertEqual(self.rows('SELECT active FROM invitations WHERE code=?', (first,)), [(0,)])
        self.assertEqual(self.rows('SELECT active FROM invitations WHERE code=?', (second,)), [(1,)])
        self.assertEqual(self.as_user('/api/invitations/referral', h.BOB)[0], 403)
        self.assertEqual(self.as_user('/api/admin/invitations', h.BOB)[0], 403)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.BOB, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', h.BOB)[0], 403)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.BOB, role='referrer')[0], 200)
        self.assertEqual(self.as_user('/api/invitations/referral', h.BOB)[0], 200)
        self.assertEqual(self.as_user('/api/admin/invitations', h.BOB)[0], 403)

    def test_approval_block_and_manager_change_cannot_rewrite_attribution(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='staff')[0], 200)
        self.assertEqual(self.register(h.BOB, self.owner_invite())[0], 200)
        original = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual(original['source'], 'agency')
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.BOB, manager_id=h.ALICE)[0], 200)
        after = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual(after['manager_id'], h.ALICE)
        self.assertEqual((after['source'], after['agency_id'], after['referrer_id']),
                         (original['source'], original['agency_id'], original['referrer_id']))
        self.assertEqual(self.as_user('/api/admin/decision', h.ALICE, user_id=h.BOB, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.BOB, decision='block', reason='Compliance review')[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.ALICE, user_id=h.BOB, decision='approve')[0], 403)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.BOB, decision='approve')[0], 200)
        restored = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual((restored['source'], restored['agency_id'], restored['referrer_id']),
                         (original['source'], original['agency_id'], original['referrer_id']))

    def test_correction_requires_reason_and_outbox_survives_http_restart(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='referrer')[0], 200)
        self.assertEqual(self.register(h.BOB, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/attribution', h.OWNER, user_id=h.BOB, source='referral', referrer_id=h.ALICE, reason='')[0], 400)
        self.assertEqual(self.as_user('/api/admin/attribution', h.BOB, user_id=h.BOB, source='referral', referrer_id=h.ALICE, reason='verified')[0], 403)
        response, data = self.as_user('/api/admin/attribution', h.OWNER, user_id=h.BOB, source='referral', referrer_id=h.ALICE, reason='verified evidence')
        self.assertEqual(response, 200, data)
        self.assertTrue(data['changed'])
        events = self.rows("SELECT details FROM audit WHERE action='attribution_correction' AND target_id=?", (h.BOB,))
        self.assertEqual(len(events), 1)
        self.assertIn('verified evidence', events[0][0])
        outbox = self.rows('SELECT event_key,chat_id,sent_at FROM notifications_outbox ORDER BY id')
        self.assertIn((f'register:{h.BOB}', h.OWNER, None), outbox)
        self.assertTrue(any(key.startswith(f'decision:{h.ALICE}:active:') for key, _, _ in outbox))
        self.stop_server()
        from http.server import ThreadingHTTPServer
        import threading
        from server.api import Handler
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.assertEqual(self.rows('SELECT event_key,chat_id,sent_at FROM notifications_outbox ORDER BY id'), outbox)
        self.assertEqual(self.as_user('/api/session', h.BOB)[1]['user']['referrer_id'], h.ALICE)

    def test_staff_assigned_agency_and_referrer_lead_access(self):
        # A staff user's agency comes from the owner, while the staff Telegram ID
        # is the manager; a referrer's downstream lead remains under that manager.
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='staff')[0], 200)
        code = self.owner_invite(assignee_id=h.ALICE)
        self.assertEqual(self.register(h.BOB, code)[0], 200)
        bob = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual((bob['source'], bob['agency_id'], bob['manager_id']), ('agency', h.OWNER, h.ALICE))
        self.assertEqual(self.as_user('/api/admin/decision', h.ALICE, user_id=h.BOB, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.BOB, role='referrer')[0], 200)
        status, response = self.as_user('/api/invitations/referral', h.BOB)
        self.assertEqual(status, 200, response)
        self.assertEqual(self.register(h.CAROL, response['invite_code'])[0], 200)
        carol = self.as_user('/api/session', h.CAROL)[1]['user']
        self.assertEqual((carol['source'], carol['agency_id'], carol['manager_id'], carol['referrer_id']),
                         ('referral', h.OWNER, h.ALICE, h.BOB))
        status, dashboard = self.as_user('/api/admin/dashboard', h.ALICE)
        self.assertEqual(status, 200, dashboard)
        self.assertIn(h.CAROL, [user['id'] for user in dashboard['users']])
        self.assertEqual(self.as_user('/api/admin/decision', h.ALICE, user_id=h.CAROL, decision='approve')[0], 200)

    def test_stale_assignee_cannot_register_against_pending_agency(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='staff')[0], 200)
        code = self.owner_invite(assignee_id=h.ALICE)
        self.assertEqual(self.webhook_start(995001, h.BOB, code)[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='block', reason='Assignee disabled')[0], 200)
        status, result = self.as_user('/api/register', h.BOB, consent=True)
        self.assertEqual(status, 409, result)
        self.assertEqual(self.as_user('/api/session', h.BOB)[1]['status'], 'invited')
        self.assertEqual(self.rows('SELECT id FROM users WHERE id=?', (h.BOB,)), [])

    def test_introduced_by_issuer_not_assignee_and_correction_restart(self):
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='staff')[0], 200)
        # OWNER issued this invitation; ALICE is assigned only as manager.
        code = self.owner_invite(assignee_id=h.ALICE)
        self.assertEqual(self.register(h.BOB, code)[0], 200)
        bob = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual((bob['introduced_by_id'], bob['agency_id'], bob['manager_id']),
                         (h.OWNER, h.OWNER, h.ALICE))
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.BOB, manager_id=h.OWNER)[0], 200)
        changed_manager = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual((changed_manager['introduced_by_id'], changed_manager['agency_id'], changed_manager['manager_id']),
                         (h.OWNER, h.OWNER, h.OWNER))
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.BOB, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.BOB, role='referrer')[0], 200)
        ref_code = self.as_user('/api/invitations/referral', h.BOB)[1]['invite_code']
        self.assertEqual(self.register(h.CAROL, ref_code)[0], 200)
        carol = self.as_user('/api/session', h.CAROL)[1]['user']
        self.assertEqual((carol['introduced_by_id'], carol['referrer_id']), (h.BOB, h.BOB))
        # Correct agency introducer to an eligible staff member; not the current manager.
        status, correction = self.as_user('/api/admin/attribution', h.OWNER, user_id=h.BOB,
                                          source='agency', agency_id=h.OWNER, introduced_by_id=h.ALICE,
                                          reason='Verified original staff introduction')
        self.assertEqual(status, 200, correction)
        self.assertTrue(correction['changed'])
        self.assertEqual((correction['user']['introduced_by_id'], correction['user']['manager_id']),
                         (h.ALICE, h.OWNER))
        audits = self.rows("SELECT details FROM audit WHERE action='attribution_correction' AND target_id=?", (h.BOB,))
        self.assertEqual(len(audits), 1)
        self.assertIn('Verified original staff introduction', audits[0][0])
        self.stop_server()
        from http.server import ThreadingHTTPServer
        from server.api import Handler
        import threading
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        persisted = self.as_user('/api/session', h.BOB)[1]['user']
        self.assertEqual((persisted['introduced_by_id'], persisted['manager_id'], persisted['agency_id']),
                         (h.ALICE, h.OWNER, h.OWNER))

    def test_legacy_schema_nullable_intro_backfill_and_stale_session(self):
        # Build an old users table before the live schema migration.
        from server import db
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("""CREATE TABLE users (
                id INTEGER PRIMARY KEY, first_name TEXT NOT NULL,
                last_name TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'lead', status TEXT NOT NULL DEFAULT 'pending',
                agency_id INTEGER, referrer_id INTEGER, manager_id INTEGER,
                registered_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                decision_reason TEXT NOT NULL DEFAULT '', source TEXT, consent_at INTEGER)""")
            now = int(time.time())
            conn.execute("INSERT INTO users(id,first_name,role,status,registered_at,updated_at) VALUES(?,?,'owner','active',?,?)",
                         (h.OWNER, 'Owner', now, now))
            conn.execute("""INSERT INTO users(id,first_name,agency_id,referrer_id,source,consent_at,registered_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?)""", (h.CAROL, 'Legacy referral', h.OWNER, h.OWNER, 'referral', now, now, now))
            conn.commit()
        db.initialize()
        self.assertIn('introduced_by_id', [column[1] for column in self.rows('PRAGMA table_info(users)')])
        self.assertEqual(self.rows('SELECT introduced_by_id FROM users WHERE id=?', (h.CAROL,)), [(h.OWNER,)])
        self.assertEqual(self.rows('SELECT introduced_by_id FROM users WHERE id=?', (h.OWNER,)), [(None,)])
        # A pending invitation with an inactive assignee must not be displayed.
        self.assertEqual(self.register(h.ALICE, self.owner_invite())[0], 200)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='approve')[0], 200)
        self.assertEqual(self.as_user('/api/admin/assign', h.OWNER, user_id=h.ALICE, role='staff')[0], 200)
        code = self.owner_invite(assignee_id=h.ALICE)
        self.assertEqual(self.webhook_start(996001, h.BOB, code)[0], 200)
        before_events = self.rows('SELECT count(*) FROM audit')[0][0]
        before_outbox = self.rows('SELECT count(*) FROM notifications_outbox')[0][0]
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='block', reason=' ')[0], 400)
        self.assertEqual(self.as_user('/api/session', h.ALICE)[1]['status'], 'active')
        self.assertEqual(self.rows('SELECT count(*) FROM audit')[0][0], before_events)
        self.assertEqual(self.rows('SELECT count(*) FROM notifications_outbox')[0][0], before_outbox)
        self.assertEqual(self.as_user('/api/admin/decision', h.OWNER, user_id=h.ALICE, decision='block', reason='Assignee disabled')[0], 200)
        status, session = self.as_user('/api/session', h.BOB)
        self.assertEqual(status, 200, session)
        self.assertIsNone(session.get('pending_source_info'))
        self.assertIsNone(session.get('source_info'))
