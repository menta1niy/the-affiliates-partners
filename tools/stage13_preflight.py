"""Read-only local release preflight; never connects to Aeza, CRM or Telegram.

Usage: python -m tools.stage13_preflight [--require-ready]
Default reports technical checks and unresolved external gates without failing
the local development phase. --require-ready fails closed on every blocker.
"""
import argparse
import json
import re
from pathlib import Path

from tools.check_legal_release import LEGAL_PAGES, validate as validate_legal

ROOT = Path(__file__).resolve().parents[1]


def inspect(root=ROOT):
    root = Path(root)
    web = root / "web"
    css = (web / "style.css").read_text(encoding="utf-8")
    user = (web / "index.html").read_text(encoding="utf-8")
    admin = (web / "admin/index.html").read_text(encoding="utf-8")
    script = (web / "app.js").read_text(encoding="utf-8")
    schema = (root / "database/postgres.py").read_text(encoding="utf-8")
    migration = (root / "deployment/mvp-schema.sql").read_text(encoding="utf-8")
    installer = (root / "deployment/install-static-release.sh").read_text(encoding="utf-8")
    builder = (root / "tools/build_static_release.py").read_text(encoding="utf-8")

    checks = {}
    checks["shared_amber_design"] = all(term in css for term in (
        "--accent-amber: #E4A34A", "--color-bg: #080909", "--lead-nav-columns: 4"))
    checks["single_stylesheet"] = all(
        'href="/partners/style.css"' in page and "theme-green.css" not in page
        for page in (user, admin))
    checks["four_participant_tabs"] = all(
        len(re.findall(r'data-view="' + name + '"', user)) == 1
        for name in ("home", "offers", "statistics", "profile"))
    checks["statistics_ledger_separation"] = (
        "/statistics/overview" in script and
        (root / "server/statistics.py").is_file() and
        "finance._balances(conn, actor)" in (root / "server/statistics.py").read_text(encoding="utf-8"))
    checks["all_legal_assets_present"] = all(
        (web / "legal" / (name + ".html")).is_file() for name in LEGAL_PAGES)
    checks["legal_references_resolve"] = all(
        '/partners/legal/' + name + '.html' in user for name in ("privacy", "terms", "referrals", "data-consent"))
    tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", migration, re.I))
    schema_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", schema, re.I))
    checks["mvp_migration_table_coverage"] = bool(tables) and tables.issubset(schema_tables)
    checks["migration_is_partners_only"] = "SET LOCAL search_path TO partners, public" in migration and "GRANT SELECT" in migration
    checks["release_uses_manifest_sha256"] = (
        "sha256sum" in installer and "File checksum mismatch" in installer and
        '"legal_version"' in builder and '"legal_version"' in installer)
    checks["release_rejects_draft"] = (
        "Draft legal document in public archive" in installer and
        "validate_legal_release(ROOT)" in builder)

    blockers = []
    try:
        legal = validate_legal(root)
    except (ValueError, OSError, json.JSONDecodeError):
        legal = None
        blockers.append("Legal operator, retention, age policy and final signed texts are not approved")
    # These checks require explicit future access to the real environment.
    blockers.extend((
        "Disposable PostgreSQL restore, migrations and privilege acceptance not run against release runtime",
        "Real Telegram iOS/Android WebView and notification acceptance not yet performed",
        "Owner has not authorized production release or GitHub push",
    ))
    return {"technical_checks": checks, "technical_pass": all(checks.values()),
            "approved_legal_version": legal, "release_ready": all(checks.values()) and not blockers,
            "release_blockers": blockers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    report = inspect()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["technical_pass"] or (args.require_ready and not report["release_ready"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
