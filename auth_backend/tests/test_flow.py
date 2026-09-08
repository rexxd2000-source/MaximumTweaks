"""Tests for the join + Verified-role assignment flow in auth_backend.

The Discord API is fully mocked (no live calls). Env vars are set before
``main`` is imported because it reads its config at import time.
"""
from __future__ import annotations

import os
import urllib.parse

# Config for tests — set BEFORE importing main (main reads env at import time
# and load_dotenv() will not override already-set variables).
os.environ.setdefault("DISCORD_CLIENT_ID", "client-test")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "secret-test")
os.environ.setdefault(
    "DISCORD_REDIRECT_URI", "http://127.0.0.1:8000/auth/discord/callback")
os.environ.setdefault("DISCORD_GUILD_ID", "guild-test")
os.environ.setdefault("DISCORD_ROLE_ID", "role-test")
os.environ.setdefault("DISCORD_BOT_TOKEN", "bot-token-test")

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app, follow_redirects=False)

VALID_STATE = "state-token-0123456789abcdef"  # len 28 >= 16

USER = {
    "id": "111222333444",
    "username": "alice",
    "global_name": "Alice",
    "avatar": "avatar-hash-1",
    "email": "alice@example.com",
    "verified": True,
}


@pytest.fixture(autouse=True)
def _clean_sessions():
    """Isolate the in-memory session store between tests."""
    with backend._sessions_lock:
        backend._sessions.clear()
    yield
    with backend._sessions_lock:
        backend._sessions.clear()


def _register_state(state=VALID_STATE):
    resp = client.get("/auth/discord/login", params={"state": state})
    assert resp.status_code == 302, resp.text
    return resp


def _callback(code="auth-code", state=VALID_STATE):
    return client.get("/auth/discord/callback",
                      params={"code": code, "state": state})


def _status(state=VALID_STATE):
    return client.get("/auth/discord/status", params={"state": state}).json()


def _mock_ok(monkeypatch):
    """Mock the Discord API for the happy path."""
    join_calls = {}

    def _join(uid, access_token):
        join_calls["uid"] = uid
        join_calls["token"] = access_token

    def _member(_uid):
        return {"roles": ["role-test"]}

    monkeypatch.setattr(backend, "_exchange_code",
                        lambda code: {"access_token": "access-token-x"})
    monkeypatch.setattr(backend, "_fetch_current_user", lambda token: USER)
    monkeypatch.setattr(backend, "_join_guild", _join)
    monkeypatch.setattr(backend, "_bot_get_member", _member)
    monkeypatch.setattr(backend, "_assign_verified_role", lambda _uid: None)
    return join_calls


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_redirects_with_guilds_join_scope():
    resp = _register_state()
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("https://discord.com/oauth2/authorize")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    scopes = set(qs["scope"][0].split())
    assert {"identify", "email", "guilds.join"} <= scopes
    assert "guilds.members.read" not in scopes
    assert qs["client_id"] == ["client-test"]
    assert qs["redirect_uri"] == ["http://127.0.0.1:8000/auth/discord/callback"]


def test_login_rejects_short_state():
    resp = client.get("/auth/discord/login", params={"state": "short"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Happy path: join + role assignment both succeed
# ---------------------------------------------------------------------------

def test_join_and_role_success(monkeypatch):
    join_calls = _mock_ok(monkeypatch)
    _register_state()

    resp = _callback()
    assert resp.status_code == 200

    data = _status()
    assert data["status"] == "success"
    result = data["result"]
    assert result["authenticated"] is True
    assert result["member"] is True
    assert result["verified_role"] is True
    assert result["discord_id"] == USER["id"]
    assert result["email"] == "alice@example.com"
    assert result["verified_email"] is True
    # guilds.join add received the user's OAuth token
    assert join_calls["uid"] == USER["id"]
    assert join_calls["token"] == "access-token-x"


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

def test_join_failure_is_reported(monkeypatch):
    _mock_ok(monkeypatch)
    _register_state()
    monkeypatch.setattr(
        backend, "_join_guild",
        lambda _uid, _token: (_ for _ in ()).throw(
            ValueError("Could not add you to the REX TWEAKS server "
                       "(Discord HTTP 403).")))

    _callback()
    data = _status()
    assert data["status"] == "error"
    assert "Could not add you" in data["result"]["error"]


def test_membership_confirm_failure_is_reported(monkeypatch):
    _mock_ok(monkeypatch)
    _register_state()
    monkeypatch.setattr(
        backend, "_bot_get_member",
        lambda _uid: (_ for _ in ()).throw(
            ValueError("Could not confirm your REX TWEAKS server membership "
                       "(Discord HTTP 404).")))

    _callback()
    data = _status()
    assert data["status"] == "error"
    assert "Could not confirm" in data["result"]["error"]


def test_role_assignment_failure_is_reported(monkeypatch):
    _mock_ok(monkeypatch)
    _register_state()
    monkeypatch.setattr(
        backend, "_assign_verified_role",
        lambda _uid: (_ for _ in ()).throw(
            ValueError("Could not grant you the Verified role "
                       "(Discord HTTP 403).")))

    _callback()
    data = _status()
    assert data["status"] == "error"
    assert "Could not grant" in data["result"]["error"]


def test_role_not_sticking_is_reported(monkeypatch):
    _mock_ok(monkeypatch)
    # Bot confirms the user, role PUT "succeeds", but the role is absent.
    monkeypatch.setattr(backend, "_bot_get_member",
                        lambda _uid: {"roles": ["some-other-role"]})
    _register_state()

    _callback()
    data = _status()
    assert data["status"] == "error"
    assert "Verified role could not be granted" in data["result"]["error"]


def test_user_denies_authorization_is_reported():
    _register_state()
    resp = client.get("/auth/discord/callback", params={
        "state": VALID_STATE, "error": "access_denied",
        "error_description": "You said no."})
    assert resp.status_code == 200
    data = _status()
    assert data["status"] == "error"


# ---------------------------------------------------------------------------
# Session hygiene
# ---------------------------------------------------------------------------

def test_state_is_single_use(monkeypatch):
    _mock_ok(monkeypatch)
    _register_state()

    assert _callback().status_code == 200
    # A second attempt with the same state must be rejected.
    assert _callback().status_code == 400


def test_unknown_state_status_returns_pending():
    assert _status(state="not-a-real-state-token-00000")["status"] == "pending"