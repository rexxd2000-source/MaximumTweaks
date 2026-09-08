"""Maximum Tweaks — license authentication backend.

A small standalone FastAPI service that owns license validation for the
MAXIMUM TWEAKS desktop app. The desktop app never holds any secrets; it only
sends a customer-entered license key plus a hashed device fingerprint and
receives a short-lived signed session token back.

Flow
----
1. Customer launches the app and enters their key (``MAX-XXXX-XXXX-XXXX``).
2. The app posts  POST /api/license/activate {key, device_id}.
   The backend binds the key to that device (hardware lock) and returns a
   signed, short-lived session token.
3. On later launches the app calls POST /api/license/validate {token,
   device_id} to refresh the token (revoked/expired keys are caught here).
4. The app caches the token locally for a short offline grace period only —
   this is not a permanent bypass, and the backend remains the authority.

Hardware locking
----------------
- ``device_id`` is a SHA-256 hash of the machine fingerprint computed by the
  client; the raw fingerprint is never sent or stored.
- A key is bound to exactly one device at a time. If a customer changes PC,
  support runs the ``unbind`` admin action — there is deliberately NO
  client-side reset (otherwise copying the app would let anyone re-bind).

Security
--------
- LICENSE_SECRET signs session tokens (HMAC-SHA256). It lives only here.
- ADMIN_TOKEN guards all admin endpoints.
- Rate limiting: activation attempts are limited per IP and per key.
- Unknown/invalid keys return a generic INVALID_KEY (no key enumeration).

Run
---
    pip install -r requirements.txt
    copy .env.example .env        # fill in real values
    uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass  # env vars may be supplied directly by the shell instead

from db import LicenseDB
from keys import generate_key, normalize_key, sign_token, verify_token, RateLimiter

# ---------------------------------------------------------------------------
# Configuration (environment only — never hard-code secrets)
# ---------------------------------------------------------------------------

LICENSE_SECRET = os.environ.get("LICENSE_SECRET", "").strip()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "72"))
OFFLINE_GRACE_HOURS = int(os.environ.get("OFFLINE_GRACE_HOURS", "24"))

ACTIVATE_PER_KEY = int(os.environ.get("ACTIVATE_PER_KEY", "10"))
ACTIVATE_PER_IP = int(os.environ.get("ACTIVATE_PER_IP", "40"))

_DB = LicenseDB()
_OK = {"status": "ok", "service": "maximumtweaks-licenses"}

app = FastAPI(title="Maximum Tweaks License Server", version="1.0.0")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ActivateRequest(BaseModel):
    key: str
    device_id: str


class ValidateRequest(BaseModel):
    token: str
    device_id: str


class DeactivateRequest(BaseModel):
    token: str
    device_id: str


class GenerateRequest(BaseModel):
    count: int = 1
    plan: str = "lifetime"
    customer: str = ""
    note: str = ""
    expires_at: str | None = None  # "YYYY-MM-DD HH:MM:SS" (UTC) or None = lifetime


class RevokeRequest(BaseModel):
    key: str
    reason: str = ""


class KeyRequest(BaseModel):
    key: str


# ---------------------------------------------------------------------------
# Rate limiters
# ---------------------------------------------------------------------------

_limiter_key = RateLimiter(ACTIVATE_PER_KEY, 3600)
_limiter_ip = RateLimiter(ACTIVATE_PER_IP, 3600)


def _err(code: str, message: str, status: int = 403) -> HTTPException:
    """Build an HTTP error whose body is the API error envelope.

    The exception handler below unwraps ``detail`` so the client receives the
    object directly as the top-level JSON body:
    ``{"success": false, "valid": false, "error": ..., "message": ...}``
    """
    return HTTPException(status_code=status, detail={
        "success": False, "valid": False, "error": code, "message": message})


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Return error bodies as a flat JSON object (no FastAPI ``detail``
    wrapper), so every response from this API is a JSON object with the same
    shape the client expects.

    Registered on the Starlette base class so it also covers unmatched-route
    404s (which raise the parent type), not just exceptions raised by our own
    endpoints.
    """
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        content = detail
    else:
        content = {"success": False, "valid": False,
                   "error": "server_error",
                   "message": str(detail) if detail else "Request failed."}
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "success": False, "valid": False,
        "error": "invalid_request", "message": "The request payload was invalid."})


def _now_ts() -> float:
    return time.time()


def _iso_to_ts(value: str) -> float:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc).timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _session_payload(rec: dict) -> dict:
    owner = rec.get("customer") or "Maximum Tweaks License"
    return {
        "license": rec["license_key"],
        "owner": owner,
        "plan": rec.get("plan") or "lifetime",
        "customer": rec.get("customer") or "",
        "activated_at": rec.get("activated_at"),
        "expires_at": rec.get("expires_at"),
        "last_validation": rec.get("last_validated"),
        "device_id": rec.get("device_id"),
    }


def _license_payload(rec: dict) -> dict:
    """License object returned to the desktop client."""
    owner = rec.get("customer") or "Maximum Tweaks License"
    return {
        "key": rec["license_key"],
        "status": rec.get("status") or "active",
        "plan": rec.get("plan") or "lifetime",
        "owner": owner,
        "customer": rec.get("customer") or "",
        "activated_at": rec.get("activated_at"),
        "expires_at": rec.get("expires_at"),
        "last_validation": rec.get("last_validated"),
        "device_id": rec.get("device_id"),
    }


def _success(message: str, rec: dict | None = None, token: str | None = None,
             token_exp: float | None = None) -> dict:
    """Uniform success envelope: ``{"success": true, "valid": true, ...}``."""
    body = {"success": True, "valid": True, "message": message}
    if rec is not None:
        body["license"] = _license_payload(rec)
    if token is not None:
        body["session_token"] = token
        body["token_exp"] = token_exp or _now_ts() + SESSION_TTL_HOURS * 3600
    return body


def _require_admin(authorization: str | None):
    if not ADMIN_TOKEN:
        raise _err("admin_disabled", "Admin access is not configured.", 403)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _err("unauthorized", "Admin bearer token required.", 401)
    token = authorization[7:].strip()
    if token != ADMIN_TOKEN:
        raise _err("unauthorized", "Invalid admin token.", 401)


def _check_expiry(rec: dict) -> dict | None:
    """If the license's expires_at has passed, mark it expired and return None.

    Returns the record unchanged when still valid.
    """
    exp = rec.get("expires_at")
    if exp and _iso_to_ts(exp) <= _now_ts():
        _DB.mark_expired(rec["license_key"])
        rec["status"] = "expired"
    return rec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return _OK


@app.post("/api/license/activate")
def activate(payload: ActivateRequest, request: Request):
    """Bind a license key to a device and issue a short-lived session token."""
    ip = (request.client.host if request.client else "unknown")
    if not _limiter_ip.hit(ip):
        raise _err("rate_limited", "Too many activation attempts. Please wait.",
                   429)
    key = normalize_key(payload.key)
    if not key:
        raise _err("invalid_license",
                   "That doesn't look like a valid license key (expected "
                   "MAX-XXXX-XXXX-XXXX).")
    if not _limiter_key.hit(key):
        raise _err("rate_limited", "Too many attempts for this key. Please wait.",
                   429)
    device_id = (payload.device_id or "").strip()
    if len(device_id) < 16:
        raise _err("invalid_device", "Device fingerprint is missing or invalid.")

    rec = _DB.get(key)
    if rec is None:
        raise _err("invalid_license",
                   "That license key was not recognized. Double-check it and "
                   "try again, or contact support.")
    _check_expiry(rec)

    if rec["status"] == "revoked":
        raise _err("license_revoked",
                   "This license key has been revoked. Contact support for help.")
    if rec["status"] == "expired":
        raise _err("license_expired", "This license key has expired.")

    if rec["status"] == "active":
        if rec["device_id"] != device_id:
            raise _err(
                "device_mismatch",
                "This license is already activated on another PC. If you "
                "changed computers, contact support to unlock it — never copy "
                "the app folder to bypass the hardware lock.")
        # Same device re-activating: refresh the token (idempotent).
    elif rec["status"] == "unused":
        _DB.activate(key, device_id)
    else:  # pragma: no cover
        raise _err("invalid_license", "This license key cannot be activated.")

    rec = _DB.get(key)
    token = sign_token(key, device_id, LICENSE_SECRET, SESSION_TTL_HOURS * 3600)
    return _success("License activated successfully", rec, token,
                    _now_ts() + SESSION_TTL_HOURS * 3600)


@app.post("/api/license/validate")
def validate(payload: ValidateRequest):
    """Verify a session token and refresh it. Catches revoked/expired keys."""
    if not LICENSE_SECRET:
        raise _err("server_error", "License server is not configured.", 500)
    claims = verify_token(payload.token, LICENSE_SECRET)
    if claims is None:
        raise _err("invalid_token", "Your session is no longer valid — "
                                    "please activate again.", 401)
    rec = _DB.get(claims.get("lic", ""))
    if rec is None:
        raise _err("invalid_token", "Your session is no longer valid.", 401)
    _check_expiry(rec)

    if rec["status"] == "revoked":
        raise _err("license_revoked", "This license key has been revoked.", 403)
    if rec["status"] == "expired":
        raise _err("license_expired", "This license key has expired.", 403)
    if rec["device_id"] and rec["device_id"] != payload.device_id:
        raise _err("device_mismatch",
                   "This license is bound to a different PC.", 403)

    _DB.touch_validation(rec["license_key"])
    token = sign_token(rec["license_key"], payload.device_id, LICENSE_SECRET,
                       SESSION_TTL_HOURS * 3600)
    return _success("License validated successfully", rec, token,
                    _now_ts() + SESSION_TTL_HOURS * 3600)


@app.post("/api/license/deactivate")
def deactivate(payload: DeactivateRequest):
    """Acknowledge a client-side deactivation (removes the local session).

    This deliberately does NOT unbind the key — hardware binding is only ever
    released through the admin ``unbind`` action so a stolen copy cannot free
    itself and be re-sold.
    """
    if verify_token(payload.token, LICENSE_SECRET) is None:
        raise _err("invalid_token", "Session is not valid.", 401)
    return _success("License deactivated on this device")


# ---------------------------------------------------------------------------
# Admin API (Bearer ADMIN_TOKEN)
# ---------------------------------------------------------------------------

@app.get("/admin/licenses")
def admin_list(status: str | None = None,
               authorization: str | None = Header(None)):
    _require_admin(authorization)
    return {"ok": True, "licenses": _DB.list_all(status)}


@app.get("/admin/stats")
def admin_stats(authorization: str | None = Header(None)):
    _require_admin(authorization)
    return {"ok": True, "stats": _DB.stats()}


@app.get("/admin/search")
def admin_search(q: str = "", authorization: str | None = Header(None)):
    """Search licenses by key / customer / note (substring, case-insensitive)."""
    _require_admin(authorization)
    query = (q or "").strip()
    if len(query) < 3:
        raise _err("invalid_query", "Search query must be at least 3 chars.",
                   400)
    return {"ok": True, "licenses": _DB.search(query)}


@app.post("/admin/generate")
def admin_generate(payload: GenerateRequest,
                   authorization: str | None = Header(None)):
    _require_admin(authorization)
    count = max(1, min(int(payload.count), 500))
    keys = [generate_key() for _ in range(count)]
    for key in keys:
        _DB.create(key, plan=payload.plan, customer=payload.customer,
                   note=payload.note, expires_at=payload.expires_at)
    return {"ok": True, "keys": keys}


@app.post("/admin/revoke")
def admin_revoke(payload: RevokeRequest,
                 authorization: str | None = Header(None)):
    _require_admin(authorization)
    rec = _DB.revoke(payload.key, payload.reason)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.post("/admin/unrevoke")
def admin_unrevoke(payload: KeyRequest,
                   authorization: str | None = Header(None)):
    _require_admin(authorization)
    rec = _DB.unrevoke(payload.key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.post("/admin/unbind")
def admin_unbind(payload: KeyRequest,
                 authorization: str | None = Header(None)):
    """Support-only PC-change action: frees the key for a new device."""
    _require_admin(authorization)
    rec = _DB.unbind(payload.key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}
