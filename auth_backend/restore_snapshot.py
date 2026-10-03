"""Restore licences from a snapshot captured through the admin API.

Why this exists
---------------
A Render free instance's filesystem is ephemeral, so a redeploy can wipe
``licenses.db`` entirely. This rebuilds it from a snapshot taken with
``GET /admin/keys``, making recovery one command instead of archaeology.

    python -m restore_snapshot --snapshot ../../backups/licenses-live-YYYYMMDD.json --dry-run
    python -m restore_snapshot --snapshot ../../backups/licenses-live-YYYYMMDD.json

What it restores
----------------
The key itself, customer, note, plan, tier, status, creation and expiry dates,
activation timestamp, revocation and suspension state, the PC limit, the bound
PC(s) - via ``key_activity.pc_hwid``, which is the same hashed fingerprint the
client stores as its ``device_id`` - and so the PC allowance as well.

The one thing it cannot rebuild is the full 30-day history grid: the API
reports per-key distinct-PC counts per day (``day_counts``) but not which PC was
active on which day. Each PC's ``last_seen`` day is restored faithfully, which
is what keeps its slot reserved; the older day-bars in the panel come back
empty. Nothing is fabricated to fill them.

Status is reconstructed rather than copied, because ``GET /admin/keys``
deliberately normalises it to the three states the panel shows. A key that was
never activated returns as ``unused`` instead of being flattened to ``active``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

_tmpdir = tempfile.mkdtemp(prefix="mt-restore-")
os.environ.setdefault("LICENSE_DB_PATH", os.path.join(_tmpdir, "restore.db"))

from db import LicenseDB, normalize_tier  # noqa: E402

_COLUMNS = (
    "status", "created_at", "expires_at", "activated_at", "revoked_at",
    "revoked_reason", "suspended_at", "suspended_until", "max_pcs", "tier",
    "last_seen", "pc_name", "activation_count", "device_id",
)
_ASSIGN = ", ".join(f"{c} = ?" for c in _COLUMNS)


def _ts(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _status(row: dict) -> str:
    """Rebuild the stored status from the panel's normalised view."""
    if row.get("status") == "revoked" or row.get("revoked_at"):
        return "revoked"
    until = _ts(row.get("suspended_until"))
    if until and until > datetime.now(timezone.utc).timestamp():
        return "suspended"
    exp = _ts(row.get("expires_at"))
    if exp is not None and exp <= datetime.now(timezone.utc).timestamp():
        return "expired"
    # used_pcs counts bound PCs, so it is the honest signal for "activated".
    return "active" if (row.get("used_pcs") or 0) > 0 else "unused"


def _bound(row: dict) -> list[dict]:
    """PCs bound to this key, newest check-in first."""
    return sorted((row.get("pcs") or []),
                  key=lambda p: p.get("last_seen") or "", reverse=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--snapshot", required=True,
                    help="JSON file written from GET /admin/keys")
    ap.add_argument("--db", default=None,
                    help="target SQLite path (default: $LICENSE_DB_PATH)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args(argv)

    with open(args.snapshot, encoding="utf-8-sig") as fh:
        snap = json.load(fh)
    rows = snap["keys"]

    tiers: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for r in rows:
        tiers[normalize_tier(r.get("tier"))] = tiers.get(
            normalize_tier(r.get("tier")), 0) + 1
        statuses[_status(r)] = statuses.get(_status(r), 0) + 1

    print(f"snapshot taken_at : {snap.get('taken_at', '?')}")
    print(f"source            : {snap.get('source', '?')}")
    print(f"rows in snapshot  : {len(rows)}")
    print(f"by status         : {statuses}")
    print(f"by tier           : {tiers}")

    if args.dry_run:
        print("\n-- dry run, nothing written --")
        for r in rows:
            pcs = _bound(r)
            print(f"  {r['key']}  {_status(r):<8} {normalize_tier(r.get('tier')):<11}"
                  f" {r.get('plan', ''):<8} pcs={len(pcs)}/{r.get('max_pcs', 1)}"
                  f"  {r.get('customer', '')}")
            for p in pcs:
                print(f"      bind {p['name']}  {p['hwid'][:12]}...  "
                      f"last {p.get('last_seen')}")
        return 0

    db = LicenseDB(args.db)
    created = skipped = 0
    pcs_restored = 0

    for r in rows:
        key = r["key"]
        if db.get(key) is not None:
            skipped += 1
            print(f"  skip {key} (already present)")
            continue

        db.create(key, plan=r.get("plan") or "lifetime",
                  customer=r.get("customer") or "", note=r.get("note") or "",
                  expires_at=r.get("expires_at"),
                  max_pcs=int(r.get("max_pcs") or 1),
                  tier=normalize_tier(r.get("tier")))

        pcs = _bound(r)
        newest = pcs[0] if pcs else {}
        with db._lock:
            conn = db._connect()
            try:
                db._exec(
                    conn,
                    f"UPDATE licenses SET {_ASSIGN} WHERE license_key = ?",
                    (_status(r), r.get("created_at") or "", r.get("expires_at"),
                     r.get("activated_at"), r.get("revoked_at"),
                     r.get("revoked_reason") or "", r.get("suspended_at"),
                     r.get("suspended_until"), int(r.get("max_pcs") or 1),
                     normalize_tier(r.get("tier")), newest.get("last_seen"),
                     newest.get("name") or "", max(1, len(pcs)),
                     newest.get("hwid"), key))
                # key_activity.pc_hwid *is* the client's device fingerprint, so
                # restoring it keeps the PC bound and its slot reserved.
                for p in pcs:
                    day = (p.get("last_seen") or "")[:10]
                    if not day:
                        continue
                    db._exec(
                        conn,
                        "INSERT INTO key_activity (license_key, pc_hwid, day,"
                        " pc_name, seen_count, last_seen) VALUES (?,?,?,?,?,?)"
                        " ON CONFLICT (license_key, pc_hwid, day) DO UPDATE SET"
                        " pc_name = excluded.pc_name, last_seen = excluded.last_seen",
                        (key, p["hwid"], day, p.get("name") or "",
                         int((r.get("day_counts") or {}).get(day, 1) or 1),
                         p.get("last_seen")))
                    pcs_restored += 1
                conn.commit()
            finally:
                conn.close()

        if _status(r) == "revoked":
            db.log_event(key, "revoked",
                         r.get("revoked_reason") or "restored from snapshot")
        else:
            db.log_event(key, "restored",
                         f"Restored from snapshot taken {snap.get('taken_at', '?')}")
        created += 1

    stats = db.stats()
    print(f"\ncreated {created}, skipped {skipped}, PC bindings restored {pcs_restored}")
    print(f"database now holds {stats['total']} licence(s)")
    print(f"  by status: {stats['by_status']}")
    print(f"  by tier  : {stats['by_tier']}")
    print("\nnote: the per-day activity grid is only as detailed as each PC's "
          "last_seen day - the API reports key-level daily counts, not which PC "
          "was active on which day, so older day-bars come back empty rather than "
          "being guessed at.")
    return 0


if __name__ == "__main__":
    sys.exit(main())