"""Admin CLI for the MAXIMUM TWEAKS license server.

Operator tool — run it on the machine that owns the license database (the
Render instance's console, or locally against auth_backend/licenses.db). It
speaks directly to the DB, so it needs no network or admin token.

Usage
-----
Run from the ``auth_backend/`` directory::

    python -m admin generate [--count N] [--prefix MAX|REX|MTW]
                             [--duration 1m|6m|lifetime]
                             [--plan lifetime|monthly|yearly|custom]
                             [--customer "Name"] [--note "..."]
                             [--expires "YYYY-MM-DD HH:MM:SS"]
    python -m admin list [--status unused|active|revoked|expired]
    python -m admin show <KEY>
    python -m admin revoke <KEY> [--reason "..."]
    python -m admin unrevoke <KEY>
    python -m admin unbind <KEY>     # support: PC change
    python -m admin stats
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import datetime, timezone

from db import LicenseDB
from keys import generate_key


def _redact(rec: dict) -> dict:
    out = dict(rec)
    out["device_id"] = (out["device_id"][:12] + "...") \
        if out.get("device_id") else None
    return out


def _add_months_utc(months: int) -> str:
    now = datetime.now(timezone.utc)
    month_index = now.month - 1 + months
    year = now.year + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, now.hour, now.minute, now.second,
                    tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cmd_generate(db: LicenseDB, args):
    prefix = (getattr(args, "prefix", "") or "").strip().upper()
    if not prefix:
        prefix = "MAX"
    if len(prefix) > 4 or not prefix.isalnum():
        print(f"Invalid prefix: {prefix!r} (use 1-4 letters/digits)")
        sys.exit(1)
    expires = args.expires
    plan = args.plan
    duration = (getattr(args, "duration", "") or "").strip().lower()
    if not expires:
        if duration == "1m":
            plan = "monthly"; expires = _add_months_utc(1)
        elif duration == "6m":
            plan = "custom"; expires = _add_months_utc(6)
        elif duration == "lifetime":
            plan = "lifetime"; expires = None
        elif duration:
            print("Duration must be: 1m, 6m or lifetime"); sys.exit(1)
    keys = []
    for _ in range(max(1, args.count)):
        key = generate_key(prefix)
        db.create(key, plan=plan if plan else "lifetime", customer=args.customer,
                  note=args.note, expires_at=expires)
        keys.append(key)
    if args.json:
        print(json.dumps({"keys": keys, "prefix": prefix, "plan": plan,
                          "expires_at": expires}))
    else:
        print(f"Generated {len(keys)} license key(s) "
              f"(prefix: {prefix}, plan: {plan or 'lifetime'}"
              f"{', expires: ' + expires if expires else ', lifetime'}):")
        for k in keys:
            print(f"  {k}")


def cmd_list(db: LicenseDB, args):
    rows = db.list_all(args.status)
    if not rows:
        print("No licenses found.")
        return
    print(f"{'KEY':<19} {'STATUS':<9} {'PLAN':<10} {'CUSTOMER':<22} {'ACTIVATED':<11} {'DEVICE':<16}")
    for r in rows:
        device = (r["device_id"][:12] + "...") if r.get("device_id") else "-"
        print(f"{r['license_key']:<19} {r['status']:<9} {r['plan']:<10} "
              f"{(r['customer'] or '-')[:22]:<22} {(r['activated_at'] or '-')[:10]:<11} {device:<16}")


def cmd_show(db: LicenseDB, args):
    rec = db.get(args.key)
    if rec is None:
        print(f"Unknown license key: {args.key}")
        sys.exit(1)
    print(json.dumps(_redact(rec), indent=2))


def cmd_revoke(db: LicenseDB, args):
    rec = db.revoke(args.key, args.reason or "")
    if rec is None:
        print(f"Unknown license key: {args.key}")
        sys.exit(1)
    print(f"Revoked {args.key}")


def cmd_unrevoke(db: LicenseDB, args):
    rec = db.unrevoke(args.key)
    if rec is None:
        print(f"Unknown license key: {args.key}")
        sys.exit(1)
    print(f"Un-revoked {args.key} (status: {rec['status']})")


def cmd_unbind(db: LicenseDB, args):
    rec = db.unbind(args.key)
    if rec is None:
        print(f"Unknown license key: {args.key}")
        sys.exit(1)
    print(f"Unbound {args.key} — ready to activate on a new PC "
          f"(resets so far: {rec['reset_count']})")


def cmd_stats(db: LicenseDB, _args):
    print(json.dumps(db.stats(), indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="auth_admin", description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="create new license keys")
    p_gen.add_argument("--count", type=int, default=1)
    p_gen.add_argument("--prefix", default="",
                       help="key prefix, e.g. MAX, REX, MTW (default MAX)")
    p_gen.add_argument("--duration", default="",
                       choices=["1m", "6m", "lifetime"],
                       help="license length (sets plan + expiry server-side)")
    p_gen.add_argument("--plan", default="lifetime",
                       choices=["lifetime", "monthly", "yearly", "custom"])
    p_gen.add_argument("--customer", default="")
    p_gen.add_argument("--note", default="")
    p_gen.add_argument("--expires", default=None,
                       help='UTC "YYYY-MM-DD HH:MM:SS" (lifetime if omitted)')
    p_gen.set_defaults(func=cmd_generate)

    p_list = sub.add_parser("list", help="list licenses")
    p_list.add_argument("--status", default=None,
                        choices=["unused", "active", "revoked", "expired"])
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one license")
    p_show.add_argument("key")
    p_show.set_defaults(func=cmd_show)

    p_rev = sub.add_parser("revoke", help="revoke a license")
    p_rev.add_argument("key")
    p_rev.add_argument("--reason", default="")
    p_rev.set_defaults(func=cmd_revoke)

    p_unr = sub.add_parser("unrevoke", help="undo a revocation")
    p_unr.add_argument("key")
    p_unr.set_defaults(func=cmd_unrevoke)

    p_unb = sub.add_parser("unbind", help="unbind a device (PC change)")
    p_unb.add_argument("key")
    p_unb.set_defaults(func=cmd_unbind)

    p_stats = sub.add_parser("stats", help="license statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    db = LicenseDB()
    args.func(db, args)


if __name__ == "__main__":
    main()
