"""License database for the MAXIMUM TWEAKS license server.

SQLite by default, PostgreSQL (Neon) when ``DATABASE_URL`` is set.

* SQLite (no ``DATABASE_URL``): used for local development. Defaults to
  ``auth_backend/licenses.db`` (override with ``LICENSE_DB_PATH``).
* PostgreSQL (``DATABASE_URL`` set): used in production on Render/Neon so
  licenses survive restarts/redeploys without a persistent disk.

Both backends expose the same ``LicenseDB`` API; the licensing logic in
``main.py``/``keys.py`` is identical either way. The desktop app never touches
this store — it only ever talks to the HTTP API in ``main.py``.

Note on Postgres connections: we deliberately open a *fresh* connection per
operation instead of using a warm pool. ``psycopg_pool`` (as used previously)
strands its worker threads after a few getconn/putconn cycles and then times
out on every subsequent call — that surfaced as persistent ``HTTP 500``s on
the live license server. This store is low-traffic, so the ~10-500ms connect
overhead per operation is a fair price for never hanging again.

All times are UTC in ``YYYY-MM-DD HH:MM:SS`` strings (same format the old
Discord backend used). ``expires_at`` is NULL for lifetime licenses.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - only needed when DATABASE_URL is set
    psycopg = None
    dict_row = None

import logging
logger = logging.getLogger("maxtweaks.license.db")

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "licenses.db"

SQLITE_SCHEMA = """
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
    suspended_at     TEXT    DEFAULT NULL,
    suspended_until  TEXT    DEFAULT NULL,       -- NULL = not suspended
    reset_count      INTEGER NOT NULL DEFAULT 0           -- support unbinds (PC change)
);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);

-- Per-PC check-in activity (heartbeat). One row per key+PC+day.
CREATE TABLE IF NOT EXISTS key_activity (
    license_key TEXT    NOT NULL,
    pc_hwid     TEXT    NOT NULL,
    day         TEXT    NOT NULL,          -- YYYY-MM-DD (UTC)
    pc_name     TEXT    NOT NULL DEFAULT '',
    seen_count  INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT    NOT NULL,
    PRIMARY KEY (license_key, pc_hwid, day)
);
CREATE INDEX IF NOT EXISTS idx_key_activity_key_day ON key_activity(license_key, day);
CREATE INDEX IF NOT EXISTS idx_key_activity_key_hwid ON key_activity(license_key, pc_hwid);

-- Logged refusals (e.g. a new PC trying to check in while the key is at its
-- PC limit, revoked, expired or unknown).
CREATE TABLE IF NOT EXISTS key_blocked (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key TEXT    NOT NULL,
    pc_hwid     TEXT    NOT NULL,
    pc_name     TEXT    NOT NULL DEFAULT '',
    at          TEXT    NOT NULL,          -- UTC timestamp of the refused check-in
    reason      TEXT    NOT NULL DEFAULT 'over_limit'
);
CREATE INDEX IF NOT EXISTS idx_key_blocked_key_at ON key_blocked(license_key, at);

-- Ops + client event log (ban/suspend/activate, applied-tweak reports, ...).
CREATE TABLE IF NOT EXISTS key_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key TEXT    NOT NULL,
    at          TEXT    NOT NULL,          -- UTC timestamp
    event       TEXT    NOT NULL,          -- activated|revoked|banned|suspended|refused|applied...
    detail      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_key_log_key_at ON key_log(license_key, at);

-- Ultra Mode waitlist (emails collected by the dashboard's "Join the
-- waitlist" button). The launch email is sent from maxoptimizations@gmail.com
-- through a swappable mail provider (see mailers.py); emails only ever live
-- in this store — never in the client.
CREATE TABLE IF NOT EXISTS waitlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT    NOT NULL UNIQUE,          -- lowercased; UNIQUE blocks dupes
    source      TEXT    NOT NULL DEFAULT '',      -- where it was submitted from
    joined_at   TEXT    NOT NULL,                 -- UTC timestamp
    subscribed  INTEGER NOT NULL DEFAULT 1,       -- 1 = eligible for launch email
    unsub_token TEXT    NOT NULL UNIQUE,          -- one-click unsubscribe link
    notified_at TEXT    DEFAULT NULL              -- last launch-email send time
);
CREATE INDEX IF NOT EXISTS idx_waitlist_subscribed ON waitlist(subscribed);
"""

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS licenses (
    id               BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    license_key      TEXT    NOT NULL UNIQUE,
    status           TEXT    NOT NULL DEFAULT 'unused',
    plan             TEXT    NOT NULL DEFAULT 'lifetime',
    customer         TEXT    NOT NULL DEFAULT '',
    note             TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL,
    expires_at       TEXT    DEFAULT NULL,
    activated_at     TEXT    DEFAULT NULL,
    device_id        TEXT    DEFAULT NULL,
    activation_count INTEGER NOT NULL DEFAULT 0,
    last_validated   TEXT    DEFAULT NULL,
    revoked_at       TEXT    DEFAULT NULL,
    revoked_reason   TEXT    NOT NULL DEFAULT '',
    suspended_at     TEXT    DEFAULT NULL,
    suspended_until  TEXT    DEFAULT NULL,
    reset_count      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);

CREATE TABLE IF NOT EXISTS key_activity (
    license_key TEXT    NOT NULL,
    pc_hwid     TEXT    NOT NULL,
    day         TEXT    NOT NULL,
    pc_name     TEXT    NOT NULL DEFAULT '',
    seen_count  INTEGER NOT NULL DEFAULT 1,
    last_seen   TEXT    NOT NULL,
    PRIMARY KEY (license_key, pc_hwid, day)
);
CREATE INDEX IF NOT EXISTS idx_key_activity_key_day ON key_activity(license_key, day);
CREATE INDEX IF NOT EXISTS idx_key_activity_key_hwid ON key_activity(license_key, pc_hwid);

CREATE TABLE IF NOT EXISTS key_blocked (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    license_key TEXT    NOT NULL,
    pc_hwid     TEXT    NOT NULL,
    pc_name     TEXT    NOT NULL DEFAULT '',
    at          TEXT    NOT NULL,
    reason      TEXT    NOT NULL DEFAULT 'over_limit'
);
CREATE INDEX IF NOT EXISTS idx_key_blocked_key_at ON key_blocked(license_key, at);

CREATE TABLE IF NOT EXISTS key_log (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    license_key TEXT    NOT NULL,
    at          TEXT    NOT NULL,
    event       TEXT    NOT NULL,
    detail      TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_key_log_key_at ON key_log(license_key, at);

CREATE TABLE IF NOT EXISTS waitlist (
    id          BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    email       TEXT    NOT NULL UNIQUE,
    source      TEXT    NOT NULL DEFAULT '',
    joined_at   TEXT    NOT NULL,
    subscribed  INTEGER NOT NULL DEFAULT 1,
    unsub_token TEXT    NOT NULL UNIQUE,
    notified_at TEXT    DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_waitlist_subscribed ON waitlist(subscribed);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_day(offset: int = 0) -> str:
    """UTC date string 'YYYY-MM-DD', offset days back from today (negative = past)."""
    return (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d")


def _utc_ts(offset_minutes: int = 0) -> str:
    """Full UTC timestamp, offset minutes back from now (negative = past)."""
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        exp = datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return exp.timestamp() <= time.time()


def _parse_db_path() -> str:
    override = os.environ.get("LICENSE_DB_PATH", "").strip()
    if override:
        return override
    return str(DEFAULT_DB_PATH)


class LicenseDB:
    """Thread-safe license store: SQLite locally, PostgreSQL when DATABASE_URL
    is set. The public API is identical for both backends."""

    def __init__(self, path: str | None = None):
        self._dsn = os.environ.get("DATABASE_URL", "").strip() or None
        self._engine = "postgres" if self._dsn else "sqlite"
        self._path = path or _parse_db_path()
        if self._engine == "sqlite":
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        self._lock = threading.RLock()
        self._pg_conn = None
        with self._lock:
            conn = self._connect()
            try:
                self._init_schema(conn)
                conn.commit()
            finally:
                self._release(conn)

    @property
    def engine(self) -> str:
        """'postgres' when DATABASE_URL is set, else 'sqlite'."""
        return self._engine

    def _connect(self):
        if self._engine == "postgres":
            if psycopg is None:  # pragma: no cover
                raise RuntimeError(
                    "DATABASE_URL is set but psycopg is not installed - "
                    "run: pip install -r requirements.txt")
            # Persistent, lock-guarded connection: keeping one long-lived
            # socket avoids the ~2s Neon connection setup that every call
            # previously paid. (psycopg_pool's thread-stranding bug is avoided
            # entirely - we reuse a single connection, never a thread pool.)
            if self._pg_conn is not None and not self._pg_conn.closed:
                return self._pg_conn
            self._pg_conn = psycopg.connect(self._dsn, connect_timeout=15,
                                            row_factory=dict_row)
            return self._pg_conn
        conn = sqlite3.connect(self._path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _release(self, conn) -> None:
        """Only close throwaway connections; the persistent PG socket stays."""
        if self._engine == "postgres":
            return
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _drop_persistent(self) -> None:
        if self._engine == "postgres":
            try:
                if self._pg_conn is not None:
                    self._pg_conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._pg_conn = None

    def _init_schema(self, conn) -> None:
        if self._engine == "postgres":
            for stmt in PG_SCHEMA.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
        else:
            conn.executescript(SQLITE_SCHEMA)
        self._migrate_columns(conn)

    _NEW_COLUMNS = (
        ("max_pcs", "INTEGER NOT NULL DEFAULT 1"),
        ("pc_name", "TEXT NOT NULL DEFAULT ''"),
        ("last_seen", "TEXT DEFAULT NULL"),
        ("suspended_at", "TEXT DEFAULT NULL"),
        ("suspended_until", "TEXT DEFAULT NULL"),
    )

    def _migrate_columns(self, conn) -> None:
        """Idempotently add columns introduced after the first deploy."""
        def _existing():
            if self._engine == "postgres":
                rows = conn.execute(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'licenses'").fetchall()
                return {r["column_name"] for r in rows}
            rows = conn.execute("PRAGMA table_info(licenses)").fetchall()
            return {r["name"] for r in rows}
        try:
            existing = _existing()
            for name, ddl in self._NEW_COLUMNS:
                if name not in existing:
                    conn.execute(f"ALTER TABLE licenses ADD COLUMN {name} {ddl}")
        except Exception:  # noqa: BLE001 - tolerate weird schemas in tests
            logger.warning("db: column migration skipped", exc_info=True)

    def _sql(self, q: str) -> str:
        """Rewrite SQLite '?' placeholders to psycopg '%s' for Postgres."""
        if self._engine == "postgres":
            return q.replace("?", "%s")
        return q

    @staticmethod
    def _is_stale_conn(exc) -> bool:
        """True when the error indicates a dead/purged pooled connection."""
        msg = str(exc).lower()
        return any(s in msg for s in (
            "adminshutdown", "server closed", "connection attempt failed",
            "connection already closed", "could not connect",
        ))

    def _exec(self, conn, sql: str, params=()):
        """Run one statement with engine-appropriate placeholders."""
        if params:
            return conn.execute(self._sql(sql), params)
        return conn.execute(self._sql(sql))

    def _run_with_retry(self, fn, *, commit: bool = True):
        """Execute *fn(conn)* guarded by the persistent connection (Postgres)
        or a fresh connection (SQLite); retry once on stale/transient errors.
        For Postgres the socket is reused for every call and only dropped when
        it actually goes stale."""
        for attempt in range(2):
            conn = self._connect()
            try:
                result = fn(conn)
                if commit:
                    conn.commit()
                return result
            except Exception as exc:
                # Roll everything back so the persistent Postgres socket isn't
                # left in a failed transaction (it is reused for every call).
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                if self._is_stale_conn(exc):
                    self._drop_persistent()
                    if attempt == 0:
                        logger.warning("db: stale/transient connection, "
                                       "retrying (attempt %d)", attempt + 1)
                        continue
                raise
            finally:
                self._release(conn)

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    def _insert_log(self, conn, license_key: str, event: str,
                    detail: str = "") -> None:
        self._exec(
            conn,
            "INSERT INTO key_log (license_key, at, event, detail)"
            " VALUES (?, ?, ?, ?)",
            (license_key, _utc_now(), event, detail))

    def _row_to_dict(self, row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}

    def get(self, license_key: str) -> dict | None:
        def _fn(conn):
            row = self._exec(
                conn, "SELECT * FROM licenses WHERE license_key = ?",
                (license_key,)).fetchone()
            return self._row_to_dict(row)
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    # ------------------------------------------------------------------
    # Writes (admin + activation flow)
    # ------------------------------------------------------------------

    def create(self, license_key: str, plan: str = "lifetime",
               customer: str = "", note: str = "",
               expires_at: str | None = None,
               max_pcs: int = 1) -> dict:
        def _fn(conn):
            self._exec(
                conn,
                "INSERT INTO licenses (license_key, status, plan, customer,"
                " note, created_at, expires_at, max_pcs)"
                " VALUES (?, 'unused', ?, ?, ?, ?, ?, ?)",
                (license_key, plan, customer, note, _utc_now(), expires_at, max_pcs))
        with self._lock:
            self._run_with_retry(_fn)
        rec = self.get(license_key)
        if rec is None:  # pragma: no cover
            raise RuntimeError("license record was not created")
        return rec

    def log_event(self, license_key: str, event: str, detail: str = "") -> None:
        """Append an audit event for a key (client reports, admin ops, ...)."""
        def _fn(conn):
            self._insert_log(conn, license_key, event, detail)
        with self._lock:
            self._run_with_retry(_fn)

    def activate(self, license_key: str, device_id: str) -> dict:
        """Bind an unused license to a device and mark it active."""
        now = _utc_now()
        def _fn(conn):
            self._exec(
                conn,
                "UPDATE licenses SET status = 'active', device_id = ?,"
                " activated_at = COALESCE(activated_at, ?),"
                " activation_count = activation_count + 1,"
                " last_validated = ?, revoked_at = NULL,"
                " revoked_reason = '' WHERE license_key = ?",
                (device_id, now, now, license_key))
            self._insert_log(conn, license_key, "activated",
                             "Key bound to a device and activated.")
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def touch_validation(self, license_key: str) -> None:
        def _fn(conn):
            self._exec(
                conn,
                "UPDATE licenses SET last_validated = ? WHERE license_key = ?",
                (_utc_now(), license_key))
        with self._lock:
            self._run_with_retry(_fn)

    def mark_expired(self, license_key: str) -> None:
        def _fn(conn):
            self._exec(
                conn,
                "UPDATE licenses SET status = 'expired' WHERE license_key = ?",
                (license_key,))
        with self._lock:
            self._run_with_retry(_fn)

    def revoke(self, license_key: str, reason: str = "") -> dict | None:
        def _fn(conn):
            self._exec(
                conn,
                "UPDATE licenses SET status = 'revoked', revoked_at = ?,"
                " revoked_reason = ? WHERE license_key = ?",
                (_utc_now(), reason, license_key))
            self._insert_log(conn, license_key, "revoked", reason)
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def unrevoke(self, license_key: str) -> dict | None:
        def _fn(conn):
            self._exec(
                conn,
                "UPDATE licenses SET status = 'active', revoked_at = NULL,"
                " revoked_reason = '' WHERE license_key = ?",
                (license_key,))
            self._insert_log(conn, license_key, "unrevoked",
                             "Key restored to active.")
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def ban(self, license_key: str, reason: str = "") -> dict | None:
        """Hard-ban a key: revoke it, log every PC it used as 'banned', and
        record the event. Unban restores the key (PC refusals stay on record)."""
        def _fn(conn):
            row = self._exec(
                conn, "SELECT * FROM licenses WHERE license_key = ?",
                (license_key,)).fetchone()
            if row is None:
                return None
            detail = reason or "banned"
            self._exec(
                conn, "UPDATE licenses SET status = 'revoked', revoked_at = ?,"
                " revoked_reason = 'banned' WHERE license_key = ?",
                (_utc_now(), license_key))
            pcs = self._exec(
                conn, "SELECT pc_hwid, MAX(pc_name) AS pc_name FROM key_activity"
                " WHERE license_key = ? GROUP BY pc_hwid", (license_key,)).fetchall()
            now = _utc_now()
            for pc in pcs:
                self._exec(
                    conn,
                    "INSERT INTO key_blocked (license_key, pc_hwid, pc_name, at,"
                    " reason) VALUES (?, ?, ?, ?, 'banned')",
                    (license_key, pc["pc_hwid"], pc["pc_name"], now))
            self._insert_log(conn, license_key, "banned", detail)
            return True
        with self._lock:
            ok = self._run_with_retry(_fn)
        return self.get(license_key) if ok else None

    def unban(self, license_key: str) -> dict | None:
        def _fn(conn):
            self._exec(
                conn, "UPDATE licenses SET status = 'active', revoked_at = NULL,"
                " revoked_reason = '' WHERE license_key = ?", (license_key,))
            self._insert_log(conn, license_key, "unbanned",
                             "Key restored after being banned.")
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def suspend(self, license_key: str, until: str,
                reason: str = "") -> dict | None:
        """Temporarily suspend a key until the given UTC timestamp. The client
        is refused (license_suspended) during the window, then it resumes."""
        def _fn(conn):
            self._exec(
                conn, "UPDATE licenses SET suspended_at = ?, suspended_until = ?"
                " WHERE license_key = ?", (_utc_now(), until, license_key))
            self._insert_log(conn, license_key, "suspended",
                             f"until {until}" + (f" ({reason})" if reason else ""))
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def unsuspend(self, license_key: str, detail: str = "") -> dict | None:
        def _fn(conn):
            self._exec(
                conn, "UPDATE licenses SET suspended_at = NULL,"
                " suspended_until = NULL WHERE license_key = ?", (license_key,))
            self._insert_log(conn, license_key, "unsuspended", detail)
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def unbind(self, license_key: str) -> dict | None:
        """Support action for a PC change: unbind the device and free the key."""
        def _fn(conn):
            self._exec(
                conn,
                "UPDATE licenses SET status = 'unused', device_id = NULL,"
                " activated_at = NULL, reset_count = reset_count + 1,"
                " revoked_at = NULL, revoked_reason = '',"
                " suspended_at = NULL, suspended_until = NULL"
                " WHERE license_key = ?",
                (license_key,))
            self._insert_log(conn, license_key, "unbound",
                             "Admin freed the key for a new device.")
        with self._lock:
            self._run_with_retry(_fn)
        return self.get(license_key)

    def delete(self, license_key: str) -> int:
        """Permanently remove a key row. Admin-ops only. Returns rows deleted."""
        def _fn(conn):
            cur = self._exec(
                conn,
                "DELETE FROM licenses WHERE license_key = ?",
                (license_key,))
            if cur.rowcount:
                self._exec(conn, "DELETE FROM key_activity"
                           " WHERE license_key = ?", (license_key,))
                self._exec(conn, "DELETE FROM key_blocked"
                           " WHERE license_key = ?", (license_key,))
                self._exec(conn, "DELETE FROM key_log"
                           " WHERE license_key = ?", (license_key,))
            return cur.rowcount
        with self._lock:
            n = self._run_with_retry(_fn)
        return n if n is not None else 0

    def revoke_all(self) -> int:
        """Revoke every key that isn't already revoked/expired.

        Bulk admin-ops: each key gets a per-key audit log line (rather than
        one anonymous row) so the inspect timeline stays truthful. Returns
        the number of keys revoked.
        """
        def _fn(conn):
            now = _utc_now()
            rows = self._exec(
                conn, "SELECT license_key FROM licenses"
                " WHERE status IN ('unused', 'active')").fetchall()
            keys = [r["license_key"] for r in rows]
            for key in keys:
                self._exec(
                    conn, "UPDATE licenses SET status = 'revoked',"
                    " revoked_at = ?, revoked_reason = 'revoked_all'"
                    " WHERE license_key = ?", (now, key))
                self._insert_log(conn, key, "revoked",
                                 "Revoked via Disable all.")
            return len(keys)
        with self._lock:
            n = self._run_with_retry(_fn)
        return n if n is not None else 0

    def delete_all(self) -> int:
        """Permanently remove every license row and its related activity,
        blocked and log rows. Admin-ops only (fresh-start). Returns the
        number of license rows deleted."""
        def _fn(conn):
            total = self._exec(conn, "SELECT COUNT(*) AS n FROM licenses"
                              ).fetchone()["n"]
            for table in ("key_activity", "key_blocked", "key_log",
                          "licenses"):
                self._exec(conn, f"DELETE FROM {table}")
            return int(total or 0)
        with self._lock:
            n = self._run_with_retry(_fn)
        return n if n is not None else 0

    def list_all(self, status: str | None = None) -> list[dict]:
        def _fn(conn):
            if status:
                rows = self._exec(
                    conn,
                    "SELECT * FROM licenses WHERE status = ?"
                    " ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = self._exec(
                    conn,
                    "SELECT * FROM licenses ORDER BY created_at DESC").fetchall()
            return [self._row_to_dict(r) for r in rows]
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def search(self, q: str) -> list[dict]:
        """Admin search across license key / customer / note (substring)."""
        def _fn(conn):
            like = f"%{q}%"
            rows = self._exec(
                conn,
                "SELECT * FROM licenses WHERE license_key LIKE ?"
                " OR customer LIKE ? OR note LIKE ?"
                " ORDER BY created_at DESC",
                (like, like, like)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def stats(self) -> dict:
        def _fn(conn):
            rows = self._exec(
                conn,
                "SELECT status, COUNT(*) AS n FROM licenses GROUP BY status").fetchall()
            total = self._exec(
                conn,
                "SELECT COUNT(*) AS n FROM licenses").fetchone()["n"]
            return {"total": total, "by_status": {r["status"]: r["n"] for r in rows}}
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    # ------------------------------------------------------------------
    # Check-in (heartbeat) flow
    # ------------------------------------------------------------------

    def checkin(self, license_key: str, hwid: str, pc_name: str = "") -> dict:
        """Handle a heartbeat check-in from the customer app.

        Returns:
          allowed  -> {"status": "allowed", "expires_at": ..., "plan": ...}
          refused  -> {"status": "refused", "error": <code>, "message": ...}
          * "invalid_license"    - unknown key
          * "license_revoked"    - revoked
          * "license_expired"    - past expiry
          * "license_suspended"  - temporarily suspended by the operator
          * "over_limit"         - already at max_pcs active PCs
        """
        def _fn(conn):
            row = self._exec(
                conn, "SELECT * FROM licenses WHERE license_key = ?",
                (license_key,)).fetchone()
            rec = self._row_to_dict(row)
            if rec is None:
                return {"status": "refused", "error": "invalid_license",
                        "message": "That license key wasn't recognized."}
            if rec["status"] == "revoked":
                reason = (rec.get("revoked_reason") or "").strip()
                if reason == "banned":
                    return {"status": "refused", "error": "license_banned",
                            "message": ("This account has been permanently "
                                        "banned from Maximum Tweaks. Contact "
                                        "support to appeal."),
                            "revoked_at": rec.get("revoked_at"),
                            "revoked_reason": "banned"}
                return {"status": "refused", "error": "license_revoked",
                        "message": ("This license key has been revoked. "
                                    "Contact support to re-activate it."),
                        "revoked_at": rec.get("revoked_at"),
                        "revoked_reason": rec.get("revoked_reason") or ""}
            if _is_expired(rec["expires_at"]):
                self._exec(conn, "UPDATE licenses SET status = 'expired'"
                           " WHERE license_key = ?", (license_key,))
                return {"status": "refused", "error": "license_expired",
                        "message": "This license key has expired."}

            until = rec.get("suspended_until") or ""
            if until and not _is_expired(until):
                self._insert_log(conn, license_key, "refused",
                                 "license_suspended")
                return {"status": "refused", "error": "license_suspended",
                        "message": (f"This license is temporarily suspended by "
                                    f"the operator until {until} (UTC). It "
                                    "resumes automatically."),
                        "suspended_until": until}
            if until:
                self._exec(
                    conn, "UPDATE licenses SET suspended_at = NULL,"
                    " suspended_until = NULL WHERE license_key = ?",
                    (license_key,))
                self._insert_log(conn, license_key, "unsuspended",
                                 "auto-resumed")

            max_pcs = int(rec.get("max_pcs") or 1)
            exp = rec.get("expires_at")
            plan = rec.get("plan")

            # Active set = distinct PCs that checked in within the last 30
            # days. A PC drops out of this window automatically after 30 days
            # of silence, which frees its slot without a manual unbind.
            active_rows = self._exec(
                conn,
                "SELECT DISTINCT pc_hwid FROM key_activity"
                " WHERE license_key = ? AND day >= ?",
                (license_key, _utc_day(-29))).fetchall()
            active_hwids = {r["pc_hwid"] for r in active_rows}

            if hwid in active_hwids:
                self._upsert_activity(conn, license_key, hwid, pc_name)
                return {"status": "allowed", "expires_at": exp, "plan": plan}

            if len(active_hwids) >= max_pcs:
                # New PC beyond the limit: refuse it (and keep the existing
                # PCs working). Log it so the admin panel can show "X blocked
                # attempts this week".
                self._exec(
                    conn,
                    "INSERT INTO key_blocked (license_key, pc_hwid, pc_name,"
                    " at, reason) VALUES (?, ?, ?, ?, 'over_limit')",
                    (license_key, hwid, pc_name, _utc_now()))
                return {"status": "refused", "error": "over_limit",
                        "message": ("This key is already used on the maximum "
                                    "number of PCs.")}

            self._upsert_activity(conn, license_key, hwid, pc_name)
            return {"status": "allowed", "expires_at": exp, "plan": plan}

        with self._lock:
            return self._run_with_retry(_fn)

    def _upsert_activity(self, conn, license_key: str, hwid: str,
                         pc_name: str) -> None:
        now = _utc_now()
        self._exec(
            conn,
            "INSERT INTO key_activity (license_key, pc_hwid, day, pc_name,"
            " seen_count, last_seen) VALUES (?, ?, ?, ?, 1, ?)"
            " ON CONFLICT (license_key, pc_hwid, day) DO UPDATE SET"
            " pc_name = excluded.pc_name,"
            " seen_count = key_activity.seen_count + 1,"
            " last_seen = excluded.last_seen",
            (license_key, hwid, _utc_day(), pc_name, now))
        # Also refresh the license-level last_seen / current pc_name so the
        # admin list can show "Last check-in" per key at a glance.
        self._exec(
            conn,
            "UPDATE licenses SET last_seen = ?, pc_name = ?"
            " WHERE license_key = ?",
            (now, pc_name, license_key))

    # ------------------------------------------------------------------
    # Activity reads (admin)
    # ------------------------------------------------------------------

    def activity(self, license_key: str, days: int = 30) -> dict:
        """Per-PC check-in grid for the key detail panel plus recent refusals."""
        def _fn(conn):
            rows = self._exec(
                conn,
                "SELECT pc_hwid, pc_name, day, last_seen FROM key_activity"
                " WHERE license_key = ? AND day >= ? ORDER BY pc_hwid, day",
                (license_key, _utc_day(-(days - 1)))).fetchall()
            blocked = self._exec(
                conn,
                "SELECT pc_hwid, pc_name, at, reason FROM key_blocked"
                " WHERE license_key = ? AND at >= ? ORDER BY at DESC LIMIT 50",
                (license_key, _utc_ts(-(7 * 24 * 60)))).fetchall()
            pcs: dict[str, dict] = {}
            for r in rows:
                pc = pcs.setdefault(r["pc_hwid"], {
                    "hwid": r["pc_hwid"], "name": r["pc_name"],
                    "last_seen": r["last_seen"], "days": {}})
                pc["days"][r["day"]] = True
                if pc["name"] != r["pc_name"] and r["pc_name"]:
                    pc["name"] = r["pc_name"]
            return {
                "pcs": [p for p in pcs.values()],
                "blocked": [dict(r) for r in blocked],
            }
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def remove_pc(self, license_key: str, hwid: str) -> int:
        """Drop a PC from a key so its slot is freed immediately. Admin-ops."""
        def _fn(conn):
            cur = self._exec(
                conn, "DELETE FROM key_activity WHERE license_key = ?"
                " AND pc_hwid = ?", (license_key, hwid))
            return cur.rowcount
        with self._lock:
            n = self._run_with_retry(_fn)
        return n if n is not None else 0

    def overview(self) -> dict:
        """Everything the admin panel needs for the key list + stats cards, in
        a handful of whole-table queries (no per-key N+1)."""
        def _fn(conn):
            keys = [self._row_to_dict(r) for r in self._exec(
                conn, "SELECT * FROM licenses ORDER BY created_at DESC").fetchall()]

            day_rows = [dict(r) for r in self._exec(
                conn,
                "SELECT license_key, day, COUNT(DISTINCT pc_hwid) AS n"
                " FROM key_activity WHERE day >= ? GROUP BY license_key, day",
                (_utc_day(-29),)).fetchall()]
            day_counts: dict[str, dict] = {}
            for r in day_rows:
                day_counts.setdefault(r["license_key"], {})[r["day"]] = r["n"]

            pc_rows = [dict(r) for r in self._exec(
                conn,
                "SELECT license_key, pc_hwid, MAX(pc_name) AS pc_name,"
                " MAX(last_seen) AS last_seen FROM key_activity WHERE day >= ?"
                " GROUP BY license_key, pc_hwid",
                (_utc_day(-29),)).fetchall()]
            pcs: dict[str, list[dict]] = {}
            for r in pc_rows:
                pcs.setdefault(r["license_key"], []).append({
                    "hwid": r["pc_hwid"], "name": r["pc_name"],
                    "last_seen": r["last_seen"]})

            blocked = [dict(r) for r in self._exec(
                conn,
                "SELECT license_key, COUNT(*) AS n FROM key_blocked"
                " WHERE at >= ? GROUP BY license_key",
                (_utc_ts(-(7 * 24 * 60)),)).fetchall()]
            blocked_week: dict[str, int] = {r["license_key"]: r["n"] for r in blocked}

            return {
                "keys": [
                    {
                        **k,
                        "pcs": pcs.get(k["license_key"], []),
                        "day_counts": day_counts.get(k["license_key"], {}),
                        "blocked_week": blocked_week.get(k["license_key"], 0),
                    }
                    for k in keys
                ],
                "day_counts": day_counts,
                "pcs": pcs,
                "blocked_week": blocked_week,
            }
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    # ------------------------------------------------------------------
    # Event log + Inspect (admin)
    # ------------------------------------------------------------------

    def logs(self, license_key: str, limit: int = 200) -> list[dict]:
        """Chronological audit/ops timeline for a key (newest first)."""
        def _fn(conn):
            rows = self._exec(
                conn, "SELECT at, event, detail FROM key_log"
                " WHERE license_key = ? ORDER BY id DESC LIMIT ?",
                (license_key, limit)).fetchall()
            return [dict(r) for r in rows]
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def last_event_detail(self, license_key: str, event: str) -> str:
        """Most recent audit detail for a given event (e.g. the ban reason).
        Returns "" when the key has no such event on record."""
        def _fn(conn):
            row = self._exec(
                conn, "SELECT detail FROM key_log"
                " WHERE license_key = ? AND event = ? ORDER BY id DESC LIMIT 1",
                (license_key, event)).fetchone()
            return (row["detail"] if row else "") or ""
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def inspect(self, license_key: str, days: int = 30) -> dict | None:
        """What the admin Inspect panel needs: the license row, per-PC
        activity (first/last seen), refusal log, and the event timeline."""
        def _fn(conn):
            row = self._exec(
                conn, "SELECT * FROM licenses WHERE license_key = ?",
                (license_key,)).fetchone()
            if row is None:
                return None
            rec = self._row_to_dict(row)
            pcs = self._exec(
                conn,
                "SELECT pc_hwid, MAX(pc_name) AS pc_name,"
                " MIN(last_seen) AS first_seen, MAX(last_seen) AS last_seen,"
                " COUNT(DISTINCT day) AS days_on FROM key_activity"
                " WHERE license_key = ? AND day >= ? GROUP BY pc_hwid"
                " ORDER BY last_seen DESC",
                (license_key, _utc_day(-(days - 1)))).fetchall()
            blocked = self._exec(
                conn,
                "SELECT pc_hwid, pc_name, at, reason FROM key_blocked"
                " WHERE license_key = ? ORDER BY at DESC LIMIT 100",
                (license_key,)).fetchall()
            events = self._exec(
                conn, "SELECT at, event, detail FROM key_log"
                " WHERE license_key = ? ORDER BY id DESC LIMIT 200",
                (license_key,)).fetchall()
            return {
                "meta": rec,
                "pcs": [dict(r) for r in pcs],
                "blocked": [dict(r) for r in blocked],
                "events": [dict(r) for r in events],
            }
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    # ------------------------------------------------------------------
    # Ultra Mode waitlist (join + launch-email bookkeeping)
    # ------------------------------------------------------------------

    def waitlist_add(self, email: str, source: str = "") -> dict:
        """Register an email for the Ultra Mode waitlist.

        Returns ``{"created": bool, "record": {...}}``. The caller should
        send an already validated/normalized (lowercased, trimmed) address;
        the UNIQUE constraint rejects duplicates, which is reported as
        ``created=False`` with the existing row.
        """
        def _fn(conn):
            self._exec(
                conn,
                "INSERT INTO waitlist (email, source, joined_at, subscribed,"
                " unsub_token) VALUES (?, ?, ?, 1, ?)",
                (email, source, _utc_now(), secrets.token_urlsafe(24)))
        with self._lock:
            try:
                self._run_with_retry(_fn)
                created = True
            except Exception:  # noqa: BLE001 - UNIQUE email collision
                created = False
        rec = self.waitlist_get(email)
        if rec is None:  # pragma: no cover
            rec = {"email": email, "source": source, "subscribed": 1}
        return {"created": created, "record": rec}

    def waitlist_get(self, email: str) -> dict | None:
        def _fn(conn):
            row = self._exec(
                conn, "SELECT * FROM waitlist WHERE email = ?",
                (email,)).fetchone()
            return self._row_to_dict(row)
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def waitlist_unsubscribe(self, token: str) -> dict | None:
        """Opt an email out of launch emails via its unique unsubscribe token.
        Returns the row, or None if the token is unknown."""
        def _fn(conn):
            row = self._exec(
                conn, "SELECT * FROM waitlist WHERE unsub_token = ?",
                (token,)).fetchone()
            if row is None:
                return None
            self._exec(conn, "UPDATE waitlist SET subscribed = 0"
                        " WHERE unsub_token = ?", (token,))
            return self._row_to_dict(row)
        with self._lock:
            return self._run_with_retry(_fn, commit=True)

    def waitlist_list(self, subscribed_only: bool = True,
                      limit: int = 100000) -> list[dict]:
        def _fn(conn):
            if subscribed_only:
                rows = self._exec(
                    conn, "SELECT * FROM waitlist WHERE subscribed = 1"
                    " ORDER BY joined_at ASC LIMIT ?", (limit,)).fetchall()
            else:
                rows = self._exec(
                    conn, "SELECT * FROM waitlist ORDER BY joined_at ASC"
                    " LIMIT ?", (limit,)).fetchall()
            return [self._row_to_dict(r) for r in rows]
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def waitlist_count(self, subscribed_only: bool = False) -> int:
        def _fn(conn):
            if subscribed_only:
                row = self._exec(
                    conn,
                    "SELECT COUNT(*) AS n FROM waitlist WHERE subscribed = 1"
                ).fetchone()
            else:
                row = self._exec(
                    conn, "SELECT COUNT(*) AS n FROM waitlist").fetchone()
            return int(row["n"] or 0)
        with self._lock:
            return self._run_with_retry(_fn, commit=False)

    def waitlist_mark_notified(self, ids: list[int]) -> int:
        """Stamp notified_at on the given waitlist ids (launch email sent).
        Returns how many rows were updated."""
        if not ids:
            return 0
        def _fn(conn):
            qmarks = ",".join("?" for _ in ids)
            cur = self._exec(
                conn,
                f"UPDATE waitlist SET notified_at = ?"
                f" WHERE id IN ({qmarks})",
                [_utc_now(), *ids])
            return cur.rowcount
        with self._lock:
            return self._run_with_retry(_fn) or 0
