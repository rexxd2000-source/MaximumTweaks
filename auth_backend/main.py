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

import calendar
import hashlib
import json
import logging
import os
import time
import hmac
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass  # env vars may be supplied directly by the shell instead

from db import LicenseDB
from keys import (
    KEY_PREFIX,
    _b64url_decode,
    _b64url_encode,
    generate_key,
    normalize_key,
    sign_token,
    verify_token,
    RateLimiter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("maxtweaks.license")

# ---------------------------------------------------------------------------
# Configuration (environment only — never hard-code secrets)
# ---------------------------------------------------------------------------

LICENSE_SECRET = os.environ.get("LICENSE_SECRET", "").strip()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "").strip()
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "720"))
OFFLINE_GRACE_HOURS = int(os.environ.get("OFFLINE_GRACE_HOURS", "24"))

ADMIN_SESSION_HOURS = int(os.environ.get("ADMIN_SESSION_HOURS", "12"))
ADMIN_COOKIE = "adm"

ACTIVATE_PER_KEY = int(os.environ.get("ACTIVATE_PER_KEY", "10"))
ACTIVATE_PER_IP = int(os.environ.get("ACTIVATE_PER_IP", "40"))

PANEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "admin_panel.html")

_DB = LicenseDB()
_OK = {"status": "ok", "service": "maximumtweaks-licenses"}

app = FastAPI(title="Maximum Tweaks License Server", version="1.1.0")


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
    duration: str = ""              # "1m" | "6m" | "lifetime" (server computes expires_at)
    prefix: str = ""                # e.g. "MAX" / "REX" / "MTW" — defaults to LICENCE_KEY_PREFIX
    customer: str = ""
    note: str = ""
    expires_at: str | None = None   # "YYYY-MM-DD HH:MM:SS" (UTC) or None = lifetime


class RevokeRequest(BaseModel):
    key: str
    reason: str = ""


class KeyRequest(BaseModel):
    key: str


class LoginRequest(BaseModel):
    token: str


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


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort server-side safety net.

    The real traceback is logged here so the operator can find the underlying
    cause; the client only ever sees a generic, friendly message — never raw
    stack traces or ``Internal Server Error`` details.
    """
    logger.error("unhandled %s on %s %s",
                 type(exc).__name__, request.method, request.url.path,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={
        "success": False, "valid": False, "error": "server_error",
        "message": "The server hit an unexpected error. Please try again later."})


# ---------------------------------------------------------------------------
# Admin panel session cookies (server-side auth, HttpOnly)
# ---------------------------------------------------------------------------

def _sign_admin_cookie() -> str:
    """Issue a short-lived, HMAC-signed admin session cookie value."""
    now = int(time.time())
    payload = {"a": 1, "exp": now + ADMIN_SESSION_HOURS * 3600}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(LICENSE_SECRET.encode("utf-8"), body.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _admin_cookie_valid(value: str | None) -> bool:
    if not value or not LICENSE_SECRET:
        return False
    try:
        body, sig = value.split(".")
        expected = hmac.new(LICENSE_SECRET.encode("utf-8"),
                            body.encode("ascii"),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(_b64url_decode(body))
        return payload.get("a") == 1 and \
            int(payload.get("exp", 0)) > int(time.time())
    except Exception:  # noqa: BLE001
        return False


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


def _require_admin(authorization: str | None, cookie: str | None = None):
    if not ADMIN_TOKEN:
        raise _err("admin_disabled", "Admin access is not configured.", 403)
    if _admin_cookie_valid(cookie):
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _err("unauthorized", "Admin bearer token required.", 401)
    token = authorization[7:].strip()
    if not hmac.compare_digest(token, ADMIN_TOKEN):
        raise _err("unauthorized", "Invalid admin token.", 401)


def _admin_guard(request: Request,
                 authorization: str | None = Header(None)):
    """Dependency: enforce server-side admin auth on every /admin/* route.

    Accepts either the HttpOnly ``adm`` session cookie (admin panel login) or
    ``Authorization: Bearer <ADMIN_TOKEN>`` (scripts/tools). A frontend flag
    can never grant admin access — this check runs on the server for every
    request and a wrong/absent credential is a hard 401.
    """
    _require_admin(authorization, request.cookies.get(ADMIN_COOKIE))


def _add_months_utc(months: int) -> str:
    """Calendar-accurate N-months-from-now, UTC, ``YYYY-MM-DD HH:MM:SS``."""
    now = datetime.now(timezone.utc)
    month_index = now.month - 1 + months
    year = now.year + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, now.hour, now.minute, now.second,
                    tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_duration(plan: str, duration: str,
                      expires_at: str | None):
    """Server-side duration application: returns (plan, expires_at).

    An explicit ``expires_at`` always wins; otherwise the ``duration`` field
    (1m / 6m / lifetime) is turned into a real expiration timestamp. The key
    itself never encodes the duration — it lives in the license record.
    """
    if expires_at:
        return plan, expires_at
    if duration == "1m":
        return "monthly", _add_months_utc(1)
    if duration == "6m":
        return "custom", _add_months_utc(6)
    if duration == "lifetime":
        return "lifetime", None
    if duration:
        raise _err("invalid_duration",
                   "Duration must be one of: 1m, 6m, lifetime.", 400)
    return plan, expires_at


def _valid_prefix(prefix: str) -> str:
    """Validate a per-generation key prefix: 1-4 uppercase alphanumerics."""
    prefix = (prefix or "").strip().upper()
    if not prefix:
        return KEY_PREFIX
    if len(prefix) > 4 or not prefix.isalnum():
        raise _err("invalid_prefix",
                   "Prefix must be 1-4 letters/digits (e.g. MAX, REX, MTW).",
                   400)
    return prefix


def _unique_keys(db: LicenseDB, count: int, prefix: str, **kwargs) -> list[str]:
    """Generate ``count`` unique, unpredictable keys and store them.

    Every key is created server-side; a UNIQUE collision (astronomically rare
    with 60 bits of entropy) transparently re-rolls instead of failing.
    """
    keys: list[str] = []
    seen: set[str] = set()
    attempts = 0
    while len(keys) < count and attempts < count * 20:
        attempts += 1
        key = generate_key(prefix)
        if key in seen:
            continue
        seen.add(key)
        try:
            db.create(key, **kwargs)
        except Exception:  # noqa: BLE001
            if db.get(key) is not None:  # true UNIQUE collision → re-roll
                continue
            raise
        keys.append(key)
    return keys


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
                   "XXXX-XXXX-XXXX-XXXX).")
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
# Admin UI + Admin API (server-side auth: Bearer ADMIN_TOKEN or adm cookie)
# ---------------------------------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    """Serve the admin panel. It is NOT a security boundary — every /admin/*
    API route behind it is independently authenticated server-side."""
    if not os.path.exists(PANEL_FILE):  # pragma: no cover
        return HTMLResponse(
            "<h1>Maximum Tweaks Admin Panel</h1><p>admin_panel.html missing.</p>")
    return FileResponse(PANEL_FILE)


@app.get("/admin/me")
def admin_me(request: Request,
             authorization: str | None = Header(None)):
    """Login state probe for the panel (cookie OR bearer)."""
    if ADMIN_TOKEN and (_admin_cookie_valid(request.cookies.get(ADMIN_COOKIE))
                        or (authorization or "").lower().startswith("bearer ")
                        and hmac.compare_digest(
                            authorization[7:].strip(), ADMIN_TOKEN)):
        return {"ok": True, "logged_in": True,
                "admin": True, "configured_prefix": KEY_PREFIX}
    return JSONResponse(status_code=401, content={
        "ok": True, "logged_in": False, "admin": False,
        "configured_prefix": KEY_PREFIX})


@app.post("/admin/login")
def admin_login(payload: LoginRequest, request: Request):
    """Exchange the admin token for an HttpOnly session cookie.

    This is the only way to get a browser session; the raw ADMIN_TOKEN is
    verified server-side and never kept in the browser beyond the cookie.
    """
    if not ADMIN_TOKEN:
        raise _err("admin_disabled", "Admin access is not configured.", 403)
    supplied = (payload.token or "").strip()
    if not supplied or not hmac.compare_digest(supplied, ADMIN_TOKEN):
        raise _err("unauthorized", "Invalid admin token.", 401)
    response = JSONResponse({"ok": True, "message": "Logged in"})
    secure = request.url.scheme == "https"
    response.set_cookie(
        ADMIN_COOKIE, _sign_admin_cookie(),
        max_age=ADMIN_SESSION_HOURS * 3600, httponly=True, samesite="lax",
        secure=secure, path="/")
    return response


@app.post("/admin/logout")
def admin_logout():
    response = JSONResponse({"ok": True, "message": "Logged out"})
    response.delete_cookie(ADMIN_COOKIE, path="/")
    return response


@app.get("/admin/licenses")
def admin_list(status: str | None = None,
               _: None = Depends(_admin_guard)):
    return {"ok": True, "licenses": _DB.list_all(status)}


@app.get("/admin/stats")
def admin_stats(_: None = Depends(_admin_guard)):
    return {"ok": True, "stats": _DB.stats()}


@app.get("/admin/search")
def admin_search(q: str = "", _: None = Depends(_admin_guard)):
    """Search licenses by key / customer / note (substring, case-insensitive)."""
    query = (q or "").strip()
    if len(query) < 3:
        raise _err("invalid_query", "Search query must be at least 3 chars.",
                   400)
    return {"ok": True, "licenses": _DB.search(query)}


@app.post("/admin/generate")
def admin_generate(payload: GenerateRequest, _: None = Depends(_admin_guard)):
    """Generate 1..500 unique license keys, stored server-side.

    Duration is resolved server-side from ``duration`` (1m/6m/lifetime) or an
    explicit ``expires_at``; the key string never leaks the duration.
    """
    count = max(1, min(int(payload.count), 500))
    prefix = _valid_prefix(payload.prefix)
    plan, expires_at = _resolve_duration(
        payload.plan, (payload.duration or "").strip().lower(),
        payload.expires_at)
    keys = _unique_keys(
        _DB, count, prefix, plan=plan, customer=payload.customer,
        note=payload.note, expires_at=expires_at)
    return {"ok": True, "keys": keys, "count": len(keys),
            "plan": plan, "expires_at": expires_at}


@app.post("/admin/revoke")
def admin_revoke(payload: RevokeRequest, _: None = Depends(_admin_guard)):
    rec = _DB.revoke(payload.key, payload.reason)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.post("/admin/unrevoke")
def admin_unrevoke(payload: KeyRequest, _: None = Depends(_admin_guard)):
    rec = _DB.unrevoke(payload.key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.post("/admin/unbind")
def admin_unbind(payload: KeyRequest, _: None = Depends(_admin_guard)):
    """Support-only PC-change action: frees the key for a new device."""
    rec = _DB.unbind(payload.key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.delete("/admin/keys/{key}")
def admin_delete(key: str, _: None = Depends(_admin_guard)):
    """Permanently delete a license row. Admin-ops only (removes test keys,
    stale rows, etc.). Not recoverable."""
    rec = _DB.get(key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    deleted = _DB.delete(key)
    return {"ok": True, "deleted": deleted}
