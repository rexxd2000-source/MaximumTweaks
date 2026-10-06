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
import hmac
import html
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
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

from db import TIERS, LicenseDB, normalize_tier
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
from launch_email import send_launch
from mailers import get_mailer

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

ACTIVATE_PER_KEY = int(os.environ.get("ACTIVATE_PER_KEY", "25"))
ACTIVATE_PER_IP = int(os.environ.get("ACTIVATE_PER_IP", "100"))

# Waitlist sign-ups per IP per hour (permissive — it is a brand funnel, not a
# licensing resource).
WAITLIST_JOIN_PER_IP = int(os.environ.get("WAITLIST_JOIN_PER_IP", "20"))

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
        return FileResponse(_WEB_INDEX, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
        })
    return JSONResponse({"status": "ok", "service": "maximumtweaks-licenses",
                         "panel": "not_built"})


# ---------------------------------------------------------------------------
# Update manifest (served on our own domain so clients never depend on the
# rate-limited github.com API. Endpoint /update.json is what the desktop app's
# UPDATE_MANIFEST_URL points at.)
#
# The manifest is a committed, static file (auth_backend/web/update.json) that
# is regenerated when releasing a new version — see release.ps1. We deliberately
# DO NOT proxy the GitHub API here: Render egress to api.github.com is not
# guaranteed and the file approach keeps the endpoint dead-simple and always up.
# ---------------------------------------------------------------------------

_UPDATE_MANIFEST_FILE = os.path.join(_WEB_DIR, "update.json")


@app.get("/update.json", include_in_schema=False)
def update_manifest():
    try:
        with open(_UPDATE_MANIFEST_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        logger.warning("update manifest: missing/unreadable update.json")
        return JSONResponse(
            {"status": "error", "message": "Manifest source temporarily unavailable."},
            status_code=502,
            headers={"Cache-Control": "no-store"},
        )
    ver = str(data.get("version") or "").strip()
    url = str(data.get("url") or "").strip()
    if not ver or not url:
        return JSONResponse(
            {"status": "error", "message": "Manifest is missing version/url."},
            status_code=502,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(data, headers={"Cache-Control": "no-store"})


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
    plan: str = "life"          # "1m" | "6m" | "life"  (billing DURATION)
    tier: str | None = "foundation"    # subscription LEVEL: foundation|performance|maximum
    max_pcs: int = 1
    note: str = ""


class RemovePcRequest(BaseModel):
    hwid: str


class GenerateRequest(BaseModel):
    count: int = 1
    plan: str = "lifetime"
    duration: str = ""              # "1m" | "6m" | "lifetime" (server computes expires_at)
    tier: str | None = "foundation"        # subscription LEVEL: foundation|performance|maximum
    prefix: str = ""                # e.g. "MAX" / "REX" / "MTW" - defaults to LICENCE_KEY_PREFIX
    customer: str = ""
    note: str = ""
    expires_at: str | None = None   # "YYYY-MM-DD HH:MM:SS" (UTC) or None = lifetime


class RevokeRequest(BaseModel):
    key: str
    reason: str = ""


class BanRequest(BaseModel):
    key: str
    reason: str = ""


class SuspendRequest(BaseModel):
    key: str
    hours: int = 12
    reason: str = ""


class KeyRequest(BaseModel):
    key: str


class TierRequest(BaseModel):
    """Set a licence's subscription level.

    The tier is validated and normalized on the server, so a malformed value
    falls back to Foundation instead of granting an unintended level. ``None`` is
    accepted and means "not specified", so a client that has never heard of
    tiers can send ``null`` and get the free tier rather than a 422.
    """
    key: str
    tier: str | None = "foundation"


class LoginRequest(BaseModel):
    token: str


class WaitlistJoinRequest(BaseModel):
    email: str
    source: str = ""


class WaitlistSendRequest(BaseModel):
    """Admin launch-email dispatch. Empty fields fall back to env/defaults."""
    code: str                       # raw ADMIN_TOKEN, reconfirm step
    subject: str = ""
    heading: str = ""
    message: str = ""
    cta_button: str = ""
    cta_url: str = ""
    to_email: str = ""              # target a single waitlist address, optional


# ---------------------------------------------------------------------------
# Rate limiters
# ---------------------------------------------------------------------------

_limiter_key = RateLimiter(ACTIVATE_PER_KEY, 3600)
_limiter_ip = RateLimiter(ACTIVATE_PER_IP, 3600)
_limiter_waitlist_ip = RateLimiter(WAITLIST_JOIN_PER_IP, 3600)


def _err(code: str, message: str, status: int = 403,
         **extra) -> HTTPException:
    """Build an HTTP error whose body is the API error envelope.

    The exception handler below unwraps ``detail`` so the client receives the
    object directly as the top-level JSON body:
    ``{"success": false, "valid": false, "error": ..., "message": ...}``
    Extra keyword args are merged into the envelope so the client can render
    purpose-built screens (e.g. ``revoked_at``, ``suspended_until``) without
    parsing human copy.
    """
    detail = {"success": False, "valid": False,
              "error": code, "message": message}
    detail.update({k: v for k, v in extra.items() if v is not None})
    return HTTPException(status_code=status, detail=detail)


def _utc_now_iso(seconds_ahead: int = 0) -> str:
    """UTC 'YYYY-MM-DD HH:MM:SS' now, optionally offset by seconds."""
    return (datetime.now(timezone.utc)
            + timedelta(seconds=seconds_ahead)).strftime("%Y-%m-%d %H:%M:%S")


SUSPENDED_MAX_HOURS = 168


def _raise_if_suspended(rec: dict) -> None:
    """Refuse a license while it is suspended by the operator. Past-due
    suspensions are silently cleared so the key resumes automatically."""
    until = (rec.get("suspended_until") or "").strip()
    if not until:
        return
    if _iso_to_ts(until) > _now_ts():
        raise _err("license_suspended",
                   f"This license is temporarily suspended by the operator "
                   f"until {until} (UTC). It resumes automatically.",
                   suspended_until=until,
                   reason=_DB.last_event_detail(rec["license_key"], "suspended"))
    _DB.unsuspend(rec["license_key"], detail="auto-resumed")


def _refusal_extra(rec: dict) -> dict:
    """Structured refusal metadata for the client's status screens.

    The client renders three distinct fullscreen gates (banned / revoked /
    timeout) from these fields, so the API keeps them machine-readable instead
    of burying them in the human message.
    """
    extra = {
        "revoked_at": rec.get("revoked_at"),
        "revoked_reason": rec.get("revoked_reason") or "",
        "suspended_until": rec.get("suspended_until"),
    }
    return {k: v for k, v in extra.items() if v not in (None, "")}


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


# Discord Bot & User OAuth (Maximum Optimizations)
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "").strip()
DISCORD_SERVER_ID = DISCORD_GUILD_ID
DISCORD_REGISTRATION_CHANNEL_ID = os.environ.get("DISCORD_REGISTRATION_CHANNEL_ID", "").strip()
DISCORD_CLIENT_ID_USER = os.environ.get("DISCORD_CLIENT_ID_USER", "").strip() or os.environ.get("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET_USER = os.environ.get("DISCORD_CLIENT_SECRET_USER", "").strip() or os.environ.get("DISCORD_CLIENT_SECRET", "").strip()
DISCORD_REDIRECT_USER = os.environ.get("DISCORD_REDIRECT_USER", "").strip()


_DISCORD_API = "https://discord.com/api"
_DISCORD_STATE_TTL = 300            # seconds a sign-in request stays valid
_DISCORD_STATES: dict[str, dict] = {}
_DISCORD_LOCK = threading.Lock()
# Discord blocks default urllib / datacenter-IP User-Agents at the token
# endpoint (HTTP 403 code 1010). Masquerade as a browser so the exchange on
# Render's egress IPs is not mistaken for a bot.
_DISCORD_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Bot REST calls (guild add, channel post) must NOT reuse that browser UA.
# Discord's edge answers a browser-spoofing UA with 403 code 40333
# ("internal network error") on every guild-scoped endpoint while
# /users/@me and /users/@me/guilds still return 200 - which looks exactly
# like an IP block and sent us chasing the wrong cause for days. With a
# DiscordBot UA the same calls succeed (a channel post returned 200).
_DISCORD_BOT_UA = "DiscordBot (https://maximumtweaks.onrender.com, 1.0)"


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


def _discord_exchange_user(code: str, redirect_uri: str) -> dict:
    """Redeem an end-user OAuth code using the *user* app credentials.

    The authorize URL in ``/auth/discord/start`` is built with
    ``DISCORD_CLIENT_ID_USER``/``DISCORD_CLIENT_SECRET_USER``, so Discord will
    only accept the code when it is exchanged by that same client. Exchanging
    it with the bot app's credentials (see ``_discord_exchange``) fails with
    ``unauthorized_client`` / ``invalid_grant``.
    """
    client_id = (DISCORD_CLIENT_ID_USER or "").strip()
    client_secret = (DISCORD_CLIENT_SECRET_USER or "").strip()
    if not client_id or not client_secret:
        return {"__error__": "client credentials missing"}
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
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
        logger.error("discord: user token exchange HTTP %s: %s", e.code, detail)
        return {"__error__": f"HTTP {e.code}: {detail[:200]}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("discord: user token exchange failed")
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


#: Discord OAuth2 error codes -> what the user is actually told. A single flat
#: "Discord authentication failed" for every case made real faults
#: (expired link, wrong app credentials, already-used code) indistinguishable.
_DISCORD_ERROR_REASONS = (
    ("invalid_grant",
     "This sign-in link has already been used or has expired. Close this "
     "window and start again from the app."),
    ("unauthorized_client",
     "The server's Discord app is not allowed to complete sign-in. This is a "
     "server setup problem - please contact support."),
    ("invalid_client",
     "The server's Discord app credentials are incorrect. This is a server "
     "setup problem - please contact support."),
    ("access_denied",
     "You cancelled the authorization, so nothing was changed."),
    ("unsupported_grant_type",
     "The server sent an unsupported request to Discord. Please contact "
     "support."),
    ("invalid_request",
     "Discord rejected the sign-in request. Please start again from the app."),
)


def _discord_failure_reason(token_body: dict) -> str:
    """Plain-English reason from the token exchange result.

    ``_discord_exchange_user`` puts the raw failure in ``__error__``; the
    callback used to throw that away and always said "authentication failed".
    """
    err = str((token_body or {}).get("__error__") or "").strip()
    if not err:
        return "Discord did not return a sign-in token. Please try again."
    low = err.lower()
    for code, reason in _DISCORD_ERROR_REASONS:
        if code in low:
            return reason
    if "timed out" in low or "connection" in low or "getaddrinfo" in low \
            or "urlopen" in low or "ssl" in low:
        return ("Could not reach Discord from the server. Check the server's "
                "internet connection and try again.")
    return "Discord refused the sign-in. Please try again."


def _discord_page(title: str, body: str, link_url: str = "",
                  link_label: str = "", auto_redirect: bool = True) -> HTMLResponse:
    """Tiny brand-consistent page shown in the browser at the end of login.

    ``auto_redirect`` bounces to the web admin panel after 1.4s so an admin
    login cookie takes effect without touching anything. End-user sign-in from
    the desktop app must pass False: the bounce dragged users out of the
    result screen and into Max Manager, so a "Connected" or "Failed" verdict
    was gone before it could be read.

    When ``link_url`` is given the redirect is suppressed regardless - a 1.4s
    bounce would hide the link before the user could click it."""
    e_title = html.escape(title)
    e_body = html.escape(body)
    link_html = ""
    script = ""
    if link_url and link_label:
        link_html = (
            '<p><a href="%s" target="_blank" rel="noopener" '
            'style="display:inline-block;padding:12px 24px;border-radius:8px;'
            'background:#e6cc92;color:#061a1d;text-decoration:none;'
            'font-weight:600">%s</a></p>'
            % (html.escape(link_url, quote=True), html.escape(link_label)))
    elif auto_redirect:
        link_html = ('<p><span class="sub">'
                     '\u2192 taking you back to the admin panel\u2026</span></p>')
        script = ("<script>setTimeout(function(){location.href='/'},1400)"
                  "</script>")
    else:
        link_html = ('<p><span class="sub">You can close this window and '
                     'return to the app.</span></p>')
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
<h1>{e_title}</h1><p>{e_body}</p>{link_html}
</div>{script}
</body></html>""")


def _discord_registration_message(*, event_type: str, username: str,
                                 discord_id: str, account_id: str,
                                 region: str = "", tier: str = "foundation",
                                 status: str = "",
                                 server_membership: str = "UNKNOWN") -> str:
    """Single source of truth for the staff-channel audit line.

    The end-user callback and /auth/discord/register-event both post through
    this so the two paths cannot drift apart."""
    return ("\u2501" * 20 + "\n"
            "MAXIMUM OPTIMIZATIONS\n"
            f"{event_type}\n"
            + "\u2501" * 20 + "\n\n"
            f"Username: {username or 'Unknown'}\n"
            f"Discord ID: {discord_id}\n"
            f"Region: {region or 'N/A'}\n"
            f"Account ID: {account_id or 'N/A'}\n"
            f"Tier: {(tier or 'foundation').upper()}\n"
            f"Status: {status or 'UNKNOWN'}\n\n"
            "Discord: Verified\n"
            f"Server Membership: {server_membership or 'UNKNOWN'}\n\n"
            + "\u2501" * 20)


def _discord_notify_staff(*, event_type: str, username: str, discord_id: str,
                          account_id: str, region: str = "",
                          tier: str = "foundation", status: str = "",
                          server_membership: str = "UNKNOWN") -> bool:
    """Post the audit line. Never raises - a failed staff ping must not turn a
    successful login into an error page."""
    if not DISCORD_REGISTRATION_CHANNEL_ID or not DISCORD_BOT_TOKEN:
        logger.warning("discord: staff channel not configured, skipped ping "
                       "for %s (channel=%s token=%s)", discord_id,
                       bool(DISCORD_REGISTRATION_CHANNEL_ID),
                       bool(DISCORD_BOT_TOKEN))
        return False
    sent = discord_bot_send_message(
        DISCORD_REGISTRATION_CHANNEL_ID,
        _discord_registration_message(
            event_type=event_type, username=username,
            discord_id=discord_id, account_id=account_id, region=region,
            tier=tier, status=status, server_membership=server_membership))
    if not sent:
        logger.warning("discord: staff notification not delivered for %s",
                       discord_id)
    return sent


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
        "tier": normalize_tier(rec.get("tier")),
        "customer": rec.get("customer") or "",
        "activated_at": rec.get("activated_at"),
        "expires_at": rec.get("expires_at"),
        "last_validation": rec.get("last_validated"),
        "device_id": rec.get("device_id"),
    }


def _license_payload(rec: dict) -> dict:
    """License object returned to the desktop client.

    ``plan`` is the billing DURATION and ``tier`` is the subscription LEVEL.
    They are separate on purpose: a yearly Maximum licence and a yearly
    Foundation licence are both ``plan="yearly"`` and differ only in ``tier``.

    ``tier`` is the value the client gates every feature on, so it is normalized
    here on the server. A row with a missing or unrecognised tier resolves to
    ``foundation``, which keeps legacy keys working on the free tier instead of
    silently granting paid features.
    """
    owner = rec.get("customer") or "Maximum Tweaks License"
    return {
        "key": rec["license_key"],
        "status": rec.get("status") or "active",
        "plan": rec.get("plan") or "lifetime",
        "tier": normalize_tier(rec.get("tier")),
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


def _require_reconfirm(code: str | None) -> None:
    """Bulk destructive ops re-verify the raw admin code in the JSON body.

    The caller is already authenticated (session cookie or bearer); this is a
    defence-in-depth 'type the admin code again to confirm' step so a stray
    click (or a hijacked session) cannot wipe/revoke every key by itself.
    """
    if not ADMIN_TOKEN:
        raise _err("admin_disabled", "Admin access is not configured.", 403)
    code = (code or "").strip()
    if not code or not hmac.compare_digest(code, ADMIN_TOKEN):
        raise _err("unauthorized",
                   "Admin code required to confirm this action.", 401)


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


@app.get("/admin/discord/selfcheck")
def admin_discord_selfcheck():
    """Diagnose the Discord wiring. Reports configuration gaps and tells you
    exactly what is missing instead of failing silently at sign-in time.

    Contains no secrets - the bot token is never echoed back.
    """
    return {"ok": True, "discord": discord_bot_self_check()}


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
        reason = (rec.get("revoked_reason") or "").strip()
        if reason == "banned":
            ban_reason = _DB.last_event_detail(key, "banned")
            raise _err("license_banned",
                       "This account has been permanently banned from Maximum "
                       "Tweaks. Contact support to appeal.",
                       **{**_refusal_extra(rec), "reason": ban_reason})
        raise _err("license_revoked",
                   "This license key has been revoked. Contact support for help.",
                   **_refusal_extra(rec))
    if rec["status"] == "expired":
        raise _err("license_expired", "This license key has expired.")
    _raise_if_suspended(rec)

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
        reason = (rec.get("revoked_reason") or "").strip()
        if reason == "banned":
            ban_reason = _DB.last_event_detail(rec["license_key"], "banned")
            raise _err("license_banned",
                       "This account has been permanently banned from Maximum "
                       "Tweaks. Contact support to appeal.",
                       **{**_refusal_extra(rec), "reason": ban_reason})
        raise _err("license_revoked", "This license key has been revoked.", 403,
                   **_refusal_extra(rec))
    if rec["status"] == "expired":
        raise _err("license_expired", "This license key has expired.", 403)
    _raise_if_suspended(rec)
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


#: Discord-authenticated sessions check in with a synthetic entitlement of the
#: form ``DISCORD:<discord_id>`` instead of a licence key. Without this the
#: minute-by-minute heartbeat posted the literal placeholder string the
#: desktop client used to store, the server answered ``invalid_license``, and
#: the client cleared the session and relocked about a minute after a
#: perfectly good sign-in.
_DISCORD_ENTITLEMENT_PREFIX = "DISCORD:"


def _discord_checkin(raw_key: str, payload: "CheckinRequest") -> dict:
    """Heartbeat for a Discord-backed session. The account row is the
    entitlement, so a suspension there locks the app on the next check-in."""
    discord_id = raw_key.split(":", 1)[-1].strip()
    if not discord_id.isdigit():
        raise _err("invalid_license", "Malformed Discord entitlement.")
    device_id = (payload.device_id or "").strip()
    if len(device_id) < 16:
        raise _err("invalid_device",
                   "Device fingerprint is missing or invalid.")

    acc = _DB.get_discord_account_by_discord_id(discord_id)
    if not acc:
        raise _err("invalid_license",
                   "This Discord account is no longer registered.", 403)
    status = (acc.get("status") or "active").lower()
    if status in ("banned", "suspended", "revoked"):
        raise _err("license_" + status,
                   "This Discord account is %s." % status, 403)

    tier = normalize_tier(acc.get("current_tier"))
    return {
        "success": True, "valid": True, "message": "OK",
        "interval_s": CHECKIN_INTERVAL_S,
        "source": "discord",
        "discord_id": discord_id,
        "account_id": acc.get("account_id"),
        "license": {
            "key": raw_key,
            "status": status,
            "plan": "discord",
            "tier": tier,
            "owner": acc.get("discord_username") or "Discord User",
            "customer": acc.get("discord_username") or "",
            "discord_id": discord_id,
            "account_id": acc.get("account_id"),
            "activated_at": acc.get("registered_at"),
            # Explicitly null: a Discord entitlement never expires, and the
            # client reads this key to decide whether to relock.
            "expires_at": None,
            "last_validation": _utc_now_iso(),
        },
    }


@app.post("/api/license/checkin")
def checkin(payload: CheckinRequest):
    """Heartbeat from a previously-activated device. Records per-PC/day
    activity and enforces the key's PC limit:
    * existing PCs keep working (their slot stays warm for 30 days), and
    * a NEW PC beyond ``max_pcs`` is refused (and logged) instead of kicking
      an existing PC out, so over-limit attempts surface in the admin panel as
      "X blocked attempts this week" rather than silently displacing a user.

    Discord-signed-in clients send ``DISCORD:<discord_id>`` and are validated
    against their account row instead of the licences table.
    """
    raw = (payload.key or "").strip()
    if raw.upper().startswith(_DISCORD_ENTITLEMENT_PREFIX):
        return _discord_checkin(raw, payload)
    key = normalize_key(payload.key)
    if not key:
        raise _err("invalid_license", "Invalid license key format.")
    device_id = (payload.device_id or "").strip()
    if len(device_id) < 16:
        raise _err("invalid_device", "Device fingerprint is missing or invalid.")
    pc_name = (payload.pc_name or "").strip()[:80]

    result = _DB.checkin(key, device_id, pc_name)
    if result["status"] != "allowed":
        extra = {k: result[k] for k in ("revoked_at", "revoked_reason",
                                        "suspended_until") if k in result}
        raise _err(result["error"], result["message"], 403, **extra)
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

    ``tier`` is the subscription LEVEL and is deliberately independent of the
    duration in ``plan`` - a yearly Foundation licence and a yearly Maximum
    licence differ only by ``tier``. It is normalized here so a malformed value
    issues a Foundation key rather than accidentally granting a paid level.
    """
    count = max(1, min(int(payload.count), 500))
    prefix = _valid_prefix(payload.prefix)
    plan, expires_at = _resolve_duration(
        payload.plan, (payload.duration or "").strip().lower(),
        payload.expires_at)
    tier = normalize_tier(payload.tier)
    keys = _unique_keys(
        _DB, count, prefix, plan=plan, tier=tier, customer=payload.customer,
        note=payload.note, expires_at=expires_at)
    return {"ok": True, "keys": keys, "count": len(keys),
            "plan": plan, "tier": tier, "expires_at": expires_at}


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


@app.post("/admin/set-tier")
def admin_set_tier(payload: TierRequest, _: None = Depends(_admin_guard)):
    """Change a licence's subscription level.

    This is the single server-side switch behind new subscriptions, upgrades
    and downgrades. It only moves ``tier``; the billing duration in ``plan``
    and the expiry date are managed separately, so changing level never
    silently changes how long the licence runs for.

    The desktop client re-reads the tier on every validate/checkin, so a
    downgrade reaches the subscriber's machine within the offline grace window
    without an reinstall.
    """
    rec = _DB.set_tier(payload.key, payload.tier)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.post("/admin/ban")
def admin_ban(payload: BanRequest, _: None = Depends(_admin_guard)):
    """Hard-ban a key: revoke it and log every PC so re-activation and
    check-ins all refuse. Unban restores the key."""
    rec = _DB.ban(payload.key, (payload.reason or "").strip())
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec),
            "revoked_reason": rec.get("revoked_reason", "")}


@app.post("/admin/unban")
def admin_unban(payload: KeyRequest, _: None = Depends(_admin_guard)):
    rec = _DB.unban(payload.key)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "license": _session_payload(rec)}


@app.post("/admin/suspend")
def admin_suspend(payload: SuspendRequest,
                  _: None = Depends(_admin_guard)):
    """Suspend a key for *hours* (1..168). The client is refused
    ``license_suspended`` during the window and resumes automatically."""
    hours = int(payload.hours or 0)
    if not 1 <= hours <= SUSPENDED_MAX_HOURS:
        raise _err("invalid_hours",
                   f"hours must be between 1 and {SUSPENDED_MAX_HOURS}.", 400)
    until = _utc_now_iso(hours * 3600)
    rec = _DB.suspend(payload.key, until)
    if rec is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "suspended_until": until,
            "license": _session_payload(rec)}


@app.post("/admin/unsuspend")
def admin_unsuspend(payload: KeyRequest, _: None = Depends(_admin_guard)):
    rec = _DB.unsuspend(payload.key)
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


@app.post("/admin/disable-all")
def admin_disable_all(code: str | None = Body(default=None, embed=True),
                      _: None = Depends(_admin_guard)):
    """Revoke every non-revoked key at once (bulk 'start fresh' action).

    Existing customers keep their local session until their next check-in
    (up to 5 minutes), at which point the server refuses the key and their
    app locks. Returns how many keys were revoked.

    Requires the admin code again in the body (defense-in-depth: the caller
    has to re-confirm before a bulk operation).
    """
    _require_reconfirm(code)
    count = _DB.revoke_all()
    return {"ok": True, "revoked": count}


@app.post("/admin/delete-all")
def admin_delete_all(code: str | None = Body(default=None, embed=True),
                     _: None = Depends(_admin_guard)):
    """Permanently delete every license row + related activity/log rows.

    Bulk 'start fresh' action. Not recoverable. Returns how many keys were
    deleted. Requires the admin code again in the body before it runs.
    """
    _require_reconfirm(code)
    count = _DB.delete_all()
    return {"ok": True, "deleted": count}


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
    tier = normalize_tier(payload.tier)
    rec = _DB.create(generate_key(KEY_PREFIX), plan=plan, tier=tier,
                     customer=(payload.customer or "").strip(),
                     note=(payload.note or "").strip(),
                     expires_at=expires_at, max_pcs=max_pcs)
    return {"ok": True, "key": rec["license_key"], "plan": plan,
            "tier": tier, "expires_at": expires_at, "max_pcs": max_pcs}


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
            # Clients heartbeat every 5 min; 660s (11 min) is 2x + slack so a
            # steady heartbeater is counted as online instead of falling in
            # and out of the window.
            if last > now_ts - 660:
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
            "tier": normalize_tier(k.get("tier")),
            "status": status,
            "created_at": k.get("created_at"),
            "activated_at": k.get("activated_at"),
            "expires_at": k.get("expires_at"),
            "revoked_at": k.get("revoked_at"),
            "revoked_reason": k.get("revoked_reason", ""),
            "suspended_at": k.get("suspended_at"),
            "suspended_until": k.get("suspended_until"),
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
            # Every tier is always present so the panel renders a fixed set of
            # counters, and tiers with no keys yet show 0 rather than vanishing.
            "by_tier": {
                t: sum(1 for k in keys if k["tier"] == t)
                for t in TIERS
            },
        },
    }


@app.get("/admin/keys/{key}/inspect")
def admin_inspect(key: str, _: None = Depends(_admin_guard)):
    """Full Inspect sheet for a key: license row, per-PC activity, refusals,
    and the ops/client event timeline (ban/suspend/revoke/applied-tweaks)."""
    data = _DB.inspect(key)
    if data is None:
        raise _err("invalid_license", "Unknown license key.", 404)
    return {"ok": True, "inspect": data}


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


# ---------------------------------------------------------------------------
# Ultra Mode waitlist (joined from the desktop dashboard's "Join the
# waitlist" button; the launch email is sent through mailers.py from
# news@max-opti.co.za). Emails live only in the DB — never in the
# client. No rate-limit metadata or credentials are ever exposed here.
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$"
)


@app.post("/api/waitlist/join")
def waitlist_join(payload: WaitlistJoinRequest, request: Request):
    """Register an email for the launch announcement. Idempotent: a repeat
    sign-up is not an error — the client renders 'already on the list'."""
    ip = (request.client.host if request.client else "unknown")
    if not _limiter_waitlist_ip.hit(ip):
        raise _err("rate_limited",
                   "Too many sign-ups from this connection. Try again in a while.",
                   429)
    email = (payload.email or "").strip().lower()
    if not email or not _EMAIL_RE.fullmatch(email):
        raise _err("invalid_email",
                   "That doesn't look like a valid email address.", 400)
    source = (payload.source or "").strip()[:120]
    result = _DB.waitlist_add(email, source)
    if result["created"]:
        logger.info("waitlist join added=%s source=%r", email, source)
    else:
        logger.info("waitlist join duplicate=%s", email)
    return {
        "ok": True,
        "added": result["created"],
        "message": ("You're on the list." if result["created"]
                    else "This email is already on the list."),
    }


@app.get("/api/waitlist/unsubscribe", include_in_schema=False)
def waitlist_unsubscribe(token: str, request: Request):
    """One-click unsubscribe from launch emails (linked inside every email).
    The token is random per address, so a guessed URL can't touch other
    registrations."""
    emailed = _DB.waitlist_unsubscribe((token or "").strip())
    if emailed is None:
        status = ("That unsubscribe link is no longer valid. If you already "
                  "unsubscribed, you're all set.")
    else:
        status = ("You've been unsubscribed. We won't email you about the "
                  "Ultra Mode launch again.")
    body = f"""\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unsubscribed — Maximum Optimizations</title>
<style>
  body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
    background:#07060d;color:#f4f2fb;font-family:ui-monospace,'JetBrains Mono',Consolas,monospace;}}
  .card{{background:#120f1c;border:1px solid rgba(156,134,245,.45);border-radius:16px;
    padding:36px;max-width:420px;text-align:center;
    box-shadow:0 24px 70px rgba(0,0,0,.5),0 0 40px rgba(156,134,245,.12);}}
  h1{{font-size:18px;margin:0 0 10px;}}
  p{{font-size:13px;color:#948db2;line-height:1.6;margin:0 0 20px;}}
  a{{color:#9c86f5;text-decoration:none;font-size:13px;}}
</style></head>
<body><div class="card">
  <h1>Unsubscribed</h1><p>{html.escape(status)}</p>
  <a href="/">Back to Maximum Optimizations</a>
</div></body></html>"""
    return HTMLResponse(body)


@app.get("/admin/waitlist")
def admin_waitlist(include_unsubscribed: bool = False,
                   _: None = Depends(_admin_guard)):
    """Sign-up roster for the admin panel (emails + subscription state)."""
    entries = _DB.waitlist_list(subscribed_only=not include_unsubscribed)
    return {
        "ok": True,
        "total": _DB.waitlist_count(subscribed_only=False),
        "subscribed": _DB.waitlist_count(subscribed_only=True),
        "entries": [
            {
                "id": e["id"],
                "email": e["email"],
                "source": e["source"],
                "joined_at": e["joined_at"],
                "subscribed": bool(e["subscribed"]),
                "notified_at": e["notified_at"],
            }
            for e in entries
        ],
    }


@app.post("/admin/waitlist/send-launch")
def admin_waitlist_send_launch(payload: WaitlistSendRequest,
                               _: None = Depends(_admin_guard)):
    """Broadcast the launch email to every subscribed address. Empty content
    fields fall back to env overrides, then built-in defaults. Failing
    recipients are reported and not stamped 'notified' so they're retried."""
    _require_reconfirm(payload.code)
    overrides = {
        "subject": payload.subject,
        "heading": payload.heading,
        "message": payload.message,
        "cta_button": payload.cta_button,
        "cta_url": payload.cta_url,
    }
    mailer = get_mailer()
    try:
        stats = send_launch(_DB, mailer, overrides, payload.to_email or None)
    except Exception as exc:  # noqa: BLE001 - guard the broadcast, report it
        logger.exception("waitlist send-launch crashed")
        stats = {
            "total": 0,
            "sent": 0,
            "failed": 1,
            "notified": 0,
            "failures": [{"email": "(server)",
                          "error": f"{type(exc).__name__}: {exc}"}],
        }
    stats["provider"] = mailer.name
    return {"ok": True, **stats}


# Discord Bot helpers



_DISCORD_USER_STATES: dict[str, dict] = {}
_DISCORD_USER_STATE_TTL = 300

def _discord_user_state_new() -> str:
    state = secrets.token_urlsafe(24)
    with _DISCORD_LOCK:
        _DISCORD_USER_STATES[state] = {"exp": time.time() + _DISCORD_USER_STATE_TTL, "status": "waiting"}
    return state


def _discord_user_state_get(state: str) -> dict | None:
    with _DISCORD_LOCK:
        entry = _DISCORD_USER_STATES.get(state)
        if entry is None:
            return None
        if entry["exp"] < time.time():
            _DISCORD_USER_STATES.pop(state, None)
            return None
        return entry


def _discord_user_state_set(state: str, **kw: object) -> None:
    with _DISCORD_LOCK:
        entry = _DISCORD_USER_STATES.get(state)
        if entry is not None:
            entry.update(kw)

@app.post("/auth/discord/start")
def auth_discord_start(request: Request):
    """Start Discord OAuth for app users."""
    client_id = DISCORD_CLIENT_ID_USER
    client_secret = DISCORD_CLIENT_SECRET_USER
    if not client_id or not client_secret:
        raise _err("discord_disabled", "Discord login is not configured.", 403)
    state = _discord_user_state_new()
    redirect_uri = DISCORD_REDIRECT_USER or (str(request.base_url).rstrip("/") + "/auth/discord/callback")
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.join",
        "state": state,
        # Without this Discord silently re-authorises anyone who approved the
        # app before, handing back a token carrying only the scopes of that
        # first approval. A user who once granted just "identify" therefore
        # receives an identify-only token forever, guilds.join is absent, and
        # the bot cannot add them - with no error anywhere on screen.
        "prompt": "consent",
    })
    return {"ok": True, "url": "https://discord.com/oauth2/authorize?" + params, "state": state}

@app.get("/auth/discord/callback")
def auth_discord_callback(request: Request, code: str = "", state: str = ""):
    entry = _discord_user_state_get(state)
    if entry is None:
        return _discord_page("Link expired",
                             "This sign-in link is no longer valid. Close "
                             "this window and start again from the app.",
                             auto_redirect=False)
    if not code:
        _discord_user_state_set(state, status="denied")
        return _discord_page("Cancelled",
                             "Discord authorization was cancelled, so nothing "
                             "was changed.", auto_redirect=False)
    redirect_uri = DISCORD_REDIRECT_USER or (str(request.base_url).rstrip("/") + "/auth/discord/callback")
    token_body = _discord_exchange_user(code, redirect_uri)
    access_token = token_body.get("access_token")
    if not access_token:
        reason = _discord_failure_reason(token_body)
        logger.warning("discord: sign-in rejected uid-unknown %s | raw=%s",
                       reason, str(token_body.get("__error__"))[:200])
        _discord_user_state_set(state, status="error", reason=reason)
        return _discord_page("Sign-in failed", reason, auto_redirect=False)
    user = _discord_user(access_token)
    uid = str(user.get("id") or "")
    username = user.get("username") or uid or "Unknown"
    # Discord reports what it actually granted, which is not necessarily what
    # we asked for. A token without guilds.join cannot add the user to the
    # server, and without this check the only symptom is a silent no-op.
    granted = str(token_body.get("scope") or "")
    granted_set = set(granted.split())
    if granted and "guilds.join" not in granted_set:
        logger.warning("discord: token for uid=%s lacks guilds.join "
                       "(granted=%r) - the bot cannot add them to the server",
                       uid, granted[:200])
        reason = ("Discord signed you in but did not grant permission to add "
                  "you to the server. Open Settings > Authorized Apps, remove "
                  "Maximum Tweaks, then sign in again.")
        _discord_user_state_set(state, status="error", reason=reason)
        return _discord_page("Server access not granted", reason,
                             auto_redirect=False)
    logger.info("discord: token for uid=%s granted scope=%r",
                uid, granted[:200])
    if not uid:
        reason = ("Discord accepted the sign-in but returned no account id, "
                  "so the identity could not be verified. Please try again.")
        logger.warning("discord: /users/@me returned no id | raw=%s",
                       str(user)[:200])
        _discord_user_state_set(state, status="error", reason=reason)
        return _discord_page("Sign-in failed", reason, auto_redirect=False)
    # Find or create account. Everything from here is wrapped so a database or
    # bot hiccup can never leak a raw server_error to the desktop app.
    try:
        existing = _DB.get_discord_account_by_discord_id(uid)
        server_membership = "UNKNOWN"
        # Try to join server
        if DISCORD_GUILD_ID:
            joined = discord_bot_add_member(DISCORD_GUILD_ID, uid, access_token)
            server_membership = "CONFIRMED" if joined else "PENDING"
            logger.info("discord: join attempt uid=%s username=%s -> %s",
                        uid, username, server_membership)
        else:
            logger.warning("discord: DISCORD_GUILD_ID not set, uid=%s was "
                           "not added to any server", uid)
        if existing:
            # Already known: keep the paid entitlement we already granted.
            license_key = existing.get("license_key")
            current_tier = existing.get("current_tier") or "foundation"
            if license_key:
                lic = _DB.get(license_key)
                if lic:
                    lt = lic.get("tier") or current_tier
                    current_tier = lt
            account_id = existing.get("account_id") or ""
            region = existing.get("region") or ""
            status = existing.get("status") or "active"
            already_linked = bool(license_key)
            event_type = "DISCORD_LINKED"
            _DB.log_discord_registration(uid, username, account_id, region, current_tier, license_key, event_type=event_type, server_membership=server_membership, discord_verified=1)
            _discord_user_state_set(state, status="ok", discord_id=uid, username=username, account_id=account_id)
        else:
            # Brand new verified Discord user -> Foundation entitlement.
            acc = _DB.create_discord_account(discord_id=uid, discord_username=username, region="", tier="foundation")
            account_id = acc.get("account_id") or ("MO-" + secrets.token_hex(3).upper())
            region = acc.get("region") or ""
            status = acc.get("status") or "active"
            current_tier = acc.get("current_tier") or "foundation"
            already_linked = False
            event_type = "ACCOUNT_CREATED"
            _DB.log_discord_registration(uid, username, account_id, "", "foundation", None, event_type=event_type, server_membership=server_membership, discord_verified=1)
            _discord_user_state_set(state, status="ok", discord_id=uid, username=username, account_id=account_id)
        # The audit line goes out from here too, not only from
        # /register-event: that is why staff chat stayed empty after a
        # successful "Connected" login.
        staff_notified = _discord_notify_staff(
            event_type=event_type, username=username, discord_id=uid,
            account_id=account_id, region=region, tier=current_tier,
            status=status, server_membership=server_membership)
        logger.info("discord: login complete uid=%s username=%s account=%s "
                    "tier=%s membership=%s staff_notified=%s",
                    uid, username, account_id, current_tier,
                    server_membership, staff_notified)
        if server_membership != "CONFIRMED":
            # Membership is a hard requirement, so never let this look like a
            # finished signup. Hand over the invite and say plainly that they
            # are not in the server yet.
            invite = discord_bot_invite_url()
            body = ("Your account is connected, but you are NOT in the "
                    "Maximum Optimizations server yet. Join with the button "
                    "below, then return to the app.")
            return _discord_page("Join required", body, link_url=invite,
                                 link_label="Join the Maximum Optimizations server",
                                 auto_redirect=False)
        if already_linked:
            body = ("You are already signed in. Your %s access is active and "
                    "you are in the Maximum Optimizations server."
                    % current_tier.upper())
            return _discord_page("Already connected", body, auto_redirect=False)
        body = ("You are connected and have been added to the Maximum "
                "Optimizations server. You can close this window.")
        return _discord_page("Connected", body, auto_redirect=False)
    except Exception:  # noqa: BLE001
        logger.exception("discord: user callback failed after identity verification")
        _discord_user_state_set(state, status="error")
        return _discord_page("Sign-in failed",
                             "We could not finish setting up your account "
                             "after verifying your Discord identity. Please "
                             "try again.", auto_redirect=False)

@app.get("/auth/discord/poll/{state}")
def auth_discord_poll(state: str):
    entry = _discord_user_state_get(state)
    if entry is None:
        return {"ok": True, "status": "expired"}
    if entry.get("status") == "ok":
        return {"ok": True, "status": "ok", "discord_id": entry.get("discord_id"), "username": entry.get("username"), "account_id": entry.get("account_id")}
    if entry.get("status") == "error":
        # Carry the real reason so the app can say why, not just "failed".
        return {"ok": True, "status": "error",
                "reason": entry.get("reason")
                or "Sign-in could not be completed."}
    if entry.get("status") == "denied":
        return {"ok": True, "status": "denied"}
    return {"ok": True, "status": "waiting"}

@app.post("/auth/discord/set-region")
def auth_discord_set_region(payload: dict = Body(default={})):
    discord_id = str(payload.get("discord_id") or "")
    region = str(payload.get("region") or "")
    if not discord_id:
        raise _err("bad_request", "discord_id required", 400)
    acc = _DB.get_discord_account_by_discord_id(discord_id)
    if not acc:
        raise _err("not_found", "account not found", 404)
    # update region
    now = _utc_now()
    def _fn(conn):
        _DB._exec(conn, "UPDATE discord_accounts SET region = ?, updated_at = ? WHERE discord_id = ?", (region, now, discord_id))
    with _DB._lock:
        _DB._run_with_retry(_fn)
    return {"ok": True}


@app.post("/auth/discord/register-event")
def auth_discord_register_event(payload: dict = Body(default={})):
    discord_id = str(payload.get("discord_id") or "")
    event_type = str(payload.get("event_type") or "ACCOUNT_EVENT")
    if not discord_id:
        raise _err("bad_request", "discord_id required", 400)
    acc = _DB.get_discord_account_by_discord_id(discord_id)
    if acc:
        log = _DB.log_discord_registration(discord_id, acc.get("discord_username") or "", acc.get("account_id"), acc.get("region") or "", acc.get("current_tier") or "foundation", acc.get("license_key"), event_type=event_type, server_membership="UNKNOWN", discord_verified=1)
    else:
        log = None
    # Send to staff channel
    msg = None
    sent = False
    if DISCORD_REGISTRATION_CHANNEL_ID and DISCORD_BOT_TOKEN:
        acc_id = acc.get("account_id") if acc else "N/A"
        uname = acc.get("discord_username") if acc else "Unknown"
        reg = acc.get("region") if acc else ""
        tier = acc.get("current_tier") if acc else "foundation"
        status = acc.get("status") if acc else "UNKNOWN"
        sent = _discord_notify_staff(
            event_type=event_type, username=uname or "Unknown",
            discord_id=discord_id, account_id=acc_id or "N/A", region=reg or "",
            tier=tier, status=status,
            server_membership=str(payload.get("server_membership") or "Unknown"))
        msg = _discord_registration_message(
            event_type=event_type, username=uname or "Unknown",
            discord_id=discord_id, account_id=acc_id or "N/A", region=reg or "",
            tier=tier, status=status,
            server_membership=str(payload.get("server_membership") or "Unknown"))
    return {"ok": True, "logged": bool(log), "notified": sent}

@app.get("/auth/discord/session")
def auth_discord_session(discord_id: str = ""):
    if not discord_id:
        raise _err("bad_request", "discord_id required", 400)
    acc = _DB.get_discord_account_by_discord_id(discord_id)
    if not acc:
        raise _err("not_found", "account not found", 404)
    # Determine entitlement - backend is authoritative
    tier = acc.get("current_tier") or "foundation"
    # If linked to a license, maybe get tier from license
    lic = None
    if acc.get("license_key"):
        lic = _DB.get(acc.get("license_key"))
        if lic:
            tier = lic.get("tier") or tier
    return {"ok": True, "account": {"account_id": acc.get("account_id"), "discord_id": acc.get("discord_id"), "discord_username": acc.get("discord_username"), "region": acc.get("region"), "tier": tier, "license_key": acc.get("license_key")}, "entitlement": tier}

# --- Bot helpers ---------------------------------------------------------
# The bot needs two capabilities for the registration flow:
#   * Add members to the guild  -> guilds.join is requested in the user OAuth
#     scope and redeemed here against the bot token.
#   * Post the audit line       -> requires Send Messages in the target
#     channel. "View Channel" alone is NOT enough.
# Bitfield used for the invite URL below.
DISCORD_PERM_ADMINISTRATOR = 1 << 3        # 8
DISCORD_PERM_VIEW_CHANNEL = 1 << 10        # 1024
DISCORD_PERM_SEND_MESSAGES = 1 << 11      # 2048
DISCORD_PERM_READ_HISTORY = 1 << 16       # 65536 (nice-to-have)
DISCORD_BOT_PERMISSIONS = (DISCORD_PERM_VIEW_CHANNEL
                           | DISCORD_PERM_SEND_MESSAGES
                           | DISCORD_PERM_READ_HISTORY)   # = 68608


def discord_bot_invite_url() -> str:
    """Bot invite link carrying the permissions the flow actually needs."""
    client_id = (os.environ.get("DISCORD_CLIENT_ID", "").strip()
                 or (DISCORD_CLIENT_ID_USER or "").strip())
    if not client_id:
        return ""
    return ("https://discord.com/oauth2/authorize"
            f"?client_id={client_id}"
            f"&permissions={DISCORD_BOT_PERMISSIONS}"
            "&scope=bot")


def _discord_bot_headers():
    if not DISCORD_BOT_TOKEN:
        return None
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": _DISCORD_BOT_UA}


def _discord_bot_call(method: str, url: str, body: dict | None = None):
    """Shared bot REST call. Returns (ok, status, detail) and always logs the
    reason on failure - silent ``False`` returns were impossible to debug.

    ``detail`` is the parsed JSON body on success (or ``None`` for an empty
    204) and an error string on failure, so callers that need to inspect the
    response can, instead of inferring the outcome from the status alone."""
    headers = _discord_bot_headers()
    if not headers:
        logger.warning("discord: bot call skipped, DISCORD_BOT_TOKEN not set")
        return False, 0, "DISCORD_BOT_TOKEN not configured"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            # The body matters: PUT /guilds/{id}/members/{user} answers 201
            # when the member was added and 204 when they were already there.
            # Discarding it made every 2xx look like a successful join.
            raw = r.read().decode("utf-8", "replace")
            parsed = None
            if raw.strip():
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None
            return r.getcode() in (200, 201, 204), r.getcode(), parsed
    except urllib.error.HTTPError as e:
        detail = _discord_http_error(e)
        # An edge refusal is NOT a permissions problem. Reporting it as one
        # sent us chasing the wrong fix, so detect it first.
        if _discord_is_ip_block(detail):
            hint = ("Discord refused the request at its edge (code "
                    f"{e.code}); not a permission issue - the usual cause is "
                    "a browser User-Agent on a bot call (we send "
                    "_DISCORD_BOT_UA), or the token lacking the bot scope")
        else:
            hint = {
                401: "bot token invalid or revoked",
                403: "bot lacks permission, or is not in the guild/channel",
                404: "guild/channel id wrong, or the bot cannot see it",
            }.get(e.code, "")
        logger.error("discord: bot %s %s -> HTTP %s %s %s",
                     method, url.rsplit("/", 2)[-2:], e.code, detail, hint)
        return False, e.code, (detail + " " + hint).strip()[:300]
    except Exception as e:  # noqa: BLE001
        logger.exception("discord: bot %s failed", method)
        return False, 0, str(e)[:200]


def discord_bot_is_member(guild_id: str, user_id: str) -> bool | None:
    """Ask Discord directly whether a user is in the guild.

    Returns True/False, or None when the question could not be answered
    (no bot token, bad ids, or Discord unreachable). None is deliberately
    distinct from False: "we could not check" must never be reported to
    staff as "not in the server".
    """
    if not DISCORD_BOT_TOKEN or not guild_id or not user_id:
        return None
    headers = _discord_bot_headers()
    if not headers:
        return None
    req = urllib.request.Request(
        f"{_DISCORD_API}/v10/guilds/{guild_id}/members/{user_id}",
        headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.getcode() == 200:
                return True
            return None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Discord's authoritative "this user is not in the guild".
            return False
        logger.warning("discord: membership check for %s failed (HTTP %s): %s",
                       user_id, e.code, _discord_http_error(e)[:150])
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("discord: membership check for %s errored: %s",
                       user_id, str(e)[:150])
        return None


def discord_bot_add_member(guild_id: str, user_id: str,
                           access_token: str = "") -> bool:
    """Add an authorized user to our guild, then verify they are actually in it.

    A 2xx from PUT /guilds/{id}/members/{user} is NOT proof of membership.
    Discord answers 201 when it added the member and 204 when the user was
    already present, and a 204 with an empty body gives us nothing to inspect.
    Treating "no exception" as success made the staff card claim
    ``Server Membership: CONFIRMED`` for a user who was never added.

    So: attempt the add, then ask Discord whether the member exists. Only a
    confirmed membership returns True.
    """
    if not DISCORD_BOT_TOKEN or not guild_id or not user_id:
        return False
    body = {"access_token": access_token} if access_token else {}
    ok, status, detail = _discord_bot_call(
        "PUT",
        f"{_DISCORD_API}/v10/guilds/{guild_id}/members/{user_id}",
        body)
    if not ok:
        logger.warning("discord: add-to-server failed for user %s (%s)",
                       user_id, detail or status)
        return False

    # The add was accepted. A 201 carries the member object; a 204 means
    # "already a member", which is also fine but must be verified because an
    # empty 204 is indistinguishable from a silent no-op at the status level.
    if status == 201 and isinstance(detail, dict) and detail.get("user"):
        logger.info("discord: added user %s to guild %s", user_id, guild_id)
        return True

    verified = discord_bot_is_member(guild_id, user_id)
    if verified is True:
        logger.info("discord: user %s is a member of guild %s", user_id, guild_id)
        return True
    if verified is False:
        logger.error("discord: add-to-server reported success for user %s but "
                     "Discord says they are NOT in guild %s", user_id, guild_id)
        return False
    # Could not verify. Do not claim membership we could not confirm.
    logger.warning("discord: could not verify membership for user %s after a "
                   "%s from add-to-server; reporting unconfirmed", user_id, status)
    return False


def discord_bot_send_message(channel_id: str, content: str) -> bool:
    """Post the staff-facing registration line to the audit channel."""
    if not DISCORD_BOT_TOKEN or not channel_id or not content:
        return False
    ok, status, detail = _discord_bot_call(
        "POST",
        f"{_DISCORD_API}/v10/channels/{channel_id}/messages",
        {"content": content[:2000]})
    if not ok:
        logger.warning("discord: staff channel post failed (%s)",
                       detail or status)
    return ok


#: Discord answers 403 with code 40333 ("internal network error") or 1010
#: (Cloudflare fingerprint block) for some endpoints depending on the request
#: identity. For our bot calls the proven cause was the browser User-Agent -
#: /users/@me stayed 200 while every guild endpoint returned 40333 from two
#: unrelated networks, and a DiscordBot UA fixed all of them. Treat these as
#: "the request was refused at the edge", never as a permissions problem.
_DISCORD_IP_BLOCK_CODES = ("40333", "1010")


def _discord_is_ip_block(detail: str) -> bool:
    d = (detail or "").lower()
    return any(c in d for c in _DISCORD_IP_BLOCK_CODES) or "internal network error" in d


def _discord_channel_overwrite_grants(channel_id: str, bot_id: str,
                                       wanted: int) -> int:
    """Permission bits a channel's overwrite list grants the bot directly.

    Guild role permissions can be 0 while a channel-specific overwrite still
    allows everything the flow needs, so the self-check has to look here
    before reporting a missing permission. Returns 0 on any failure."""
    if not channel_id or not bot_id:
        return 0
    headers = _discord_bot_headers()
    if not headers:
        return 0
    req = urllib.request.Request(
        f"{_DISCORD_API}/v10/channels/{channel_id}", headers=headers,
        method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ch = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return 0
    if not isinstance(ch, dict):
        return 0
    granted = 0
    everyone = str(ch.get("guild_id") or "")
    for ow in (ch.get("permission_overwrites") or []):
        if str(ow.get("id")) != str(bot_id):
            continue
        allow = int(ow.get("allow") or 0)
        deny = int(ow.get("deny") or 0)
        granted |= allow & wanted & ~deny
    return granted


def _db_identity() -> dict:
    """Where this process stores data, plus the Discord row counts.

    Deliberately reports only a host label and counts - never a password,
    never a full DSN. Render and a local shell can then be compared in one
    glance, which is the only way to tell "nothing was written" apart from
    "we are looking at two different databases".
    """
    out = {"engine": "sqlite", "target": "", "accounts": None,
           "registrations": None}
    try:
        dsn = (os.environ.get("DATABASE_URL") or "").strip()
        if not dsn:
            out["target"] = os.environ.get("LICENSE_DB_PATH", "") or "licenses.db"
            return out
        # psycopg://user:pass@host/db?params -> host/db, with the password gone.
        host = dsn.split("@")[-1]
        out["engine"] = "postgres"
        out["target"] = host.split("?")[0]
        import psycopg
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as pg:
            with pg.cursor() as cur:
                for key, table in (("accounts", "discord_accounts"),
                                   ("registrations", "discord_registrations")):
                    try:
                        cur.execute(f"SELECT count(*) FROM {table}")
                        out[key] = cur.fetchone()[0]
                    except Exception:  # noqa: BLE001
                        out[key] = None
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:120]
    return out


def discord_bot_self_check() -> dict:
    """Report whether the bot pieces are configured and the bot is in the
    guild. Safe to call from /admin; never returns the token itself."""
    out = {
        "token_configured": bool(DISCORD_BOT_TOKEN),
        "guild_id_configured": bool(DISCORD_GUILD_ID),
        "channel_id_configured": bool(DISCORD_REGISTRATION_CHANNEL_ID),
        "user_client_configured": bool(DISCORD_CLIENT_ID_USER
                                       and DISCORD_CLIENT_SECRET_USER),
        # Surfaced so a stale DISCORD_CLIENT_ID is visible instead of
        # silently sending admin login to a different Discord application.
        "user_login_client_id": DISCORD_CLIENT_ID_USER or "",
        "admin_login_client_id": _discord_config()["client_id"],
        "permissions_decimal": DISCORD_BOT_PERMISSIONS,
        "invite_url": discord_bot_invite_url(),
        # Which database this process is actually writing to, and how much it
        # holds. Without this, an empty table is indistinguishable between
        # "no sign-ins happened" and "I am querying a different database than
        # production" - which is exactly how a lost registration gets missed.
        "db_engine": _db_identity(),
        "bot_reachable": False,
        "in_guild": False,
        "guild_name": "",
        "can_read_channel": False,
        "network_restricted": False,
        "problems": [],
    }
    if not out["token_configured"]:
        out["problems"].append("DISCORD_BOT_TOKEN is not set - the bot cannot "
                               "add users to the server or post to staff chat.")
    if not out["guild_id_configured"]:
        out["problems"].append("DISCORD_GUILD_ID is not set.")
    if not out["channel_id_configured"]:
        out["problems"].append("DISCORD_REGISTRATION_CHANNEL_ID is not set.")
    if not out["user_client_configured"]:
        out["problems"].append("DISCORD_CLIENT_ID_USER / "
                               "DISCORD_CLIENT_SECRET_USER are not set.")
    # The admin panel and the end-user sign-in should authorise through the
    # same Discord application. When they do not, admin login breaks with
    # "invalid redirect_uri" for reasons that look nothing like the cause.
    if (out["user_login_client_id"] and out["admin_login_client_id"]
            and out["user_login_client_id"] != out["admin_login_client_id"]):
        out["problems"].append(
            "DISCORD_CLIENT_ID (%s) does not match DISCORD_CLIENT_ID_USER "
            "(%s) - admin login is pointed at a different Discord "
            "application. Set DISCORD_CLIENT_ID to %s and restart the "
            "service."
            % (out["admin_login_client_id"], out["user_login_client_id"],
               out["user_login_client_id"]))
    if not out["token_configured"]:
        return out

    headers = _discord_bot_headers()

    def _get(path: str):
        req = urllib.request.Request(f"{_DISCORD_API}/v10{path}",
                                     headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    try:
        me = _get("/users/@me")
        out["bot_reachable"] = True
        out["bot_username"] = me.get("username") or me.get("global_name")
    except urllib.error.HTTPError as e:
        detail = _discord_http_error(e)
        if _discord_is_ip_block(detail):
            out["network_restricted"] = True
            out["problems"].append(
                "Discord refused this request at its edge (code %s). The token "
                "is valid (users/@me answered); check that bot calls send the "
                "DiscordBot User-Agent and not a browser one." % e.code)
        else:
            out["problems"].append(
                f"bot token rejected by Discord (HTTP {e.code}): {detail[:120]}")
    except Exception as e:  # noqa: BLE001
        out["problems"].append(f"bot unreachable: {str(e)[:150]}")

    # Guild membership: /users/@me/guilds is the reliable endpoint. The
    # /guilds/{id}/members/{bot} route is frequently IP-blocked and would
    # otherwise produce a false "not in guild".
    if out["bot_reachable"] and DISCORD_GUILD_ID:
        try:
            guilds = _get("/users/@me/guilds")
            if isinstance(guilds, list):
                for g in guilds:
                    if str(g.get("id")) == str(DISCORD_GUILD_ID):
                        out["in_guild"] = True
                        out["guild_name"] = g.get("name") or ""
                if not out["in_guild"]:
                    out["problems"].append(
                        "the bot is NOT in the configured guild "
                        f"({DISCORD_GUILD_ID}). Invite it with: "
                        + out["invite_url"])
        except urllib.error.HTTPError as e:
            detail = _discord_http_error(e)
            if _discord_is_ip_block(detail):
                out["network_restricted"] = True
                out["problems"].append(
                    "could not list the bot's guilds - Discord refused the "
                    f"request at its edge (code {e.code}). Membership is "
                    "unverified.")
            else:
                out["problems"].append(
                    f"guild list failed (HTTP {e.code}): {detail[:120]}")
        except Exception as e:  # noqa: BLE001
            out["problems"].append(f"guild list failed: {str(e)[:120]}")

    # Permission bits come from the member object; treat an edge refusal as
    # "unknown" rather than "missing permissions".
    if out["in_guild"] and out.get("bot_username"):
        try:
            member = _get(f"/guilds/{DISCORD_GUILD_ID}/members/{me['id']}")
            perms = int(member.get("permissions") or 0)
            out["bot_permission_bits"] = perms
            missing = []
            if perms & DISCORD_PERM_ADMINISTRATOR:
                # Administrator overrides every channel-level bit.
                missing = []
            else:
                # A channel overwrite can grant what the guild role cannot.
                # The bot here has guild perms 0 yet posts fine, because
                # account-registrations allows 3072 directly to its user id -
                # so consult the target channel before crying "missing".
                granted = _discord_channel_overwrite_grants(
                    DISCORD_REGISTRATION_CHANNEL_ID, str(me["id"]),
                    DISCORD_PERM_VIEW_CHANNEL | DISCORD_PERM_SEND_MESSAGES)
                out["channel_overwrite_grants"] = granted
                need = DISCORD_PERM_VIEW_CHANNEL | DISCORD_PERM_SEND_MESSAGES
                if not perms & DISCORD_PERM_VIEW_CHANNEL and not granted & DISCORD_PERM_VIEW_CHANNEL:
                    missing.append("View Channel")
                if not perms & DISCORD_PERM_SEND_MESSAGES and not granted & DISCORD_PERM_SEND_MESSAGES:
                    missing.append("Send Messages")
            if missing:
                out["problems"].append(
                    "bot is in the guild but missing: " + ", ".join(missing)
                    + ". Re-invite using: " + out["invite_url"])
        except urllib.error.HTTPError as e:
            detail = _discord_http_error(e)
            if _discord_is_ip_block(detail):
                out["network_restricted"] = True
                out["problems"].append(
                    "permissions could not be read - Discord refused the "
                    f"request at its edge (code {e.code}).")
            elif e.code == 404:
                out["problems"].append(
                    "bot member record not found for this guild.")
            else:
                out["problems"].append(
                    f"permission check failed (HTTP {e.code}): {detail[:120]}")
        except Exception as e:  # noqa: BLE001
            out["problems"].append(f"permission check failed: {str(e)[:120]}")

    if out["in_guild"] and DISCORD_REGISTRATION_CHANNEL_ID:
        try:
            ch = _get(f"/channels/{DISCORD_REGISTRATION_CHANNEL_ID}")
            out["can_read_channel"] = True
            out["channel_name"] = ch.get("name") if isinstance(ch, dict) else ""
        except urllib.error.HTTPError as e:
            detail = _discord_http_error(e)
            if _discord_is_ip_block(detail):
                out["network_restricted"] = True
                out["problems"].append(
                    "channel visibility unverified - Discord refused the "
                    f"request at its edge (code {e.code}).")
            elif e.code == 404:
                out["problems"].append(
                    "registration channel not found. Check "
                    "DISCORD_REGISTRATION_CHANNEL_ID (enable Developer Mode "
                    "and right-click the channel -> Copy ID).")
            else:
                out["problems"].append(
                    "bot cannot see the registration channel. Check the id and "
                    "that the bot has View Channel + Send Messages there.")
        except Exception:  # noqa: BLE001
            pass
    return out
