"""Tests for the Discord OAuth admin login.

Covers the desktop flow: /admin/discord/start -> browser authorize ->
/admin/discord/callback -> /admin/discord/poll (which delivers the admin
session cookie). Discord API calls are monkeypatched so nothing ever leaves
the test process, and never touches the license tables.
"""
from __future__ import annotations

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="mt-discord-")
os.environ["LICENSE_DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["LICENSE_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["SESSION_TTL_HOURS"] = "2"
os.environ["OFFLINE_GRACE_HOURS"] = "24"
os.environ["DISCORD_CLIENT_ID"] = "test-client-id"
os.environ["DISCORD_CLIENT_SECRET"] = "test-client-secret"
os.environ["DISCORD_ADMIN_IDS"] = "111222333,444555666"
os.environ["DISCORD_ADMIN_NAMES"] = "111222333:Reaper,444555666:Rex"

try:
    from dotenv import load_dotenv
    load_dotenv()  # pick up TEST_DATABASE_URL from auth_backend/.env if set
except Exception:  # noqa: BLE001
    pass

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app)

REAPER_UID = "111222333"
REX_UID = "444555666"


@pytest.fixture(autouse=True)
def _clean_discord_states():
    """Fresh OAuth request store before every test (no DB rows involved)."""
    backend._DISCORD_STATES.clear()
    yield
    backend._DISCORD_STATES.clear()


def _start() -> dict:
    r = client.post("/admin/discord/start")
    assert r.status_code == 200
    return r.json()


# ---------------------------------------------------------------------------
# Probe + start
# ---------------------------------------------------------------------------

def test_probe_reports_discord_auth_mode():
    body = client.get("/admin").json()
    assert body["auth"] == "discord"
    assert body["admins"] == ["Reaper", "Rex"]


def test_start_returns_discord_authorize_url():
    body = _start()
    assert body["ok"] is True
    assert body["state"]
    assert "https://discord.com/oauth2/authorize" in body["url"]
    assert "client_id=test-client-id" in body["url"]
    assert "response_type=code" in body["url"]
    assert "scope=identify" in body["url"]
    assert f"state={body['state']}" in body["url"]


def test_start_disabled_without_credentials(monkeypatch):
    monkeypatch.setenv("DISCORD_ADMIN_IDS", "")
    r = client.post("/admin/discord/start")
    assert r.status_code == 403
    assert r.json()["error"] == "discord_disabled"


# ---------------------------------------------------------------------------
# Full success flow: start -> callback -> poll -> cookie -> /admin/me
# ---------------------------------------------------------------------------

def test_successful_login_sets_admin_cookie(monkeypatch):
    monkeypatch.setattr(
        backend, "_discord_exchange",
        lambda code, uri: {"access_token": "fake-token"})
    monkeypatch.setattr(
        backend, "_discord_user",
        lambda tok: {"id": REAPER_UID, "username": "Reaper"})

    state = _start()["state"]
    assert client.get(f"/admin/discord/poll/{state}").json()["status"] == "waiting"

    r = client.get(f"/admin/discord/callback?code=abc&state={state}")
    assert r.status_code == 200
    assert "signed in" in r.text.lower()
    # The browser/wrapper flow must get the cookie on the callback itself
    # (it auto-redirects to / after 1400ms), not only via the desktop poll.
    assert "adm=" in r.headers.get("set-cookie", "")

    poll = client.get(f"/admin/discord/poll/{state}")
    body = poll.json()
    assert body["status"] == "ok"
    assert body["user"] == "Reaper"
    assert "adm=" in poll.headers.get("set-cookie", "")

    # TestClient persists the cookie, so the next /admin/* call is authorized.
    me = client.get("/admin/me")
    assert me.status_code == 200
    assert me.json()["logged_in"] is True

    # Full admin access works with the Discord-issued session.
    keys = client.get("/admin/keys")
    assert keys.status_code == 200
    assert keys.json()["ok"] is True


def test_callback_without_code_is_denied(monkeypatch):
    monkeypatch.setattr(
        backend, "_discord_exchange",
        lambda code, uri: {"access_token": "fake-token"})
    monkeypatch.setattr(
        backend, "_discord_user",
        lambda tok: {"id": REAPER_UID, "username": "Reaper"})

    state = _start()["state"]
    r = client.get(f"/admin/discord/callback?state={state}")
    assert "cancelled" in r.text.lower()
    assert client.get(f"/admin/discord/poll/{state}").json()["status"] == "denied"


def test_non_admin_is_denied(monkeypatch):
    monkeypatch.setattr(
        backend, "_discord_exchange",
        lambda code, uri: {"access_token": "fake-token"})
    monkeypatch.setattr(
        backend, "_discord_user",
        lambda tok: {"id": "999999999", "username": "Intruder"})

    state = _start()["state"]
    r = client.get(f"/admin/discord/callback?code=abc&state={state}")
    assert "Access denied" in r.text
    assert client.get(f"/admin/discord/poll/{state}").json()["status"] == "denied"


def test_second_admin_user_also_allowed(monkeypatch):
    monkeypatch.setattr(
        backend, "_discord_exchange",
        lambda code, uri: {"access_token": "fake-token"})
    monkeypatch.setattr(
        backend, "_discord_user",
        lambda tok: {"id": REX_UID, "username": "Rex"})

    state = _start()["state"]
    client.get(f"/admin/discord/callback?code=abc&state={state}")
    body = client.get(f"/admin/discord/poll/{state}").json()
    assert body["status"] == "ok"
    assert body["user"] == "Rex"


def test_exchange_failure_is_denied(monkeypatch):
    monkeypatch.setattr(backend, "_discord_exchange", lambda code, uri: {})
    state = _start()["state"]
    r = client.get(f"/admin/discord/callback?code=abc&state={state}")
    assert "could not complete" in r.text.lower()
    assert client.get(f"/admin/discord/poll/{state}").json()["status"] == "denied"


# ---------------------------------------------------------------------------
# Expired / unknown states
# ---------------------------------------------------------------------------

def test_expired_state_polls_expired():
    state = _start()["state"]
    backend._discord_state_set(state, exp=0)
    assert client.get(f"/admin/discord/poll/{state}").json()["status"] == "expired"
    r = client.get(f"/admin/discord/callback?code=abc&state={state}")
    assert "expired" in r.text.lower()


def test_unknown_state_is_expired():
    assert client.get("/admin/discord/poll/does-not-exist").json()["status"] == "expired"
    r = client.get("/admin/discord/callback?code=abc&state=does-not-exist")
    assert "expired" in r.text.lower()