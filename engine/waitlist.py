"""Ultra Mode waitlist client (dashboard "Join the waitlist" button).

Flow per submission:

  1. validate + normalize the email,
  2. mirror every registration into a durable local store
     (``data/waitlist.json``) so a sign-up is never lost offline,
  3. sync to the waitlist API hosted on the license backend — the backend
     rejects duplicates (UNIQUE email), so repeat sign-ups are reported as
     "already on the list",
  4. if the backend is unreachable the email stays queued locally and is
     pushed next time a sync succeeds.

No credentials exist here and nothing secret ever reaches the frontend — the
API call is a plain POST without auth. All network work happens on a worker
QThread (see ui.pages.dashboard), never on the UI thread.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from config.app_config import ROOT, WAITLIST_API_URL
from maxlog import logger

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")

LOCAL_FILE = ROOT / "data" / "waitlist.json"
_HTTP_TIMEOUT = 20.0
_MAX_PENDING_PUSH = 50


def _load_entries() -> list[dict]:
    try:
        data = json.loads(LOCAL_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("emails"), list):
            return data["emails"]
    except Exception:  # noqa: BLE001 - corrupt/absent store = empty
        pass
    return []


def _save_entries(entries: list[dict]) -> None:
    try:
        LOCAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LOCAL_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"emails": entries}, indent=2),
                       encoding="utf-8")
        tmp.replace(LOCAL_FILE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("waitlist: could not persist local store: %s", exc)


def _post(email: str, source: str) -> dict | None:
    """POST one email to the backend. Returns the parsed response on success,
    or None when the backend is unreachable/not configured."""
    url = (WAITLIST_API_URL or "").strip().rstrip("/")
    if not url.startswith("https://"):
        return None
    payload = json.dumps({"email": email, "source": source}).encode("utf-8")
    request = urllib.request.Request(
        url + "/api/waitlist/join",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "MaximumTweaks/1.0"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("ok") is not True:
        return None
    return body


def _push_pending(entries: list[dict]) -> None:
    """Best-effort: sync any queued (unsynced) local emails to the backend."""
    pushed = 0
    for entry in entries:
        if entry.get("synced"):
            continue
        result = _post(entry.get("email", ""), entry.get("source", ""))
        if result is not None:
            entry["synced"] = True
            pushed += 1
        if pushed >= _MAX_PENDING_PUSH:
            break


def join(email: str, source: str = "ultra_mode") -> dict:
    """Register ``email`` (or report it is already listed).

    Returns a result dict the dashboard modal renders directly:
      * ``{"ok": True, "status": "added", ...}``  — newly added
      * ``{"ok": True, "status": "exists", ...}`` — already on the list
      * ``{"ok": True, "status": "queued", ...}`` — saved locally; backend
        unreachable, will sync later
      * ``{"ok": False, "status": "invalid", ...}`` — bad address
    """
    email = (email or "").strip().lower()
    if not email or not EMAIL_RE.fullmatch(email):
        return {"ok": False, "status": "invalid",
                "message": "That doesn't look like a valid email address."}

    entries = _load_entries()
    local = [e for e in entries if e.get("email") == email]

    # Backend first: on success it is authoritative and we can push any
    # pending queued entries too.
    backend = _post(email, source)

    if local:
        return {"ok": True, "status": "exists",
                "message": "This email is already on the list."}

    entries.append({"email": email, "source": source,
                    "joined": int(time.time()), "synced": backend is not None})
    if backend is not None:
        _push_pending(entries)
    _save_entries(entries)

    if backend is None:
        return {"ok": True, "status": "queued",
                "message": "Saved on this device — it will sync to the waitlist "
                           "when you're online."}
    return {"ok": True, "status": "added",
            "message": "You're on the list."}