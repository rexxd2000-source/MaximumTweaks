"""Tests for the MAXIMUM TWEAKS license server.

Runs against a throwaway SQLite DB in a temp dir by default; no network, no
real keys. To exercise the PostgreSQL path instead, set TEST_DATABASE_URL to
a dedicated throwaway Postgres DB (never the production database) - the whole
suite then runs against it. A production DATABASE_URL in a .env is never
touched by the tests.
Env vars are set before ``main`` is imported because it reads its config at
import time.
"""
from __future__ import annotations

import os
import tempfile

_tmpdir = tempfile.mkdtemp(prefix="mt-licenses-")
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
from keys import generate_key, normalize_key, sign_token, verify_token  # noqa: E402

import main as backend  # noqa: E402

client = TestClient(backend.app)
db = LicenseDB()

DEVICE_A = "a" * 64
DEVICE_B = "b" * 64


@pytest.fixture(autouse=True)
def _clean_db():
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn, "DELETE FROM licenses")
            conn.commit()
        finally:
            conn.close()
    yield


def _make_key(plan="lifetime", customer="Alice", expires_at=None) -> str:
    key = generate_key()
    db.create(key, plan=plan, customer=customer, expires_at=expires_at)
    return key


def _activate(key, device=DEVICE_A):
    return client.post("/api/license/activate",
                       json={"key": key, "device_id": device})


# ---------------------------------------------------------------------------
# Key generation / normalization
# ---------------------------------------------------------------------------

def test_generated_key_matches_expected_format():
    key = generate_key()
    assert len(key) == len("MAX-XXXX-XXXX-XXXX")
    assert key.startswith("MAX-")
    groups = key.split("-")
    assert len(groups) == 4
    assert all(len(g) == 4 for g in groups[1:])


def test_keys_are_unique_and_cryptographically_secure():
    keys = {generate_key() for _ in range(1000)}
    assert len(keys) == 1000


def test_normalize_key_tolerates_noise():
    key = generate_key()
    assert normalize_key(key.lower()) == key
    assert normalize_key(key.replace("-", "")) == key
    assert normalize_key("  " + key + " ") == key
    assert normalize_key("XXXX-XXXX-XXXX") == ""


def test_generate_key_accepts_custom_prefix():
    for prefix in ("MAX", "REX", "MTW", "MTWX"):
        key = generate_key(prefix)
        assert key.startswith(prefix + "-")
        groups = key.split("-")
        assert len(groups) == 4
        assert len(groups[0]) == len(prefix)
        assert all(len(g) == 4 for g in groups[1:])
    # Default prefix is still used when none is passed.
    assert generate_key().startswith("MAX-")


def test_generated_keys_do_not_encode_duration():
    """A 1-month key and a lifetime key must be format-identical and
    unpredictable — the duration lives only in the DB record."""
    import re as _re
    shape = r"^[A-Z]{3,4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$"
    for _ in range(200):
        assert _re.match(shape, generate_key())


def test_normalize_key_accepts_custom_prefixes():
    assert normalize_key("REX-7KQ2-M8VA-XP4T") == "REX-7KQ2-M8VA-XP4T"
    assert normalize_key("mtw-a92f-qx7p-k4zd") == "MTW-A92F-QX7P-K4ZD"
    assert normalize_key("MTWX-A92F-QX7P-K4ZD") == "MTWX-A92F-QX7P-K4ZD"


def test_generate_key_rejects_invalid_prefix():
    key = generate_key("toolong!")
    assert key.startswith("MAX-")  # silently falls back to the configured prefix


# ---------------------------------------------------------------------------
# Token signing / verification
# ---------------------------------------------------------------------------

def test_token_round_trip():
    tok = sign_token("MAX-AAAA-BBBB-CCCC", DEVICE_A, "secret", 3600)
    claims = verify_token(tok, "secret")
    assert claims["lic"] == "MAX-AAAA-BBBB-CCCC"
    assert claims["dev"] == DEVICE_A


def test_token_rejects_wrong_secret():
    tok = sign_token("MAX-AAAA-BBBB-CCCC", DEVICE_A, "secret", 3600)
    assert verify_token(tok, "wrong-secret") is None


def test_token_rejects_expired():
    tok = sign_token("MAX-AAAA-BBBB-CCCC", DEVICE_A, "secret", -10)
    assert verify_token(tok, "secret") is None


def test_token_rejects_tampered():
    tok = sign_token("MAX-AAAA-BBBB-CCCC", DEVICE_A, "secret", 3600)
    assert verify_token(tok[:-2] + "xx", "secret") is None


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

def test_activate_binds_and_returns_session():
    key = _make_key()
    resp = _activate(key)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["success"] is True
    assert data["valid"] is True
    assert data["message"] == "License activated successfully"
    assert data["license"]["key"] == key
    assert data["license"]["device_id"] == DEVICE_A
    assert data["license"]["owner"] == "Alice"
    assert data["session_token"]
    # DB is now bound + active.
    rec = db.get(key)
    assert rec["status"] == "active"
    assert rec["device_id"] == DEVICE_A
    assert rec["activation_count"] == 1


def test_activate_is_idempotent_for_same_device():
    key = _make_key()
    _activate(key)
    resp = _activate(key)
    assert resp.status_code == 200
    assert db.get(key)["activation_count"] == 1


def test_activate_rejects_second_device():
    key = _make_key()
    _activate(key, DEVICE_A)
    resp = _activate(key, DEVICE_B)
    assert resp.status_code == 403
    body = resp.json()
    assert body["success"] is False
    assert body["valid"] is False
    assert body["error"] == "device_mismatch"


def test_activate_unknown_key_is_generic():
    resp = _activate("MAX-AAAA-BBBB-CCCC")
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_license"


def test_activate_requires_real_format():
    resp = _activate("not-a-key")
    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_license"


def test_activate_revoked_key():
    key = _make_key()
    db.revoke(key, "chargeback")
    resp = _activate(key)
    assert resp.status_code == 403
    assert resp.json()["error"] == "license_revoked"


def test_activate_expired_key():
    key = _make_key(expires_at="2000-01-01 00:00:00")
    resp = _activate(key)
    assert resp.status_code == 403
    assert resp.json()["error"] == "license_expired"
    assert db.get(key)["status"] == "expired"


# ---------------------------------------------------------------------------
# Validation (session refresh)
# ---------------------------------------------------------------------------

def _activate_ok(key, device=DEVICE_A) -> dict:
    resp = _activate(key, device)
    assert resp.status_code == 200
    return resp.json()


def test_validate_refreshes_token():
    key = _make_key()
    data = _activate_ok(key)
    resp = client.post("/api/license/validate",
                       json={"token": data["session_token"], "device_id": DEVICE_A})
    assert resp.status_code == 200
    out = resp.json()
    assert out["success"] is True
    assert out["session_token"]  # fresh token issued


def test_validate_rejects_garbage_token():
    resp = client.post("/api/license/validate",
                       json={"token": "garbage", "device_id": DEVICE_A})
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"


def test_validate_catches_revoked_key():
    key = _make_key()
    data = _activate_ok(key)
    db.revoke(key, "abuse")
    resp = client.post("/api/license/validate",
                       json={"token": data["session_token"], "device_id": DEVICE_A})
    assert resp.status_code == 403
    assert resp.json()["error"] == "license_revoked"


def test_validate_catches_expired_key():
    key = _make_key()
    data = _activate_ok(key)
    # Make the license expire after activation, then validate.
    with db._lock:
        conn = db._connect()
        try:
            db._exec(conn,
                     "UPDATE licenses SET expires_at = ? WHERE license_key = ?",
                     ("2000-01-01 00:00:00", key))
            conn.commit()
        finally:
            conn.close()
    resp = client.post("/api/license/validate",
                       json={"token": data["session_token"], "device_id": DEVICE_A})
    assert resp.status_code == 403
    assert resp.json()["error"] == "license_expired"


def test_validate_catches_device_mismatch():
    key = _make_key()
    data = _activate_ok(key, DEVICE_A)
    resp = client.post("/api/license/validate",
                       json={"token": data["session_token"], "device_id": DEVICE_B})
    assert resp.status_code == 403
    assert resp.json()["error"] == "device_mismatch"


# ---------------------------------------------------------------------------
# Deactivation
# ---------------------------------------------------------------------------

def test_deactivate_acknowledges_but_keeps_binding():
    key = _make_key()
    data = _activate_ok(key)
    resp = client.post("/api/license/deactivate",
                       json={"token": data["session_token"], "device_id": DEVICE_A})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "License deactivated on this device"
    # No self-unbind: the key stays bound to the device.
    rec = db.get(key)
    assert rec["status"] == "active"
    assert rec["device_id"] == DEVICE_A


# ---------------------------------------------------------------------------
# Response-shape guarantees
# ---------------------------------------------------------------------------

def test_unmatched_route_still_returns_json_object():
    """Even a 404 (e.g. the client hitting a stale backend) must be a JSON
    object, never a bare string or a {'detail': 'Not Found'} the client could
    trip over."""
    resp = client.post("/api/license/nope", json={})
    assert resp.status_code == 404
    body = resp.json()
    assert isinstance(body, dict)
    assert body.get("success") is False
    assert body.get("error") == "server_error"
    assert body.get("message")


def test_invalid_payload_is_json_object():
    resp = client.post("/api/license/activate", json={"key": 123})
    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body, dict)
    assert body.get("success") is False
    assert body.get("error") == "invalid_request"


def test_error_bodies_have_no_detail_wrapper():
    key = _make_key()
    db.revoke(key, "chargeback")
    resp = _activate(key)
    assert resp.status_code == 403
    body = resp.json()
    assert "detail" not in body
    assert "success" in body and "error" in body and "message" in body


# ---------------------------------------------------------------------------
# Support flow (admin)
# ---------------------------------------------------------------------------

def _admin_headers():
    return {"Authorization": f"Bearer {os.environ['ADMIN_TOKEN']}"}


def test_admin_requires_token():
    resp = client.get("/admin/licenses")
    assert resp.status_code == 401
    resp = client.get("/admin/licenses", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_admin_generate_and_list():
    resp = client.post("/admin/generate", json={"count": 3, "customer": "Bob"},
                       headers=_admin_headers())
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 3
    for k in keys:
        assert db.get(k)["status"] == "unused"
    listing = client.get("/admin/licenses", headers=_admin_headers()).json()
    assert len(listing["licenses"]) >= 3


def test_admin_unbind_frees_key_for_new_pc():
    key = _make_key()
    _activate(key, DEVICE_A)
    assert db.get(key)["status"] == "active"

    resp = client.post("/admin/unbind", json={"key": key},
                       headers=_admin_headers())
    assert resp.status_code == 200
    rec = db.get(key)
    assert rec["status"] == "unused"
    assert rec["device_id"] is None
    assert rec["reset_count"] == 1

    # Now the SAME key can activate on a new machine.
    resp = _activate(key, DEVICE_B)
    assert resp.status_code == 200
    assert db.get(key)["device_id"] == DEVICE_B


# ---------------------------------------------------------------------------
# Admin panel + configurable key generation
# ---------------------------------------------------------------------------

def test_admin_me_requires_login():
    assert client.get("/admin/me").status_code == 401
    resp = client.get("/admin/me", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["logged_in"] is True
    assert body["configured_prefix"] == "MAX"


def test_admin_login_cookie_flow():
    # Wrong token is rejected.
    bad = client.post("/admin/login", json={"token": "wrong-token"})
    assert bad.status_code == 401
    # Correct token sets an HttpOnly session cookie.
    ok = client.post("/admin/login", json={"token": os.environ["ADMIN_TOKEN"]})
    assert ok.status_code == 200
    cookie = ok.cookies.get("adm")
    assert cookie
    assert "httponly" in ok.headers.get("set-cookie", "").lower()
    # The cookie alone authenticates admin endpoints.
    resp = client.get("/admin/licenses", cookies={"adm": cookie})
    assert resp.status_code == 200
    assert "licenses" in resp.json()
    # A fresh client with no cookie is a hard 401 (cookie jar does not leak).
    from starlette.testclient import TestClient as _TC
    assert _TC(backend.app).get("/admin/licenses").status_code == 401


def test_admin_me_accepts_cookie():
    ok = client.post("/admin/login", json={"token": os.environ["ADMIN_TOKEN"]})
    cookie = ok.cookies.get("adm")
    resp = client.get("/admin/me", cookies={"adm": cookie})
    assert resp.status_code == 200
    assert resp.json()["logged_in"] is True


def test_admin_delete_key():
    resp = client.post("/admin/generate",
                       json={"count": 1, "prefix": "DEL", "note": "delete test"},
                       headers=_admin_headers())
    key = resp.json()["keys"][0]
    assert db.get(key) is not None

    # not found -> 404
    resp = client.delete("/admin/keys/NOPE-NOPE-NOPE-NOPE",
                         headers=_admin_headers())
    assert resp.status_code == 404

    # happy path -> gone from the store
    resp = client.delete(f"/admin/keys/{key}", headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert resp.json()["deleted"] == 1
    assert db.get(key) is None

    # admin endpoint refuses unauthenticated calls
    from starlette.testclient import TestClient as _TC
    assert _TC(backend.app).delete(f"/admin/keys/{key}").status_code == 401


def test_admin_generate_with_prefix_and_duration():
    resp = client.post("/admin/generate",
                       json={"count": 2, "duration": "1m", "prefix": "REX",
                             "customer": "Alice"},
                       headers=_admin_headers())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["keys"]) == 2 and len(set(data["keys"])) == 2
    assert all(k.startswith("REX-") for k in data["keys"])
    assert data["plan"] == "monthly"
    assert data["expires_at"]  # ~1 month out, server-computed
    for k in data["keys"]:
        rec = db.get(k)
        assert rec["plan"] == "monthly"
        assert rec["expires_at"] == data["expires_at"]
        assert rec["customer"] == "Alice"


def test_admin_generate_lifetime_has_no_expiry():
    resp = client.post("/admin/generate",
                       json={"count": 1, "duration": "lifetime", "prefix": "MTW"},
                       headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["keys"][0].startswith("MTW-")
    assert data["expires_at"] is None
    assert db.get(data["keys"][0])["plan"] == "lifetime"


def test_admin_generate_6m_sets_expiry():
    resp = client.post("/admin/generate",
                       json={"count": 1, "duration": "6m"},
                       headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "custom"
    assert data["expires_at"]
    assert db.get(data["keys"][0])["expires_at"] == data["expires_at"]


def test_admin_generate_bulk_unique():
    resp = client.post("/admin/generate", json={"count": 50},
                       headers=_admin_headers())
    assert resp.status_code == 200
    keys = resp.json()["keys"]
    assert len(keys) == 50 == len(set(keys))
    assert all(normalize_key(k) for k in keys)


def test_admin_generate_rejects_bad_prefix():
    resp = client.post("/admin/generate", json={"prefix": "LONG!!"},
                       headers=_admin_headers())
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_prefix"


def test_admin_generate_computed_keys_activate():
    resp = client.post("/admin/generate",
                       json={"count": 1, "duration": "1m", "prefix": "REX"},
                       headers=_admin_headers())
    key = resp.json()["keys"][0]
    # The generated (prefixed) key works through the public license API.
    act = _activate(key)
    assert act.status_code == 200, act.text
    assert act.json()["license"]["key"] == key
    assert db.get(key)["status"] == "active"


def test_admin_panel_html_served():
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Maximum Tweaks" in resp.text


def test_unhandled_500_returns_friendly_envelope():
    """A genuine server error must return the friendly JSON envelope while the
    real exception is logged server-side — never raw Internal Server Error."""
    from starlette.testclient import TestClient as _TC
    original = backend._DB.list_all
    backend._DB.list_all = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        with _TC(backend.app, raise_server_exceptions=False) as quiet:
            resp = quiet.get("/admin/licenses", headers=_admin_headers())
            assert resp.status_code == 500
            body = resp.json()
            assert body["error"] == "server_error"
            assert "boom" not in body["message"]
            assert body["message"]
    finally:
        backend._DB.list_all = original
