"""Authenticated, bounded CRM event transport shared by API and dispatch jobs.

The secret is a dedicated integration credential, never the Telegram bot token.
Both services sign exactly the transmitted UTF-8 body, preventing JSON
normalization differences from changing the authenticated message.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request


MAX_BODY = 256 * 1024
MAX_SKEW = 300


class BridgeError(Exception):
    pass


def secret():
    return os.environ.get("PARTNERS_CRM_SHARED_SECRET", "")


def signature(payload, timestamp, key):
    if not isinstance(payload, bytes) or not isinstance(timestamp, int) or not isinstance(key, str) or len(key) < 32:
        raise BridgeError("CRM integration is not configured")
    message = str(timestamp).encode("ascii") + b"\n" + payload
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify(payload, timestamp_header, signature_header, key=None, now=None, event_id_header=None):
    """Verify raw body HMAC and short freshness window before JSON decoding."""
    key = secret() if key is None else key
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BODY:
        raise BridgeError("Invalid CRM payload size")
    if not isinstance(timestamp_header, str) or not timestamp_header.isascii() or not timestamp_header.isdecimal() or len(timestamp_header) > 12:
        raise BridgeError("Invalid CRM timestamp")
    timestamp = int(timestamp_header)
    if abs((int(time.time()) if now is None else now) - timestamp) > MAX_SKEW:
        raise BridgeError("Expired CRM request")
    if not isinstance(signature_header, str) or len(signature_header) != 64 or not all(c in "0123456789abcdef" for c in signature_header):
        raise BridgeError("Invalid CRM signature")
    if not hmac.compare_digest(signature(payload, timestamp, key), signature_header):
        raise BridgeError("Invalid CRM signature")
    try:
        event = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("Invalid CRM JSON") from exc
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not 1 <= len(event["event_id"]) <= 128:
        raise BridgeError("Missing CRM event identifier")
    if not isinstance(event.get("type"), str) or not 1 <= len(event["type"]) <= 80:
        raise BridgeError("Missing CRM event type")
    if event_id_header is not None and event_id_header != event["event_id"]:
        raise BridgeError("CRM event identifier mismatch")
    return event


def deliver(url, event, *, key=None, timeout=8):
    """Send one durable event. Caller owns retry/outbox and event_id stability."""
    key = secret() if key is None else key
    if not isinstance(url, str) or not url.startswith("https://"):
        raise BridgeError("CRM endpoint must use HTTPS")
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str):
        raise BridgeError("CRM event_id is required")
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if not 0 < len(payload) <= MAX_BODY:
        raise BridgeError("Invalid CRM payload size")
    timestamp = int(time.time())
    request = urllib.request.Request(url, payload, {
        "Content-Type": "application/json; charset=utf-8",
        "X-TA-Timestamp": str(timestamp),
        "X-TA-Signature": signature(payload, timestamp, key),
        "X-TA-Event-ID": event["event_id"],
    }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = response.read(MAX_BODY + 1)
            if len(result) > MAX_BODY:
                raise BridgeError("CRM response too large")
            if response.status < 200 or response.status >= 300:
                raise BridgeError("CRM delivery rejected")
            return json.loads(result) if result else {}
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BridgeError("CRM delivery failed") from exc
