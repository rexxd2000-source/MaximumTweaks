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
import html
import json
import logging
import os
import secrets
import threading
import time
import hmac
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
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

_DB = LicenseDB()
_OK = {"status": "ok", "service": "maximumtweaks-licenses"}

app = FastAPI(title="Maximum Tweaks License Server", version="1.2.0")

# ---------------------------------------------------------------------------
# Web admin panel (React SPA)
#
# The license manager UI is a single-page app built from ../rex-tweaks-ui
# (``npm run build``) and copied into ./web. It talks to the /admin/* JSON
# endpoints below using the same HttpOnly ``adm`` cookie the token/Discord
# logins issue, so credentials never live in the browser.
# ---------------------------------------------------------------------------

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_WEB_DIR = os.path.join(_BASE_DIR, "web")
_WEB_INDEX = os.path.join(_WEB_DIR, "index.html")
_ASSETS_DIR = os.path.join(_WEB_DIR, "assets")

if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="webassets")


@app.get("/", include_in_schema=False)
def web_root():
    if os.path.isfile(_WEB_INDEX):
        return FileResponse(_WEB_INDEX)
    return JSONResponse({"status": "ok", "service": "maximumtweaks-licenses",
                         "panel": "not_built"})


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


class CheckinRequest(BaseModel):
    key: str
    device_id: str
    pc_name: str = ""


class CreateKeyRequest(BaseModel):
    customer: str = ""
    plan: str = "life"          # "1m" | "6m" | "life"
    max_pcs: int = 1
    note: str = ""


class RemovePcRequest(BaseModel):
    hwid: str


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


# ---------------------------------------------------------------------------
# Discord OAuth admin login
#
# Admins sign in with their Discord account instead of typing the shared
# ADMIN_TOKEN. The desktop app opens a browser to Discord's authorize page;
# the callback (hosted here) exchanges the code, looks the user up, and checks
# the Discord user ID against DISCORD_ADMIN_IDS. The desktop then polls the
# /admin/discord/poll endpoint, which hands it the same HttpOnly ``adm``
# session cookie the token login uses — so ADMIN_TOKEN never leaves the server.
#
# env:
#   DISCORD_CLIENT_ID      Discord application client id
#   DISCORD_CLIENT_SECRET  Discord application client secret (server-only)
#   DISCORD_ADMIN_IDS      comma-separated Discord user IDs allowed to sign in
#   DISCORD_ADMIN_NAMES    optional "id:Display Name" pairs for nicer labels
#   DISCORD_REDIRECT       optional override; defaults to
#                          <request base>/admin/discord/callback
#
# Register `https://<your-domain>/admin/discord/callback` as an OAuth2
# redirect URI in the Discord Developer Portal.
# ---------------------------------------------------------------------------

_DISCORD_API = "https://discord.com/api"
_DISCORD_STATE_TTL = 300            # seconds a sign-in request stays valid
_DISCORD_STATES: dict[str, dict] = {}
_DISCORD_LOCK = threading.Lock()
# Discord blocks default urllib / datacenter-IP User-Agents at the token
# endpoint (HTTP 403 code 1010). Masquerade as a browser so the exchange on
# Render's egress IPs is not mistaken for a bot.
_DISCORD_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _discord_http_error(e: "urllib.error.HTTPError") -> str:
    try:
        return e.read().decode("utf-8", "replace")[:300]
    except Exception:  # noqa: BLE001
        return str(e)


def _discord_config() -> dict:
    """Read Discord credentials + allowlist live from the environment so tests
    and deployments can set/change them without a restart."""
    return {
        "client_id": os.environ.get("DISCORD_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("DISCORD_CLIENT_SECRET", "").strip(),
        "admin_ids": {x.strip() for x in
                      os.environ.get("DISCORD_ADMIN_IDS", "").split(",")
                      if x.strip()},
    }


def _discord_enabled() -> bool:
    cfg = _discord_config()
    return bool(cfg["client_id"] and cfg["client_secret"] and cfg["admin_ids"])


def _discord_admin_names() -> dict[str, str]:
    """Optional "id:Display Name" mapping used only for friendly labels."""
    names: dict[str, str] = {}
    for part in os.environ.get("DISCORD_ADMIN_NAMES", "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        uid, name = part.split(":", 1)
        names[uid.strip()] = name.strip()
    return names


def _discord_state_new() -> str:
    state = secrets.token_urlsafe(24)
    with _DISCORD_LOCK:
        _DISCORD_STATES[state] = {
            "exp": time.time() + _DISCORD_STATE_TTL,
            "status": "waiting", "name": None,
        }
    return state


def _discord_state_get(state: str) -> dict | None:
    with _DISCORD_LOCK:
        entry = _DISCORD_STATES.get(state)
        if entry is None:
            return None
        if entry["exp"] < time.time():
            _DISCORD_STATES.pop(state, None)
            return None
        return entry


def _discord_state_set(state: str, **kw: object) -> None:
    with _DISCORD_LOCK:
        entry = _DISCORD_STATES.get(state)
        if entry is not None:
            entry.update(kw)


def _discord_exchange(code: str, redirect_uri: str) -> dict:
    """Exchange the OAuth code for an access token (stdlib-only; patched in
    tests so the suite never touches Discord). On failure returns a dict
    carrying a ``__error__`` string so the callback can tell the user exactly
    what Discord returned instead of a generic sorry."""
    cfg = _discord_config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        return {"__error__": "client credentials missing"}
    data = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    req = urllib.request.Request(f"{_DISCORD_API}/oauth2/token", data=data,
                                 method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", _DISCORD_UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = _discord_http_error(e)
        logger.error("discord: token exchange HTTP %s: %s", e.code, detail)
        return {"__error__": f"HTTP {e.code}: {detail[:200]}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("discord: token exchange failed")
        return {"__error__": str(e)[:200]}


def _discord_user(access_token: str) -> dict:
    """Fetch the Discord account behind an access token (patched in tests)."""
    req = urllib.request.Request(f"{_DISCORD_API}/users/@me")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("User-Agent", _DISCORD_UA)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return {}


def _discord_page(title: str, body: str) -> HTMLResponse:
    """Tiny brand-consistent page shown in the browser at the end of login.
    Auto-redirects back to the web admin panel (the SPA at /) so the login
    cookie takes effect without the user touching anything."""
    e_title = html.escape(title)
    e_body = html.escape(body)
    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{e_title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{{margin:0;font-family:'Segoe UI',Arial,sans-serif;background:#061a1d;
     color:#efe8d8;display:flex;align-items:center;justify-content:center;
     min-height:100vh}}
.card{{max-width:440px;padding:40px;text-align:center}}
h1{{font-family:Georgia,serif;font-weight:400;color:#e6cc92;margin:0 0 12px}}
p{{color:#8ea3a0;line-height:1.6}}
.sub{{font-size:12px;color:#8ea3a0;margin-top:24px}}
</style></head><body><div class="card">
<h1>{e_title}</h1><p>{e_body}<br><span class="sub">
\u2192 taking you back to the admin panel\u2026</span></p>
</div><script>setTimeout(function(){{location.href='/'}},1400);</script>
</body></html>""")


@app.post("/admin/discord/start")
def discord_start(request: Request):
    """Begin a Discord sign-in: returns the Discord authorize URL + state the
    desktop app opens in the browser and then polls."""
    if not _discord_enabled():
        raise _err("discord_disabled",
                   "Discord login is not configured on the server.", 403)
    state = _discord_state_new()
    cfg = _discord_config()
    redirect_uri = (os.environ.get("DISCORD_REDIRECT", "").strip()
                    or str(request.base_url).rstrip("/")
                    + "/admin/discord/callback")
    params = urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify",
        "state": state,
    })
    return {"ok": True,
            "url": "https://discord.com/oauth2/authorize?" + params,
            "state": state}


@app.get("/admin/discord/callback")
def discord_callback(request: Request, code: str = "", state: str = ""):
    """Discord redirects the browser here after the user authorizes. Validates
    the account against the allowlist and flips the poll status to ok."""
    entry = _discord_state_get(state)
    if entry is None:
        return _discord_page(
            "Sign-in link expired",
            "This sign-in link is no longer valid. Close this window, go "
            "back to the admin app and try again.")
    if not code:
        _discord_state_set(state, status="denied")
        return _discord_page(
            "Sign-in cancelled",
            "Discord sign-in was cancelled. Close this window and go "
            "back to the admin app.")
    redirect_uri = (os.environ.get("DISCORD_REDIRECT", "").strip()
                    or str(request.base_url).rstrip("/")
                    + "/admin/discord/callback")
    token_body = _discord_exchange(code, redirect_uri)
    access_token = token_body.get("access_token")
    if not access_token:
        _discord_state_set(state, status="denied")
        detail = token_body.get("__error__", "")
        body = ("Discord could not complete the sign-in. Close this window "
                "and try again.")
        if detail:
            body += "\nServer detail: " + detail
        return _discord_page("Discord sign-in failed", body)
    user = _discord_user(access_token)
    uid = str(user.get("id") or "")
    username = user.get("username") or uid or "Unknown"
    cfg = _discord_config()
    if uid not in cfg["admin_ids"]:
        _discord_state_set(state, status="denied")
        logger.warning("discord: non-admin login attempt uid=%s user=%s",
                       uid, username)
        return _discord_page(
            "Access denied",
            f"Hi {username} \u2014 this Discord account is not one of the "
            "allowed admins. Close this window.")
    _discord_state_set(state, status="ok", name=username)
    logger.info("discord: admin login uid=%s user=%s", uid, username)
    names = _discord_admin_names()
    pretty = names.get(uid, username)
    response = _discord_page(
        "You\u2019re signed in",
        f"Welcome, {pretty}. You can close this window and go back to the "
        "admin app.")
    # The browser/wrapper flow gets its session here (the callback auto-
    # redirects back to / after 1400ms); the desktop app still polls
    # /admin/discord/poll/{state} for its own copy of the cookie.
    secure = request.url.scheme == "https"
    response.set_cookie(
        ADMIN_COOKIE, _sign_admin_cookie(),
        max_age=ADMIN_SESSION_HOURS * 3600, httponly=True, samesite="lax",
        secure=secure, path="/")
    return response


@app.get("/admin/discord/poll/{state}")
def discord_poll(state: str, request: Request):
    """The desktop app polls this while the browser flow runs. On success the
    response carries the HttpOnly ``adm`` cookie so the desktop client is
    authorized for every /admin/* call without ever holding ADMIN_TOKEN."""
    entry = _discord_state_get(state)
    if entry is None:
        return {"ok": True, "status": "expired"}
    if entry["status"] == "ok":
        secure = request.url.scheme == "https"
        response = JSONResponse({"ok": True, "status": "ok",
                                 "user": entry.get("name") or ""})
        response.set_cookie(
            ADMIN_COOKIE, _sign_admin_cookie(),
            max_age=ADMIN_SESSION_HOURS * 3600, httponly=True, samesite="lax",
            secure=secure, path="/")
        return response
    if entry["status"] == "denied":
        return {"ok": True, "status": "denied"}
    return {"ok": True, "status": "waiting"}


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


def _add_days_utc(days: int) -> str:
    """N days from now, UTC, ``YYYY-MM-DD HH:MM:SS``."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S")


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


def _plan_expiry(plan: str) -> str | None:
    """Resolve a mockup-style plan to an expiry timestamp (1m = 30 days,
    6m = 180 days, life = never)."""
    if plan == "1m":
        return _add_days_utc(30)
    if plan == "6m":
        return _add_days_utc(180)
    return None


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


#: Heartbeat cadence told to the client (seconds). The desktop app repeats
#: check-ins on this interval whenever it is running.
CHECKIN_INTERVAL_S = 300


@app.post("/api/license/checkin")
def checkin(payload: CheckinRequest):
    """Heartbeat from a previously-activated device. Records per-PC/day
    activity and enforces the key's PC limit:
    * existing PCs keep working (their slot stays warm for 30 days), and
    * a NEW PC beyond ``max_pcs`` is refused (and logged) instead of kicking
      an existing PC out, so over-limit attempts surface in the admin panel as
      "X blocked attempts this week" rather than silently displacing a user.
    """
    key = normalize_key(payload.key)
    if not key:
        raise _err("invalid_license", "Invalid license key format.")
    device_id = (payload.device_id or "").strip()
    if len(device_id) < 16:
        raise _err("invalid_device", "Device fingerprint is missing or invalid.")
    pc_name = (payload.pc_name or "").strip()[:80]

    result = _DB.checkin(key, device_id, pc_name)
    if result["status"] != "allowed":
        raise _err(result["error"], result["message"], 403)
    rec = _DB.get(key)
    return {
        "success": True, "valid": True, "message": "OK",
        "interval_s": CHECKIN_INTERVAL_S,
        "license": _license_payload(rec) if rec else None,
    }


# ---------------------------------------------------------------------------
# Admin API (server-side auth: Bearer ADMIN_TOKEN or adm cookie)
#
# The web admin panel (SPA at /) authenticates by exchanging the ADMIN_TOKEN
# or a Discord login for the HttpOnly ``adm`` cookie, then calls these JSON
# endpoints with the browser's own cookie.
# ---------------------------------------------------------------------------

@app.get("/admin")
def admin_root():
    """Root admin probe: confirms the API is up and reports the prefix. The
    admin UI is the web panel (SPA served at /) which talks to the endpoints
    below."""
    body = {"ok": True, "admin": True, "configured_prefix": KEY_PREFIX,
            "panel": "web"}
    if _discord_enabled():
        cfg = _discord_config()
        names = _discord_admin_names()
        body["auth"] = "discord"
        body["admins"] = [names.get(uid, uid)
                          for uid in sorted(cfg["admin_ids"])]
    else:
        body["auth"] = "token"
    return body


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


VALID_PLANS = {"1m", "6m", "life"}


@app.post("/admin/keys")
def admin_create_key(payload: CreateKeyRequest,
                     _: None = Depends(_admin_guard)):
    """Create one license key with the mockup-style plans (1m = 30 days,
    6m = 180 days, life = never) and a PC limit."""
    plan = (payload.plan or "life").strip().lower()
    if plan not in VALID_PLANS:
        raise _err("invalid_plan",
                   "Plan must be one of: 1m, 6m, life.", 400)
    max_pcs = int(payload.max_pcs or 1)
    if not 1 <= max_pcs <= 10:
        raise _err("invalid_max_pcs", "max_pcs must be between 1 and 10.", 400)
    expires_at = _plan_expiry(plan)
    rec = _DB.create(generate_key(KEY_PREFIX), plan=plan,
                     customer=(payload.customer or "").strip(),
                     note=(payload.note or "").strip(),
                     expires_at=expires_at, max_pcs=max_pcs)
    return {"ok": True, "key": rec["license_key"], "plan": plan,
            "expires_at": expires_at, "max_pcs": max_pcs}


@app.get("/admin/keys")
def admin_keys(_: None = Depends(_admin_guard)):
    """Full admin overview: every key plus per-key activity aggregates and
    the dashboard stat counters, fetched in a handful of table-wide queries."""
    data = _DB.overview()
    now_ts = _now_ts()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    keys = []
    active_keys = 0
    online_now = 0
    active_today = 0
    expiring_7d = 0
    for k in data["keys"]:
        status = k["status"]
        # Normalize to the mockup's 3 UI states: an unused (never activated)
        # key is still "active" until it expires or is revoked.
        if status == "unused":
            status = "active"
        elif status != "revoked" and _iso_to_ts(k.get("expires_at") or "") \
                and _iso_to_ts(k["expires_at"]) <= now_ts:
            status = "expired"
        # PC-level aggregates (mockup semantics: "PCs online now" and "PCs
        # active today" count distinct PCs, not keys).
        key_online = []
        key_today = []
        for p in k.get("pcs", []):
            last = _iso_to_ts(p.get("last_seen") or "")
            if last > now_ts - 300:
                key_online.append(p)
            if (p.get("last_seen") or "")[:10] == today:
                key_today.append(p)
        online_now += len(key_online)
        active_today += len(key_today)
        if status != "revoked" and status != "expired":
            active_keys += 1
            exp = _iso_to_ts(k.get("expires_at") or "")
            if exp and now_ts < exp <= now_ts + 7 * 86400:
                expiring_7d += 1
        keys.append({
            "key": k["license_key"],
            "customer": k.get("customer", ""),
            "note": k.get("note", ""),
            "plan": k.get("plan", "lifetime"),
            "status": status,
            "created_at": k.get("created_at"),
            "activated_at": k.get("activated_at"),
            "expires_at": k.get("expires_at"),
            "revoked_at": k.get("revoked_at"),
            "last_seen": k.get("last_seen"),
            "max_pcs": int(k.get("max_pcs") or 1),
            "used_pcs": len(k.get("pcs", [])),
            "pcs": k.get("pcs", []),
            "day_counts": k.get("day_counts", {}),
            "blocked_week": k.get("blocked_week", 0),
        })

    return {
        "ok": True,
        "keys": keys,
        "stats": {
            "total": len(keys),
            "active_keys": active_keys,
            "online_now": online_now,
            "active_today": active_today,
            "expiring_7d": expiring_7d,
        },
    }


@app.get("/admin/keys/{key}/activity")
def admin_key_activity(key: str, _: None = Depends(_admin_guard)):
    """Per-PC 30-day check-in grid for a single key plus recent refusals."""
    rec = _DB.get(key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    data = _DB.activity(key, days=30)
    return {"ok": True, "key": key, **data}


@app.delete("/admin/keys/{key}/pcs/{hwid}")
def admin_remove_pc(key: str, hwid: str, _: None = Depends(_admin_guard)):
    """Free a slot by removing one PC's activity from a key immediately."""
    rec = _DB.get(key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    removed = _DB.remove_pc(key, hwid)
    return {"ok": True, "removed": removed}
