"""Rex Tweaks — Discord OAuth2 authentication backend.

A small standalone FastAPI service that owns the Discord Client Secret and
validates identities for the REX TWEAKS desktop app.

Flow
----
1. The desktop app opens  GET /auth/discord/login?state=<state>
2. this service 302-redirects the browser to Discord's authorize endpoint
   requesting the scopes `identify email guilds.join`.
3. Discord authenticates the user and redirects to DISCORD_REDIRECT_URI
   (/auth/discord/callback) carrying a one-time authorization code.
4. The callback validates the `state`, exchanges the code for an access token
   (Client Secret used here, on the server, never sent to the client), then:
     a. fetches /users/@me                       -> identity (id, name, email)
     b. PUT /guilds/{GUILD}/members/{id}         -> adds the user to the server
        using the OAuth access token (guilds.join; the bot is already in the
        server, so the user does NOT need to have joined beforehand).
     c. GET /guilds/{GUILD}/members/{id}         -> confirms membership (bot)
     d. PUT .../members/{id}/roles/{ROLE}        -> assigns the Verified role
        using the bot (bot role is above Verified and has Manage Roles).
     e. re-reads the member object to confirm the role actually stuck.
5. Success is reported ONLY when BOTH the server join AND the Verified role
   assignment have succeeded; otherwise an error result is stored.
6. The result is stored in a short-lived in-memory session keyed by `state`.
7. The desktop app polls  GET /auth/discord/status?state=<state>  to learn
   whether verification succeeded.

Security
--------
- The Client Secret AND the Bot token are read only from the environment here.
  They are never exposed to the desktop application and never logged.
- The OAuth authorization `code` is never logged either.
- `state` tokens are unguessable, single-use and expire after a few minutes.
- Access tokens are exchanged and discarded on the server; they are not
  persisted.

Run
---
    pip install -r requirements.txt
    copy .env.example .env        # then fill in real values (incl. bot token)
    uvicorn main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.parse

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # noqa: BLE001
    pass  # env vars may be supplied directly by the shell instead

# ---------------------------------------------------------------------------
# Configuration (environment only — never hard-code secrets)
# ---------------------------------------------------------------------------

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "").strip()
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "").strip()
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "").strip()
DISCORD_ROLE_ID = os.environ.get("DISCORD_ROLE_ID", "").strip()
# Bot token for the REX TWEAKS bot: required to add members (guilds.join is
# performed by the bot on the user's behalf) and to assign the Verified role.
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

# guilds.join lets the backend add the user to the server without the user
# needing to join first; email captures the verified-email flag. No other
# read scopes are required because membership + role checks run through the
# bot instead of the user's token.
DISCORD_SCOPES = "identify email guilds.join"

DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = "https://discord.com/api/oauth2/token"
DISCORD_ME = "https://discord.com/api/users/@me"
DISCORD_GUILD_API = f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}"

STATE_TTL_SECONDS = 600  # a pending login expires after 10 minutes
_OK = {"status": "ok", "service": "rextweaks-auth"}


# ---------------------------------------------------------------------------
# Short-lived in-memory login sessions (keyed by OAuth `state`)
# ---------------------------------------------------------------------------

class AuthResult(BaseModel):
    authenticated: bool
    discord_id: str = ""
    username: str = ""
    display_name: str = ""
    avatar: str = ""
    email: str = ""
    verified_email: bool = False
    member: bool = False
    verified_role: bool = False
    error: str = ""


_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


def _purge_expired() -> None:
    now = time.time()
    expired = [s for s, rec in _sessions.items()
               if now - rec["created"] > STATE_TTL_SECONDS]
    for s in expired:
        _sessions.pop(s, None)


app = FastAPI(title="Rex Tweaks Auth", version="1.1.0")


@app.get("/health")
def health():
    return _OK


@app.get("/auth/discord/login")
def discord_login(state: str = Query(...)):
    """Register the login attempt and bounce the browser to Discord."""
    if not (DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and DISCORD_REDIRECT_URI):
        return HTMLResponse("Auth backend is not configured.", status_code=500)
    if not _valid_state(state):
        return HTMLResponse("Invalid state parameter.", status_code=400)

    _purge_expired()
    with _sessions_lock:
        # A previously-completed/consumed state must not be reused.
        if state in _sessions:
            return HTMLResponse("State already in use.", status_code=400)
        _sessions[state] = {
            "status": "pending",
            "result": None,
            "created": time.time(),
        }

    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": DISCORD_SCOPES,
        "state": state,
    })
    return RedirectResponse(f"{DISCORD_AUTHORIZE}?{params}", status_code=302)


@app.get("/auth/discord/callback")
def discord_callback(code: str = Query(None),
                     state: str = Query(None),
                     error: str = Query(None),
                     error_description: str = Query(None)):
    """Handle Discord's redirect, join the server and assign the Verified role."""
    with _sessions_lock:
        rec = _sessions.get(state) if state else None

    # Single-use: a state that already produced a result must not be
    # processed again (otherwise the record would be overwritten before the
    # desktop app polls /auth/discord/status).
    if rec is not None and rec["status"] != "pending":
        return HTMLResponse("Login state was already consumed.", status_code=400)

    if error:
        _record(state, rec, "error", AuthResult(
            authenticated=False,
            error=f"Discord authorization was not granted: "
                  f"{error_description or error}"))
        return _result_page(success=False, member=False, role=False,
                            error="Authorization not granted.")

    if state is None or rec is None:
        return HTMLResponse("Unknown or expired login state.", status_code=400)
    if not code:
        return HTMLResponse("Missing authorization code.", status_code=400)

    try:
        token_payload = _exchange_code(code)
        access_token = token_payload["access_token"]

        # a) identity (id, username, email, avatar)
        user = _fetch_current_user(access_token)
        uid = str(user.get("id") or "")
        if not uid:
            raise ValueError("Discord returned an invalid profile.")

        # b) add the user to the guild with their OAuth token (guilds.join).
        _join_guild(uid, access_token)

        # c) confirm they are now a guild member (bot).
        member = _bot_get_member(uid)

        # d) assign the Verified role (bot).
        _assign_verified_role(uid)

        # e) confirm the role actually stuck.
        verified = _member_has_role(_bot_get_member(uid))

        result = AuthResult(
            authenticated=True,
            discord_id=uid,
            username=str(user.get("username") or ""),
            display_name=str(user.get("global_name") or user.get("username") or ""),
            avatar=str(user.get("avatar") or ""),
            email=str(user.get("email") or ""),
            verified_email=bool(user.get("verified")),
            member=True,
            verified_role=verified,
        )
        if not verified:
            raise ValueError("The Verified role could not be granted.")
        _record(state, rec, "success", result)
        return _result_page(success=True, member=True, role=True)
    except Exception as exc:  # noqa: BLE001
        # Message is a safe, user-facing summary — never a code or secret.
        _record(state, rec, "error", AuthResult(
            authenticated=False,
            error=str(exc) or "Discord verification failed."))
        return _result_page(success=False, member=False, role=False,
                            error=str(exc) or "Verification failed. Try again.")


@app.get("/auth/discord/status")
def discord_status(state: str = Query(...)):
    """Polling endpoint used by the desktop app to pick up the result."""
    _purge_expired()
    with _sessions_lock:
        rec = _sessions.get(state)
    if rec is None:
        return {"status": "pending", "result": None}
    return {"status": rec["status"], "result": rec["result"]}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _valid_state(state: str) -> bool:
    return bool(state) and len(state) >= 16 and len(state) <= 128


def _record(state: str, rec: dict | None, status: str, result: AuthResult):
    if rec is None:
        return
    with _sessions_lock:
        rec["status"] = status
        rec["result"] = result.model_dump()


def _http_json(client: httpx.Client, method: str, url: str,
               headers: dict | None = None):
    resp = client.request(method, url, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Discord API returned HTTP {resp.status_code}")
    return resp.json()


def _bot_headers() -> dict:
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}


def _exchange_code(code: str) -> dict:
    """Exchange the authorization code for an access token (server-side)."""
    payload = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.post(DISCORD_TOKEN, data=payload)
        if resp.status_code != 200:
            raise ValueError("Discord rejected the authorization code.")
        data = resp.json()
    if not data.get("access_token"):
        raise ValueError("Discord returned no access token.")
    return data


def _fetch_current_user(access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=20.0) as client:
        user = _http_json(client, "GET", DISCORD_ME, headers=headers)
    return user


def _join_guild(uid: str, access_token: str) -> None:
    """Add ``uid`` to the guild using their OAuth token (guilds.join scope).

    The bot performs the add on behalf of the user. 201 = newly joined,
    204 = already a member (both fine). Requires the bot to be in the guild.
    """
    with httpx.Client(timeout=20.0) as client:
        resp = client.put(
            f"{DISCORD_GUILD_API}/members/{uid}",
            json={"access_token": access_token},
            headers=_bot_headers(),
        )
    if resp.status_code not in (201, 204):
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        raise ValueError("Could not add you to the REX TWEAKS server "
                         f"(Discord HTTP {resp.status_code} {detail}).")


def _bot_get_member(uid: str) -> dict:
    """Fetch the member object via the bot; confirms guild membership."""
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(
            f"{DISCORD_GUILD_API}/members/{uid}",
            headers=_bot_headers(),
        )
    if resp.status_code != 200:
        raise ValueError("Could not confirm your REX TWEAKS server membership "
                         f"(Discord HTTP {resp.status_code}).")
    return resp.json()


def _assign_verified_role(uid: str) -> None:
    """Assign the Verified role to ``uid`` using the bot."""
    with httpx.Client(timeout=20.0) as client:
        resp = client.put(
            f"{DISCORD_GUILD_API}/members/{uid}/roles/{DISCORD_ROLE_ID}",
            headers=_bot_headers(),
        )
    if resp.status_code != 204:
        raise ValueError("Could not grant you the Verified role "
                         f"(Discord HTTP {resp.status_code}).")


def _member_has_role(member: dict) -> bool:
    """True if the member object lists the configured Verified role."""
    try:
        roles = member.get("roles") or []
        return str(DISCORD_ROLE_ID) in {str(r) for r in roles}
    except Exception:  # noqa: BLE001
        return False


def _result_page(success: bool, member: bool, role: bool, error: str = "") -> HTMLResponse:
    """The tab the browser lands on after the OAuth round-trip."""
    if success:
        lines = [
            "<li>Authentication succeeded</li>",
            "<li>You were added to the REX TWEAKS server</li>",
            "<li>Verified role assigned</li>",
            "<li>You may close this tab and return to REX TWEAKS.</li>",
        ]
    else:
        lines = [
            "<li>Authentication failed.</li>",
            f"<li>{error}</li>",
            "<li>Close this tab and try again in REX TWEAKS.</li>",
        ]
    body = "\n".join(lines)
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>REX TWEAKS</title></head>
<body style="background:#05070A;color:#EEF4F8;font-family:Segoe UI,sans-serif;
text-align:center;padding:90px 20px;">
<div style="max-width:420px;margin:0 auto;">
  <div style="color:#00F2FE;font-size:22px;font-weight:900;letter-spacing:4px;
  margin-bottom:18px;">REX TWEAKS</div>
  <div style="font-size:15px;">Discord verification</div>
  <ul style="list-style:none;padding:0;margin-top:22px;font-size:13px;
  color:#D6E4EC;">{body}</ul>
</div></body></html>""")