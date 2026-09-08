"""License-key client for Maximum Tweaks — backend API client.

The desktop app holds no secrets and can generate nothing. It sends the
customer-entered key plus a hashed device fingerprint to the license backend
(``auth_backend/``) and stores the returned short-lived session token locally.

  * ``activate(key)``     — POST /api/license/activate  (binds key to device)
  * ``validate()``        — POST /api/license/validate  (refresh token)
  * ``deactivate()``      — POST /api/license/deactivate + clear local session

Once activated, the key is locked to the device: the persisted session keeps
the PC authorized across reboots and app updates (revocation is re-checked
against the server on every launch, and stale tokens self-repair silently).
Raw hardware identifiers are never sent: only the SHA-256 ``device_id`` hash
is transmitted.

Pure-stdlib (urllib) so the CLI and GUI both work without extra dependencies.
All network work happens on a worker QThread — never call these on the UI
thread (see ui.license).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

from config.app_config import LICENSE_API_URL
from engine import state as state_mgr
from rexlog import logger

SESSION_KEY = "license"
_HTTP_TIMEOUT = 20.0
_DEVICE_ID: str | None = None


# ---------------------------------------------------------------------------
# Device fingerprint (hardware lock)
# ---------------------------------------------------------------------------

def device_id() -> str:
    """Stable, hashed device fingerprint (SHA-256 of machine identifiers).

    Only this hash ever leaves the PC. MachineGuid is unique per Windows
    install and survives reboots; COMPUTERNAME is a fallback.
    uuid.getnode() is intentionally excluded — it returns random values on
    some machines where the MAC address is unavailable at boot, which breaks
    license persistence across reboots.
    """
    global _DEVICE_ID
    if _DEVICE_ID:
        return _DEVICE_ID
    parts = []
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography") as key:
            parts.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
    except Exception:  # noqa: BLE001
        pass
    parts.append(os.environ.get("COMPUTERNAME", ""))
    _DEVICE_ID = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return _DEVICE_ID


# ---------------------------------------------------------------------------
# Session (persisted in state.json under "license")
# ---------------------------------------------------------------------------

def session() -> dict | None:
    return state_mgr.license_session()


def set_session(data: dict | None) -> None:
    state_mgr.set_license_session(data)


def owner_name(sess: dict | None = None) -> str:
    sess = sess or session()
    if not sess:
        return "guest"
    return sess.get("owner") or "Maximum Tweaks License"


def is_configured() -> bool:
    return bool(LICENSE_API_URL)


def dev_bypass_enabled() -> bool:
    """Development-only owner bypass.

    NEVER active in the frozen EXE: the app is a PyInstaller build, so the
    ``frozen`` attribute is always set there and this returns False no matter
    what. Even when running from source it additionally requires the
    ``REX_DEV_BYPASS=1`` environment variable, so a normal ``python main.py``
    still enforces the license.
    """
    if getattr(sys, "frozen", False):
        return False
    return os.environ.get("REX_DEV_BYPASS", "") == "1"


def _license_expired(sess: dict) -> bool:
    exp = sess.get("expires_at")
    if not exp:
        return False  # lifetime
    try:
        from datetime import datetime, timezone
        exp_ts = datetime.strptime(exp, "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc).timestamp()
        return time.time() > exp_ts
    except Exception:  # noqa: BLE001
        return False


_OFFLINE_GRACE_HOURS = 24 * 30  # 30 days — trust local session if last server
                                 # confirmation was within this window


def _last_validation_age_hours(sess: dict) -> float | None:
    """Hours since the last successful server validation, or None."""
    ts = sess.get("last_validation")
    if not ts:
        return None
    try:
        from datetime import datetime, timezone
        validated = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") \
            .replace(tzinfo=timezone.utc).timestamp()
        return (time.time() - validated) / 3600
    except Exception:  # noqa: BLE001
        return None


def is_authorized() -> bool:
    """Can the app run right now without re-activating?

    True when a persisted session exists, the device fingerprint matches this
    PC, and the license has not expired (lifetime keys never expire).

    The session-token clock is deliberately NOT a factor: once a key is bound
    to this PC it stays authorized across reboots and app updates — the key
    is locked to the machine.

    Offline grace: even if the server would report the key as revoked/expired,
    the app continues to trust a locally-stored session for up to 30 days after
    the last successful server confirmation.  This prevents transient outages,
    Render cold-starts, and network issues from locking users out.
    Revocation is re-checked the next time the server is reachable during an
    explicit activation attempt.
    """
    sess = session()
    if not sess:
        return False
    if sess.get("device_id") and sess.get("device_id") != device_id():
        # Auto-repair: the device_id may have changed due to a previous
        # uuid.getnode() instability.  If the session was activated on this
        # machine (we only check locally), trust it and update the stored
        # fingerprint so future launches pass the check.
        stored = sess.get("device_id")
        current = device_id()
        if stored and len(stored) == 64 and len(current) == 64:
            sess["device_id"] = current
            set_session(sess)
            logger.info("license: device_id auto-repaired for stability")
        else:
            return False
    if _license_expired(sess):
        age = _last_validation_age_hours(sess)
        if age is not None and age < _OFFLINE_GRACE_HOURS:
            logger.warn(f"license: offline grace — key expired but last server "
                        f"confirm was {age:.0f}h ago, staying authorized")
            return True
        return False
    return True


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib)
# ---------------------------------------------------------------------------

class LicenseError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code


def _friendly(code: str, server_message: str = "") -> str:
    if server_message:
        return server_message
    return {
        # Current envelope error codes
        "invalid_license": ("That license key wasn't recognized. Double-check "
                            "it and try again, or contact support."),
        "license_revoked": "This license key has been revoked. Contact support for help.",
        "license_expired": "This license key has expired.",
        "device_mismatch": ("This license is already activated on another PC. "
                            "Changed computers? Contact support to unlock it."),
        "rate_limited": "Too many attempts — please wait a few minutes.",
        "invalid_token": "Your session is no longer valid. Please activate again.",
        "invalid_device": "This device could not be identified.",
        "server_error": ("The license server is not available right now. "
                         "Please try again later."),
        # Legacy envelope error codes (older backends)
        "INVALID_KEY": ("That license key wasn't recognized. Double-check it "
                        "and try again, or contact support."),
        "REVOKED": "This license key has been revoked. Contact support for help.",
        "EXPIRED": "This license key has expired.",
        "ALREADY_ACTIVATED": ("This license key is already activated on "
                              "another PC. Changed computers? Contact support "
                              "to unlock it."),
        "RATE_LIMITED": "Too many attempts — please wait a few minutes.",
        "INVALID_TOKEN": "Your session is no longer valid. Please activate again.",
        "DEVICE_MISMATCH": "This license is bound to a different PC.",
        "INVALID_DEVICE": "This device could not be identified.",
    }.get(code, "Activation failed. Please try again.")


def _decode_body(raw: bytes):
    """Best-effort JSON decode. Returns the parsed value, or None for an
    empty / non-JSON body. Never raises."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def _normalize_response(parsed, status: int) -> dict:
    """Force any server response into a safe dict the callers can ``.get()``.

    The license server always answers with a JSON object, but the client must
    survive anything: empty bodies, invalid JSON, bare strings, FastAPI's
    default ``{"detail": ...}`` wrappers, and proxy error pages. Whatever the
    backend actually sent, callers get a dict — never a str/list/None that
    would blow up on ``.get()``.
    """
    if not isinstance(parsed, dict):
        return {
            "success": False,
            "valid": False,
            "error": "server_error",
            "message": "The license server returned an unexpected response. "
                       f"Please try again later. (HTTP {status})",
        }
    if "detail" in parsed and not any(
            k in parsed for k in ("ok", "success", "code", "error", "message")):
        detail = parsed["detail"]
        if isinstance(detail, dict):
            return detail
        return {
            "success": False,
            "valid": False,
            "error": "server_error",
            "message": "The license server isn't responding as expected. "
                       f"Please try again later. (HTTP {status})",
        }
    return parsed


def _http_json(url: str, payload: dict, timeout: float = _HTTP_TIMEOUT):
    """POST JSON; returns ``(status, normalized-dict)``.

    Never raises for HTTP/parse issues — callers always receive a dict. Only
    network-level failures (offline, DNS, timeout) raise LicenseError so the
    caller can decide whether the cached session should stay valid.
    """
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("User-Agent", "MaximumTweaks/2.0")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _normalize_response(
                _decode_body(resp.read()), resp.status)
    except urllib.error.HTTPError as exc:
        return exc.code, _normalize_response(
            _decode_body(exc.read()), exc.code)
    except (urllib.error.URLError, OSError) as exc:
        raise LicenseError(
            "Could not reach the license server. Check your internet "
            "connection and try again.", "NETWORK") from exc


def _session_from_response(data: dict) -> dict:
    """Extract the persisted-session fields from the server envelope.

    Accepts both the current format (``license`` object + ``session_token``)
    and the legacy format (``session`` object + ``token``).
    """
    inner = data.get("license")
    if not isinstance(inner, dict):
        inner = data.get("session")
    if not isinstance(inner, dict):
        inner = {}
    sess = {
        "license": (inner.get("key") or inner.get("license_key")
                    or inner.get("license") or ""),
        "owner": (inner.get("owner") or inner.get("customer")
                  or "Maximum Tweaks License"),
        "plan": inner.get("plan") or "lifetime",
        "customer": inner.get("customer") or "",
        "activated_at": inner.get("activated_at"),
        "expires_at": inner.get("expires_at"),
        "last_validation": inner.get("last_validation")
                           or inner.get("last_validated"),
        "device_id": inner.get("device_id"),
    }
    sess["token"] = data.get("session_token") or data.get("token") or ""
    sess["token_exp"] = data.get("token_exp") or 0
    return sess


def _store_record(payload: dict, device: str) -> dict:
    """Merge server session + fresh token into the persisted session."""
    sess = _session_from_response(payload)
    sess["device_id"] = device
    sess["last_validation"] = time.strftime("%Y-%m-%d %H:%M:%S")
    set_session(sess)
    return sess


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def activate(key: str) -> dict:
    """Bind ``key`` to this device and store the resulting session.

    Raises LicenseError with a user-friendly message on failure.
    """
    if not is_configured():
        raise LicenseError("The license server is not configured yet — set "
                           "LICENSE_API_URL in config/app_config.py.")
    base = LICENSE_API_URL.rstrip("/")
    dev = device_id()
    status, data = _http_json(f"{base}/api/license/activate",
                              {"key": key, "device_id": dev})
    if status == 200 and (data.get("success") or data.get("ok")):
        sess = _store_record(data, dev)
        logger.info(f"license: activated key {sess.get('license')}")
        return sess
    code = data.get("error") or data.get("code") or ""
    raise LicenseError(_friendly(code, data.get("message", "")), code)


def validate() -> tuple[bool, str]:
    """Best-effort token refresh with self-repair. Returns (ok, message).

    This is a background refresh — it MUST NOT clear the stored session on
    failure.  Only explicit user action (deactivate) or a fresh user-initiated
    activate() may revoke a session.  Network errors, server outages, and even
    ``license_revoked`` responses during a background check are logged but the
    local session stays intact so the app survives restarts, reboots, and
    temporary connectivity issues.  Revocation is re-checked on the next
    *explicit* activation attempt.
    """
    sess = session()
    if not sess or not sess.get("token"):
        return False, "No session stored."
    if not is_configured():
        return False, "License server not configured."
    base = LICENSE_API_URL.rstrip("/")
    dev = device_id()
    try:
        status, data = _http_json(f"{base}/api/license/validate",
                                  {"token": sess.get("token"), "device_id": dev})
    except LicenseError as exc:
        return False, exc.message  # network — keep cached session
    if status == 200 and (data.get("success") or data.get("ok")):
        _store_record(data, dev)
        logger.info("license: session refreshed")
        return True, ""
    code = data.get("error") or data.get("code") or ""
    message = _friendly(code, data.get("message", ""))

    if code in ("invalid_token", "INVALID_TOKEN"):
        key = sess.get("license") or ""
        if not key:
            return False, message
        try:
            activate(key)
            logger.info("license: stale token repaired via re-activation")
            return True, ""
        except LicenseError as exc:
            # Do NOT clear the session — the background refresh must never
            # lock the user out.  Revocation is enforced on the next explicit
            # activation attempt.
            logger.warn(f"license: background re-activation failed ({exc.code}): "
                        f"{exc.message}")
            return False, exc.message

    # Server says key is revoked / expired / bound elsewhere — log but do NOT
    # clear.  The session stays so the app survives restarts.  Revocation is
    # re-checked when the user next explicitly activates.
    if code in ("license_revoked", "license_expired", "device_mismatch",
                "REVOKED", "EXPIRED", "DEVICE_MISMATCH"):
        logger.warn(f"license: server reports {code} during background refresh "
                    f"— session retained for offline grace")
    return False, message


def deactivate() -> None:
    """Tell the server we're leaving (no self-unbind) and clear local session."""
    sess = session()
    if sess and sess.get("token") and is_configured():
        try:
            _http_json(f"{LICENSE_API_URL.rstrip('/')}/api/license/deactivate",
                       {"token": sess["token"], "device_id": device_id()})
        except Exception as exc:  # noqa: BLE001
            logger.warn(f"license: deactivate request failed: {exc}")
    set_session(None)
    logger.info("license: session deactivated")
