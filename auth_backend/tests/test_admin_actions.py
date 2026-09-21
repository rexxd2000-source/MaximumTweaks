"""Tests for the admin hard-ban, timeout (suspend), and inspect actions.

Covers the /admin/ban, /admin/unban, /admin/suspend, /admin/unsuspend
endpoints plus how a suspension/ban ripples through the customer-facing
activate / validate / checkin flows, and the /admin/keys/{key}/inspect
sheet. Runs against the same throwaway SQLite DB used by test_license.py.
"""
from __future__ import annotations

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="mt-admin-actions-")
os.environ["LICENSE_DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["LICENSE_SECRET"] = "test-secret-not-for-production"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["SESSION_TTL_HOURS"] = "2"
os.environ["OFFLINE_GRACE_HOURS"] = "24"

try:
    from dotenv import load_dotenv
    load_dotenv()  # pick up TEST_DATABASE_URL from auth_backend/.env if set
except Exception:  # noqa: BLE001
    pass

if os.environ.get("TEST_DATABASE_URL", "").strip():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"].strip()

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

from db import LicenseDB  # noqa: E402
from keys import generate_key, sign_token  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app)
db = LicenseDB()

DEVICE_A = "a" * 64
DEVICE_B = "b" * 64

PAST = "2020-01-01 00:00:00"


@pytest.fixture(autouse=True)
def _clean_db():
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn, "DELETE FROM licenses")
            db._exec(conn, "DELETE FROM key_activity")
            db._exec(conn, "DELETE FROM key_blocked")
            db._exec(conn, "DELETE FROM key_log")
            conn.commit()
        finally:
            conn.close()
    yield


def _admin_headers():
    return {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}


def _make_key(customer="Alice", max_pcs=1) -> str:
    key = generate_key()
    db.create(key, plan="life", customer=customer, max_pcs=max_pcs)
    return key


def _activate(key, device=DEVICE_A):
    return client.post("/api/license/activate",
                       json={"key": key, "device_id": device})


def _checkin(key, device=DEVICE_A, pc_name="Test PC"):
    return client.post("/api/license/checkin",
                       json={"key": key, "device_id": device, "pc_name": pc_name})


def _events(key):
    return db.logs(key)


# ---------------------------------------------------------------------------
# Hard ban / unban
# ---------------------------------------------------------------------------

def test_ban_revokes_key_and_blocks_pcs():
    key = _make_key(max_pcs=2)
    _activate(key, DEVICE_A)
    _checkin(key, DEVICE_A)
    _checkin(key, DEVICE_B)  # second PC joins via check-in (within max_pcs)

    r = client.post("/admin/ban", json={"key": key, "reason": "chargeback"},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["revoked_reason"] == "banned"

    rec = db.get(key)
    assert rec["status"] == "revoked"
    assert rec["revoked_reason"] == "banned"

    # Every PC the key used is on record as blocked.
    with db._lock:
        conn = db._connect()
        try:
            rows = db._exec(
                conn, "SELECT pc_hwid, reason FROM key_blocked"
                " WHERE license_key = ?", (key,)).fetchall()
        finally:
            conn.close()
    assert {r["pc_hwid"] for r in rows} == {DEVICE_A, DEVICE_B}
    assert all(r["reason"] == "banned" for r in rows)

    # The banned event is in the key log.
    kinds = [e["event"] for e in _events(key)]
    assert "banned" in kinds

    # A banned key refuses activation and check-in.
    got = _activate(key).json()
    assert got["error"] == "license_revoked"
    got = _checkin(key).json()
    assert got["error"] == "license_revoked"


def test_ban_unknown_key_is_404():
    r = client.post("/admin/ban", json={"key": "NOPE-NOPE-NOPE-NOPE", "reason": ""},
                    headers=_admin_headers())
    assert r.status_code == 404


def test_unban_restores_key():
    key = _make_key()
    _activate(key, DEVICE_A)
    client.post("/admin/ban", json={"key": key, "reason": ""},
                headers=_admin_headers())

    r = client.post("/admin/unban", json={"key": key}, headers=_admin_headers())
    assert r.status_code == 200, r.text
    assert db.get(key)["status"] == "active"
    assert db.get(key)["revoked_reason"] == ""

    got = _activate(key).json()
    assert got.get("success") is True
    kinds = [e["event"] for e in _events(key)]
    assert "unbanned" in kinds


def test_ban_requires_admin_auth():
    key = _make_key()
    r = client.post("/admin/ban", json={"key": key, "reason": ""})
    assert r.status_code == 401
    assert db.get(key)["status"] == "unused"


# ---------------------------------------------------------------------------
# Suspend (timeout) / unsuspend
# ---------------------------------------------------------------------------

def test_suspend_refuses_activate_validate_and_checkin():
    key = _make_key()
    _activate(key, DEVICE_A)

    r = client.post("/admin/suspend", json={"key": key, "hours": 6},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    assert r.json()["suspended_until"]
    assert db.get(key)["suspended_until"] is not None
    assert "suspended" in [e["event"] for e in _events(key)]

    got = _activate(key).json()
    assert got["error"] == "license_suspended"
    got = _checkin(key).json()
    assert got["error"] == "license_suspended"

    token = sign_token(key, DEVICE_A, os.environ["LICENSE_SECRET"], 3600)
    got = client.post("/api/license/validate",
                      json={"token": token, "device_id": DEVICE_A}).json()
    assert got["error"] == "license_suspended"


def test_suspend_rejects_bad_hours():
    key = _make_key()
    for hours in (0, -3, 200):
        r = client.post("/admin/suspend", json={"key": key, "hours": hours},
                        headers=_admin_headers())
        assert r.status_code == 400, hours
    # A non-numeric value fails Pydantic validation before the endpoint.
    r = client.post("/admin/suspend", json={"key": key, "hours": "abc"},
                    headers=_admin_headers())
    assert r.status_code == 422


def test_unsuspend_restores_key():
    key = _make_key()
    _activate(key, DEVICE_A)
    client.post("/admin/suspend", json={"key": key, "hours": 6},
                headers=_admin_headers())

    r = client.post("/admin/unsuspend", json={"key": key},
                    headers=_admin_headers())
    assert r.status_code == 200, r.text
    assert db.get(key)["suspended_until"] is None

    got = _activate(key).json()
    assert got.get("success") is True
    assert "unsuspended" in [e["event"] for e in _events(key)]


def test_suspensions_resume_automatically_when_past_due():
    key = _make_key()
    _activate(key, DEVICE_A)
    db.suspend(key, PAST)

    # Activation past-due clears the suspension and goes through.
    got = _activate(key).json()
    assert got.get("success") is True
    assert db.get(key)["suspended_until"] is None
    assert "auto-resumed" in [e["detail"] for e in _events(key)]


def test_checkin_auto_resumes_past_due_suspension():
    key = _make_key()
    _activate(key, DEVICE_A)
    db.suspend(key, PAST)

    got = _checkin(key)
    assert got.status_code == 200, got.text
    assert got.json()["success"] is True
    assert db.get(key)["suspended_until"] is None
    assert "auto-resumed" in [e["detail"] for e in _events(key)]


# ---------------------------------------------------------------------------
# Keys list + inspect
# ---------------------------------------------------------------------------

def test_keys_list_carries_suspended_and_revoked_fields():
    active = _make_key("Active Buddy")
    banned = _make_key("Naughty")
    db.ban(banned, "chargeback")
    db.suspend(active, "2099-01-01 00:00:00")

    keys = client.get("/admin/keys", headers=_admin_headers()).json()["keys"]
    by = {k["key"]: k for k in keys}
    assert by[banned]["status"] == "revoked"
    assert by[banned]["revoked_reason"] == "banned"
    assert by[active]["suspended_until"] == "2099-01-01 00:00:00"
    assert by[active]["suspended_at"]


def test_keys_list_requires_admin():
    assert client.get("/admin/keys").status_code == 401


def test_inspect_shape_and_timeline():
    key = _make_key("Inspect Me")
    _activate(key, DEVICE_A)
    _checkin(key, DEVICE_A, "Gaming Rig")
    client.post("/admin/suspend", json={"key": key, "hours": 12},
                headers=_admin_headers())
    client.post("/admin/unsuspend", json={"key": key},
                headers=_admin_headers())

    r = client.get(f"/admin/keys/{key}/inspect", headers=_admin_headers())
    assert r.status_code == 200, r.text
    info = r.json()["inspect"]
    assert info["meta"]["license_key"] == key
    assert info["meta"]["customer"] == "Inspect Me"
    assert {p["pc_hwid"] for p in info["pcs"]} == {DEVICE_A}
    assert info["pcs"][0]["pc_name"] == "Gaming Rig"
    assert info["pcs"][0]["days_on"] >= 1

    kinds = [e["event"] for e in info["events"]]
    assert "activated" in kinds
    assert "suspended" in kinds
    assert "unsuspended" in kinds
    # Log is newest-first, so the suspends happened before the resume.
    assert kinds.index("suspended") > kinds.index("unsuspended")


def test_inspect_banned_key_lists_blocked_pcs():
    key = _make_key()
    _activate(key, DEVICE_A)
    _checkin(key, DEVICE_A)  # check-in history is what ban blocks
    client.post("/admin/ban", json={"key": key, "reason": "refund"},
                headers=_admin_headers())

    info = client.get(f"/admin/keys/{key}/inspect",
                      headers=_admin_headers()).json()["inspect"]
    assert info["meta"]["revoked_reason"] == "banned"
    assert any(b["reason"] == "banned" and b["pc_hwid"] == DEVICE_A
               for b in info["blocked"])
    assert "banned" in [e["event"] for e in info["events"]]


def test_inspect_unknown_key_is_404():
    r = client.get("/admin/keys/NOPE-NOPE-NOPE-NOPE/inspect",
                   headers=_admin_headers())
    assert r.status_code == 404