"""Stage 12: versioned consent, fail-closed public release, no real personal data."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import db
from tests.test_registration import HttpHarness, ALICE, OWNER
from tools.check_legal_release import LEGAL_PAGES, validate


VERSION = "partners-legal-v2-2026-11"


class LegalRegistrationTests(unittest.TestCase):
    setUp = HttpHarness.setUp
    stop_server = HttpHarness.stop_server
    post = HttpHarness.post
    as_user = HttpHarness.as_user

    def setUp(self):
        HttpHarness.setUp(self)
        env = patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "true",
                                   "PARTNERS_LEGAL_APPROVED_VERSION": VERSION})
        env.start()
        self.addCleanup(env.stop)

    def test_approved_version_must_match_and_is_recorded(self):
        session = self.as_user('/api/session', ALICE)[1]
        self.assertEqual(session['legal_version'], VERSION)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True)[0], 409)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True,
                                      legal_version="partners-registration-v1-2026-11-draft")[0], 409)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True,
                                      legal_version=VERSION, privacy_accepted=False)[0], 400)
        self.assertEqual(self.as_user('/api/register', ALICE, consent=True,
                                      legal_version=VERSION, terms_accepted=False)[0], 400)
        with db.transaction() as conn:
            self.assertIsNone(db.get_user(conn, ALICE))
        status, result = self.as_user('/api/register', ALICE, consent=True, legal_version=VERSION)
        self.assertEqual(status, 200, result)
        self.assertEqual(self.as_user('/api/session', ALICE)[1]['registration']['consent_version'], VERSION)

    def test_public_mode_without_approval_is_blocked(self):
        with patch.dict(os.environ, {"PARTNERS_LEGAL_APPROVED_VERSION": "",
                                   "PARTNERS_REQUIRE_APPROVED_LEGAL": "true"}):
            self.assertEqual(self.as_user('/api/register', ALICE, consent=True)[0], 503)
        with patch.dict(os.environ, {"PARTNERS_LEGAL_APPROVED_VERSION": VERSION + "-draft"}):
            self.assertEqual(self.as_user('/api/register', ALICE, consent=True)[0], 503)


class LegalReleaseGateTests(unittest.TestCase):
    def test_registration_links_point_to_bundled_documents(self):
        from html.parser import HTMLParser

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.urls = set()

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    self.urls.update(value for key, value in attrs if key == "href")

        root = Path(__file__).resolve().parents[1]
        doc = root / "web" / "index.html"
        links = Links()
        links.feed(doc.read_text(encoding="utf-8"))
        for name in ("privacy", "data-consent", "terms", "referrals"):
            url = "/partners/legal/" + name + ".html"
            self.assertIn(url, links.urls)
            self.assertTrue((root / "web" / "legal" / (name + ".html")).is_file())

    def test_owner_confirmed_documents_pass_document_gate_but_have_open_release_issues(self):
        import json
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(validate(root), VERSION)
        evidence = json.loads((root / "deployment" / "legal-approval.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["confirmation_type"], "owner-confirmed-via-chat")
        self.assertEqual(evidence["registry_verification"], "pending")
        self.assertIs(evidence["release_ready"], False)
        self.assertTrue(evidence["unresolved_required_facts"])

    def test_approval_metadata_alone_cannot_release_draft_documents(self):
        import json
        with tempfile.TemporaryDirectory(prefix="legal-stage12-") as tmp:
            root = Path(tmp)
            (root / "deployment").mkdir()
            (root / "web" / "legal").mkdir(parents=True)
            values = {key: "Reviewed" for key in (
                "operator_name", "operator_contact", "data_location", "retention_policy",
                "minor_policy", "payment_terms", "approved_by")}
            values.update(version=VERSION, approved_on="2026-11-20")
            approval = root / "deployment" / "legal-approval.json"
            approval.write_text(json.dumps(values), encoding="utf-8")
            for name in LEGAL_PAGES:
                (root / "web" / "legal" / (name + ".html")).write_text(
                    "<html><span class='placeholder'>[OPERATOR]</span></html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "draft text"):
                validate(root)
            for name in LEGAL_PAGES:
                (root / "web" / "legal" / (name + ".html")).write_text(
                    "<html><p>Reviewed legal page</p></html>", encoding="utf-8")
            self.assertEqual(validate(root), VERSION)
            values["operator_name"] = "[FILL ME]"
            approval.write_text(json.dumps(values), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "placeholder fields"):
                validate(root)


if __name__ == '__main__':
    unittest.main()
