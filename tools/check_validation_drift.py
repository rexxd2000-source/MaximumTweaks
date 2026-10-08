"""List validation override ids that are no longer part of the shipped catalogue.

Run from the repo root:

    python tools/check_validation_drift.py

Prints the orphan count, the first 20 orphan ids, and a cross-check against
database/removed_tweaks.py (were the orphans deliberately removed tweaks, or
typos?). Exit code is 1 when orphans exist, so it can gate a script or CI.

Historical note: on 2026-10-08 this reported 0 orphans against the live
catalogue. The "295 stale overrides" figure that circulated before it came
from tests/test_subscriptions.py applying validation to a one-element sample
list (every override looks orphaned next to it), not from real drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import BY_ID  # noqa: E402
from database import validation as V  # noqa: E402
from database.removed_tweaks import REMOVED_TWEAKS  # noqa: E402


def main() -> int:
    live = set(BY_ID)
    orphans = sorted(V.orphaned_overrides())
    removed = set(REMOVED_TWEAKS)

    print(f"shipped catalogue (BY_ID): {len(live)}")
    print(f"validation OVERRIDES:      {len(V.OVERRIDES)}")
    print(f"validation NOTES:          {len(V.NOTES)}")
    print(f"orphan override ids:       {len(orphans)}")
    if orphans:
        print(f"first 20: {', '.join(orphans[:20])}")
    else:
        print("first 20: (none)")
    print(f"orphan ids also in removed_tweaks: {len(set(orphans) & removed)}")
    print(f"live ids also in removed_tweaks:   {len(live & removed)} (must be 0)")

    if orphans:
        print("DRIFT: delete the stale records in database/validation_data.py "
              "or restore the tweaks.")
        return 1
    print("OK: every override id exists in the shipped catalogue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
