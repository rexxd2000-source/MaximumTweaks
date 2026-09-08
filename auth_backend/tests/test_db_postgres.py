"""Postgres-specific tests for the license store (Neon / any PG).

Opt-in: these only run when ``TEST_DATABASE_URL`` points at a dedicated
throwaway PostgreSQL database. Set it in ``auth_backend/.env`` (gitignored)
or the shell; it is promoted to ``DATABASE_URL`` by ``test_license.py`` so
the full API suite also exercises Postgres. Never point this at a production
database - every test wipes the ``licenses`` table.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

try:
    from dotenv import load_dotenv
    load_dotenv()  # pick up TEST_DATABASE_URL from auth_backend/.env if set
except Exception:  # noqa: BLE001
    pass

from db import LicenseDB

_DSN = os.environ.get("TEST_DATABASE_URL", "").strip()
if _DSN:
    os.environ["DATABASE_URL"] = _DSN


def _is_test_db(dsn: str) -> bool:
    if not dsn:
        return False
    parts = urlparse(dsn)
    host = parts.hostname or ""
    dbname = (parts.path or "/").lstrip("/")
    return host in ("localhost", "127.0.0.1") or "test" in dbname.lower()


pytestmark = pytest.mark.skipif(
    not _DSN or not _is_test_db(_DSN),
    reason="set TEST_DATABASE_URL to a dedicated throwaway Postgres DB "
           "(e.g. a 'maximumtweaks_test' database on Neon) to run Postgres tests; "
           "it must never point at the production database",
)

DB = LicenseDB()


@pytest.fixture(autouse=True)
def _clean_db():
    with DB._lock:
        conn = DB._connect()
        try:
            DB._exec(conn, "DELETE FROM licenses")
            conn.commit()
        finally:
            conn.close()
    yield


def _key(i: int) -> str:
    return f"MAX-TEST-PG-{i:04d}"


# ---------------------------------------------------------------------------
# Engine selection / schema
# ---------------------------------------------------------------------------

def test_engine_is_postgres():
    assert DB.engine == "postgres"


def test_schema_is_idempotent():
    again = LicenseDB()
    try:
        rec = again.create(_key(0), customer="idem")
        assert rec["status"] == "unused"
    finally:
        again.revoke(_key(0), "cleanup")


def test_rows_get_identity_ids():
    first = DB.create(_key(1))
    second = DB.create(_key(2))
    assert first["id"] is not None
    assert second["id"] > first["id"]


# ---------------------------------------------------------------------------
# CRUD parity
# ---------------------------------------------------------------------------

def test_create_get_round_trip():
    rec = DB.create(_key(10), plan="monthly", customer="Alice",
                    expires_at="2099-01-01 00:00:00")
    got = DB.get(_key(10))
    assert got == rec
    assert got["plan"] == "monthly"
    assert got["customer"] == "Alice"
    assert got["expires_at"] == "2099-01-01 00:00:00"


def test_activate_binds_device():
    DB.create(_key(20), customer="Bob")
    rec = DB.activate(_key(20), "d" * 64)
    assert rec["status"] == "active"
    assert rec["device_id"] == "d" * 64
    assert rec["activation_count"] == 1


def test_revoke_unrevoke_unbind():
    DB.create(_key(30))
    DB.activate(_key(30), "d" * 64)
    DB.revoke(_key(30), "chargeback")
    assert DB.get(_key(30))["status"] == "revoked"
    DB.unrevoke(_key(30))
    assert DB.get(_key(30))["status"] == "active"
    DB.unbind(_key(30))
    rec = DB.get(_key(30))
    assert rec["status"] == "unused"
    assert rec["device_id"] is None
    assert rec["reset_count"] == 1


def test_search_and_stats():
    DB.create(_key(40), customer="Charlie", note="power user")
    DB.create(_key(41), customer="Diana")
    DB.activate(_key(40), "d" * 64)
    assert any("Charlie" in r["customer"] for r in DB.search("Charlie"))
    assert any("power" in r["note"] for r in DB.search("power"))
    stats = DB.stats()
    assert stats["total"] >= 2
    assert stats["by_status"].get("active", 0) >= 1
    assert stats["by_status"].get("unused", 0) >= 1


def test_duplicate_license_key_raises():
    import psycopg
    DB.create(_key(50))
    with pytest.raises(psycopg.errors.UniqueViolation):
        DB.create(_key(50))
