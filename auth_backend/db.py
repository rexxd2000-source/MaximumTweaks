"""License database for the MAXIMUM TWEAKS license server.

SQLite-backed, server-side only. The desktop app never touches this store —
it only ever talks to the HTTP API in ``main.py``. On Render you should point
``LICENSE_DB_PATH`` at a Persistent Disk (see README) so licenses survive
deploys/restarts; locally it defaults to ``auth_backend/licenses.db``.

All times are UTC in ``YYYY-MM-DD HH:MM:SS`` strings (same format the old
Discord backend used). ``expires_at`` is NULL for lifetime licenses.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "licenses.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key      TEXT    NOT NULL UNIQUE,
    status           TEXT    NOT NULL DEFAULT 'unused',   -- unused|active|revoked|expired
    plan             TEXT    NOT NULL DEFAULT 'lifetime', -- lifetime|monthly|yearly|custom
    customer         TEXT    NOT NULL DEFAULT '',
    note             TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    expires_at       TEXT    DEFAULT NULL,                -- NULL = lifetime
    activated_at     TEXT    DEFAULT NULL,
    device_id        TEXT    DEFAULT NULL,                -- hashed device fingerprint
    activation_count INTEGER NOT NULL DEFAULT 0,
    last_validated   TEXT    DEFAULT NULL,
    revoked_at       TEXT    DEFAULT NULL,
    revoked_reason   TEXT    NOT NULL DEFAULT '',
    reset_count      INTEGER NOT NULL DEFAULT 0           -- support unbinds (PC change)
);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_db_path() -> str:
    override = os.environ.get("LICENSE_DB_PATH", "").strip()
    if override:
        return override
    return str(DEFAULT_DB_PATH)


class LicenseDB:
    """Thread-safe SQLite store for license records."""

    def __init__(self, path: str | None = None):
        self._path = path or _parse_db_path()
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def get(self, license_key: str) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM licenses WHERE license_key = ?",
                    (license_key,)).fetchone()
                return self._row_to_dict(row)
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Writes (admin + activation flow)
    # ------------------------------------------------------------------

    def create(self, license_key: str, plan: str = "lifetime",
               customer: str = "", note: str = "",
               expires_at: str | None = None) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO licenses (license_key, status, plan, customer,"
                    " note, created_at, expires_at) VALUES (?, 'unused', ?, ?, ?, ?, ?)",
                    (license_key, plan, customer, note, _utc_now(), expires_at))
                conn.commit()
            finally:
                conn.close()
        rec = self.get(license_key)
        if rec is None:  # pragma: no cover
            raise RuntimeError("license record was not created")
        return rec

    def activate(self, license_key: str, device_id: str) -> dict:
        """Bind an unused license to a device and mark it active.

        Returns the updated record. Only ``unused`` licenses can be activated
        through this path (re-activation of an already-bound key is handled by
        the API layer so the caller can return the right error code).
        """
        now = _utc_now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE licenses SET status = 'active', device_id = ?,"
                    " activated_at = COALESCE(activated_at, ?),"
                    " activation_count = activation_count + 1,"
                    " last_validated = ?, revoked_at = NULL,"
                    " revoked_reason = '' WHERE license_key = ?",
                    (device_id, now, now, license_key))
                conn.commit()
            finally:
                conn.close()
        return self.get(license_key)

    def touch_validation(self, license_key: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE licenses SET last_validated = ? WHERE license_key = ?",
                    (_utc_now(), license_key))
                conn.commit()
            finally:
                conn.close()

    def mark_expired(self, license_key: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE licenses SET status = 'expired' WHERE license_key = ?",
                    (license_key,))
                conn.commit()
            finally:
                conn.close()

    def revoke(self, license_key: str, reason: str = "") -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE licenses SET status = 'revoked', revoked_at = ?,"
                    " revoked_reason = ? WHERE license_key = ?",
                    (_utc_now(), reason, license_key))
                conn.commit()
            finally:
                conn.close()
        return self.get(license_key)

    def unrevoke(self, license_key: str) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE licenses SET status = 'active', revoked_at = NULL,"
                    " revoked_reason = '' WHERE license_key = ?",
                    (license_key,))
                conn.commit()
            finally:
                conn.close()
        return self.get(license_key)

    def unbind(self, license_key: str) -> dict | None:
        """Support action for a PC change: unbind the device and free the key.

        The license keeps its activation_count history; status returns to
        ``unused`` so the same key can be activated on the new machine. This
        is the ONLY supported way to change hardware (never client-side).
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE licenses SET status = 'unused', device_id = NULL,"
                    " activated_at = NULL, reset_count = reset_count + 1,"
                    " revoked_at = NULL, revoked_reason = '' WHERE license_key = ?",
                    (license_key,))
                conn.commit()
            finally:
                conn.close()
        return self.get(license_key)

    def list_all(self, status: str | None = None) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                if status:
                    rows = conn.execute(
                        "SELECT * FROM licenses WHERE status = ?"
                        " ORDER BY created_at DESC", (status,)).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def search(self, q: str) -> list[dict]:
        """Admin search across license key / customer / note (substring)."""
        with self._lock:
            conn = self._connect()
            try:
                like = f"%{q}%"
                rows = conn.execute(
                    "SELECT * FROM licenses WHERE license_key LIKE ?"
                    " OR customer LIKE ? OR note LIKE ?"
                    " ORDER BY created_at DESC",
                    (like, like, like)).fetchall()
                return [self._row_to_dict(r) for r in rows]
            finally:
                conn.close()

    def stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM licenses GROUP BY status").fetchall()
                total = conn.execute("SELECT COUNT(*) AS n FROM licenses").fetchone()["n"]
            finally:
                conn.close()
        return {"total": total, "by_status": {r["status"]: r["n"] for r in rows}}
