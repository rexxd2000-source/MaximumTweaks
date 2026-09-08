"""License key generation, HMAC session tokens and rate limiting.

Server-side only. Keys are generated with ``secrets`` (cryptographically
secure) and only ever leave this backend when the admin CLI prints them. The
desktop app can generate nothing and holds no secrets — it only submits a key
the customer bought/entered.

Token format (stateless, HMAC-SHA256 signed):
    <base64url(payload_json)> . <hex_signature>
    payload = {"lic": key, "dev": device_hash, "iat": epoch, "exp": epoch, "v": 1}
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

# 32-char alphabet with no ambiguous characters (I/L/O/0/1 removed).
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
KEY_PREFIX = "MAX"
_GROUPS = 3
_GROUP_LEN = 4
TOKEN_VERSION = 1

KEY_RE = f"^{KEY_PREFIX}-[A-HJKMNP-Z2-9]{{4}}-[A-HJKMNP-Z2-9]{{4}}-[A-HJKMNP-Z2-9]{{4}}$"


def generate_key() -> str:
    """Return a fresh key like ``MAX-XXXX-XXXX-XXXX`` (60 bits of entropy)."""
    def group():
        return "".join(secrets.choice(ALPHABET) for _ in range(_GROUP_LEN))
    return f"{KEY_PREFIX}-{group()}-{group()}-{group()}"


def normalize_key(raw: str) -> str:
    """Tolerate lowercase / missing dashes / surrounding whitespace."""
    cleaned = "".join(ch for ch in (raw or "").upper() if ch.isalnum())
    if len(cleaned) != len(KEY_PREFIX) + _GROUPS * _GROUP_LEN:  # MAX + 12 chars
        return ""
    return f"{cleaned[:3]}-{cleaned[3:7]}-{cleaned[7:11]}-{cleaned[11:]}"


# ---------------------------------------------------------------------------
# HMAC session tokens
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def sign_token(license_key: str, device_id: str, secret: str,
               ttl_seconds: int) -> str:
    """Issue a short-lived, signed, stateless session token."""
    now = int(time.time())
    payload = {
        "lic": license_key,
        "dev": device_id,
        "iat": now,
        "exp": now + int(ttl_seconds),
        "v": TOKEN_VERSION,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str, secret: str) -> dict | None:
    """Verify signature + expiry; return the payload dict or None."""
    try:
        body, sig = token.split(".")
        expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64url_decode(body))
        if payload.get("v") != TOKEN_VERSION:
            return None
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Fixed-window rate limiter (per key / per IP)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Cheap in-memory fixed-window limiter. Keyed buckets are dropped once
    their window passes, so this never grows unbounded."""

    def __init__(self, limit: int, window_seconds: int):
        self._limit = limit
        self._window = window_seconds
        self._buckets: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Record a hit; return False when the limit is exceeded."""
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._buckets.get(key, []) if now - t < self._window]
            if len(hits) >= self._limit:
                self._buckets[key] = hits
                return False
            hits.append(now)
            self._buckets[key] = hits
            return True

    def retry_after(self) -> int:
        return int(self._window)
