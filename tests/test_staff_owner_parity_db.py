"""Global manager operational parity, with owner and self-mutation guards."""
import time
import unittest

from server import db
from tests import test_registration as registration

OWNER = registration.OWNER


class StaffOwnerParityDBTests(unittest.TestCase):
    as_user = registration.HttpHarness.as_user
    post = registration.HttpHarness.post
    stop_server = registration.HttpHarness.stop_server

    def setUp(self):
        registration.HttpHarness.setUp(self)
        db.initialize()
        now = int(time.time())
        self.staff, self.admin, self.other_staff = 995101, 995102, 995103
        self.lead_a, self.lead_b = 995201, 995202
        with db.transaction() as conn:
            db.ensure_owner(conn, OWNER)
            for uid, role, agency, manager in (
                (self.staff, "staff", self.staff, None),
                (self.admin, "admin", self.staff, None),
                (self.other_staff, "staff", self.other_staff, None),
                (self.lead_a, "lead", self.staff, None),
                (self.lead_b, "lead", self.other_staff, None),
            ):
                conn.execute(
                    "INSERT INTO users(id,internal_id,first_name,username,role,status,"
                    "agency_id,manager_id,registered_at,updated_at) "
                    "VALUES(?,?,?,? ,?,'active',?,?,?,?)",
                    (uid, db.allocate_internal_id(conn), f"User{uid}", f"member{uid}",
                     role, agency, manager, now, now),
                )
            conn.execute("UPDATE users SET manager_id=? WHERE id=?",
                         (self.other_staff, self.lead_a))
            db.audit(conn, self.other_staff, "test_cross_team", self.lead_b, "cross-team")

    def test_staff_and_admin_see_all_leads_and_events(self):
        for actor in (OWNER, self.staff, self.admin):
            with self.subTest(actor=actor):
                status, dashboard = self.as_user("/api/admin/dashboard", actor)
                self.assertEqual(status, 200, dashboard)
                self.assertTrue({self.lead_a, self.lead_b}.issubset(
                    {user["id"] for user in dashboard["users"]}))
                status, page = self.as_user("/api/admin/users", actor, role="lead")
                self.assertEqual(status, 200, page)
                self.assertTrue({self.lead_a, self.lead_b}.issubset(
                    {user["id"] for user in page["users"]}))
                self.assertIn("member995202", {u["username"] for u in page["users"]})
                status, audit = self.as_user("/api/admin/audit", actor)
                self.assertEqual(status, 200, audit)
                self.assertIn("test_cross_team", {row["action"] for row in audit["events"]})
                status, detail = self.as_user("/api/admin/participant", actor, user_id=self.lead_b)
                self.assertEqual(status, 200, detail)
                self.assertEqual(detail["user"]["id"], self.lead_b)
                self.assertIn("finance", detail)
                self.assertIn("statistics", detail)
                status, owner_profile = self.as_user("/api/admin/participant", actor, user_id=OWNER)
                self.assertEqual(status, 200, owner_profile)
                self.assertEqual(owner_profile["user"]["role"], "owner")

    def test_staff_operates_other_team_leads_and_can_unblock(self):
        status, result = self.as_user("/api/admin/decision", self.staff,
                                      user_id=self.lead_b, decision="block", reason="review")
        self.assertEqual(status, 200, result)
        status, result = self.as_user("/api/admin/decision", self.staff,
                                      user_id=self.lead_b, decision="approve")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["user"]["status"], "active")
        status, result = self.as_user("/api/admin/assign", self.staff,
                                      user_id=self.lead_b, manager_id=self.staff)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["user"]["manager_id"], self.staff)
        status, result = self.as_user("/api/admin/assign", self.staff,
                                      user_id=self.lead_a, role="referrer")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["role"], "referrer")

    def test_self_and_owner_mutations_are_denied(self):
        for actor in (self.staff, self.admin):
            for target in (actor, OWNER):
                with self.subTest(actor=actor, target=target):
                    self.assertEqual(
                        self.as_user("/api/admin/assign", actor,
                                     user_id=target, role="owner")[0], 403)
                    self.assertEqual(
                        self.as_user("/api/admin/decision", actor,
                                     user_id=target, decision="block", reason="x")[0], 403)
        with db.transaction() as conn:
            self.assertEqual(db.get_user(conn, OWNER)["role"], "owner")
            self.assertEqual(db.get_user(conn, self.staff)["role"], "staff")
            self.assertEqual(db.get_user(conn, self.admin)["role"], "admin")
            self.assertEqual(db.get_user(conn, OWNER)["status"], "active")

    def test_staff_can_manage_invitation_across_team(self):
        status, created = self.as_user("/api/admin/invitations", self.staff,
                                       assignee_id=self.other_staff, candidate_label="candidate")
        self.assertEqual(status, 200, created)
        status, revoked = self.as_user("/api/invitations/revoke", self.admin, code=created["code"])
        self.assertEqual(status, 200, revoked)
        self.assertTrue(revoked["changed"])

    def test_all_managers_can_issue_and_revoke_crm_blogger_invites(self):
        blogger = "123e4567-e89b-42d3-a456-426614174000"
        with db.transaction() as conn:
            conn.execute("INSERT INTO crm_bloggers(blogger_uuid,channel,issuer_id,active) "
                         "VALUES(?,?,?,1)", (blogger, "Test Blogger", OWNER))
        for actor in (self.staff, self.admin):
            with self.subTest(actor=actor):
                status, invitation = self.as_user("/api/admin/invitations/blogger", actor,
                                                  blogger_uuid=blogger)
                self.assertEqual(status, 200, invitation)
                self.assertEqual(self.as_user("/api/invitations/revoke", actor,
                                             code=invitation["code"])[0], 200)
        with db.transaction() as conn:
            actions = [row["actor_id"] for row in conn.execute(
                "SELECT actor_id FROM audit WHERE action='invite_blogger'").fetchall()]
            self.assertEqual(set(actions), {self.staff, self.admin})

    def test_nonmanager_cannot_query_admin_operations(self):
        self.assertEqual(self.as_user("/api/admin/users", self.lead_a)[0], 403)
        self.assertEqual(self.as_user("/api/admin/participant", self.lead_a,
                                      user_id=self.lead_b)[0], 403)


if __name__ == "__main__":
    unittest.main()
