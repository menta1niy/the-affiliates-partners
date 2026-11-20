"""Fail-closed legal/document readiness gate for public static releases.

An approval record is operational evidence only, never a substitute for legal
review. This gate prevents accidental publication of the bundled draft pages.
"""
import json
import re
from pathlib import Path


LEGAL_PAGES = ("privacy", "data-consent", "terms", "referrals", "bloggers")
REQUIRED_FIELDS = ("version", "operator_name", "operator_contact", "data_location",
                   "retention_policy", "minor_policy", "payment_terms", "approved_by", "approved_on")


def validate(root):
    root = Path(root)
    approval = root / "deployment" / "legal-approval.json"
    if not approval.is_file():
        raise ValueError("Legal approval missing: publication of draft documents is forbidden")
    info = json.loads(approval.read_text(encoding="utf-8"))
    if not isinstance(info, dict):
        raise ValueError("Legal approval must be an object")
    if any(not isinstance(info.get(key), str) or not info[key].strip()
           or info[key].strip().startswith("[") for key in REQUIRED_FIELDS):
        raise ValueError("Legal approval has missing or placeholder fields")
    version = info["version"].strip()
    if not re.fullmatch(r"partners-legal-v[0-9]+-[0-9]{4}-[0-9]{2}", version):
        raise ValueError("Legal version must be an approved, non-draft revision")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", info["approved_on"]):
        raise ValueError("Legal approval date must be YYYY-MM-DD")
    for name in LEGAL_PAGES:
        page = root / "web" / "legal" / (name + ".html")
        if not page.is_file():
            raise ValueError("Missing legal page: " + name)
        contents = page.read_text(encoding="utf-8")
        if ("ПРОЕКТ" in contents or "НЕ УТВЕРЖДЕНО" in contents
                or "placeholder" in contents or "[" in contents and "</span>" in contents
                or "partners-registration-v1-2026-11-draft" in contents):
            raise ValueError("Legal page still contains draft text: " + name)
    return version


if __name__ == "__main__":
    print("Approved legal version:", validate(Path(__file__).resolve().parents[1]))
