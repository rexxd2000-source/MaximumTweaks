"""Discord identity verification for Rex Tweaks — backend client.

The desktop app no longer holds the Discord Client Secret or runs the OAuth2
flow itself. That responsibility lives in the separate FastAPI service under
``auth_backend/``. This module is a thin HTTP client for it:

  * ``login()`` opens ``{AUTH_SERVER_URL}/auth/discord/login?state=...`` in the
    browser, then polls ``/auth/discord/status`` until the backend has finished
    the Discord round-trip (guild-membership + Verified-role checks included).
  * The resulting identity is stored in ``config/state.json`` under "discord".

Pure-stdlib (urllib) so the CLI and GUI both work without extra dependencies.
All network work happens in a worker thread — the GUI never calls these on the
UI thread (see ui.discord).
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from config.app_config import AUTH_SERVER_URL, DISCORD_CDN
from engine import state as state_mgr
from rexlog import logger

SESSION_KEY = "discord"
_AUTH_TIMEOUT = 240
_POLL_INTERVAL = 1.5


def is_configured() -> bool:
    return bool(AUTH_SERVER_URL)


def session() -> dict | None:
    return state_mgr.discord_session()


def display_name(prof: dict | None) -> str:
    """Verified identity only: until a session is verified the user is
    always 'guest' (verify-first guest strategy)."""
    if not prof or not prof.get("verified"):
        return "guest"
    return prof.get("name") or prof.get("username") or "guest"


def is_verified(prof: dict | None) -> bool:
    return bool(prof and prof.get("verified"))


# ---------------------------------------------------------------------------
# Low-level HTTP helpers (stdlib)
# ---------------------------------------------------------------------------

class _HttpError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def _http_json(url: str, method="GET", data: bytes | None = None,
               headers: dict | None = None, timeout: float = 20.0):
    """Return (status, parsed-json-or-None)."""
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "RexTweaks/1.0 (+https://github.com)")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:  # noqa: BLE001
                return resp.status, None
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read())
        except Exception:  # noqa: BLE001
            body = None
        return exc.code, body
    except (urllib.error.URLError, OSError) as exc:
        raise _HttpError(f"network error: {exc}") from exc


def _fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "RexTweaks/1.0 (+https://github.com)")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _open_browser(url: str) -> None:
    """Open the login URL in the default browser.

    os.startfile is the most reliable opener on Windows; webbrowser is the
    cross-platform fallback.
    """
    try:
        if os.name == "nt":
            os.startfile(url)  # noqa: S606
            return
    except Exception:  # noqa: BLE001
        pass
    import webbrowser
    webbrowser.open(url, new=1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def login(timeout: float = _AUTH_TIMEOUT, open_browser: bool = True,
          on_url=None) -> dict:
    """Run the browser login via the auth backend; returns the profile dict.

    ``on_url`` (if given) receives the login URL before the browser opens —
    used by the GUI so it can open the browser on the UI thread and offer a
    manual fallback link.

    Raises a ValueError/_HttpError with a user-friendly message on failure.
    """
    if not is_configured():
        raise ValueError(
            "Discord verification is not configured — set AUTH_SERVER_URL in "
            "config/app_config.py to point at the auth backend.")

    base = AUTH_SERVER_URL.rstrip("/")
    state = secrets.token_urlsafe(18)
    login_url = f"{base}/auth/discord/login?state={state}"
    status_url = f"{base}/auth/discord/status?state={state}"

    logger.info("discord: opening auth backend login URL")
    if on_url is not None:
        try:
            on_url(login_url)
        except Exception:  # noqa: BLE001
            logger.warn("discord: on_url callback failed")
    if open_browser:
        _open_browser(login_url)

    result = _poll_status(status_url, timeout)
    if result.get("status") != "success":
        raise ValueError(result.get("error")
                         or "Discord authorization was not completed.")
    payload = result.get("result") or {}
    if not payload.get("authenticated"):
        raise ValueError(payload.get("error") or "Discord did not authenticate.")

    return _store_session(payload)


def _poll_status(status_url: str, timeout: float) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, data = _http_json(status_url)
            if code == 200 and isinstance(data, dict) \
                    and data.get("status") in ("success", "error"):
                return data
        except _HttpError:
            pass  # transient; keep polling
        time.sleep(_POLL_INTERVAL)
    raise _HttpError("Authorization timed out — no response from the "
                     "auth server.")


def _store_session(payload: dict) -> dict:
    uid = str(payload.get("discord_id") or "")
    if not uid:
        raise ValueError("The auth server returned no Discord ID.")
    username = str(payload.get("username") or "user")
    member = bool(payload.get("member"))
    verified_role = bool(payload.get("verified_role"))
    prof = {
        "id": uid,
        "name": str(payload.get("display_name") or username),
        "username": username,
        "tag": username,  # modern accounts carry a 0 discriminator
        "email": str(payload.get("email") or ""),
        "verified": bool(member and verified_role),
        "verified_email": bool(payload.get("verified_email")),
        "avatar_hash": payload.get("avatar"),
        "token": "",
        "refresh_token": "",
        "expires_at": 0,
        "connected_at": time.strftime("%Y-%m-%d %H:%M"),
        "member": member,
        "verified_role": verified_role,
    }

    avatar = prof["avatar_hash"]
    if avatar:
        url = f"{DISCORD_CDN}/avatars/{uid}/{avatar}.png?size=256"
        try:
            if state_mgr.set_discord_avatar_from_bytes(_fetch_bytes(url)):
                logger.info(f"discord: cached avatar for {uid}")
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"discord: avatar download failed: {exc}")

    state_mgr.set_discord_session(prof)
    logger.info(f"discord: verified user {uid} ({username})")
    return prof


def validate_session(timeout: float = 20.0) -> bool:
    """Best-effort check that a stored identity exists.

    The backend owns all Discord tokens, so the desktop app has nothing to
    refresh — it just confirms a session is cached.
    """
    return bool(state_mgr.discord_session())


def logout() -> None:
    state_mgr.set_discord_session(None)
    state_mgr.clear_discord_avatar()
    logger.info("discord: session cleared")
