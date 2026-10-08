"""Hard release gate for the shipped tweak catalogue.

Run from the repo root:

    python tools/audit_tweak_db.py

Checks, in order:

  1. schema      - every category module re-validates: action shapes, known
                   kinds, allowed risk/impact flags, unique ids, core fields.
  2. duplicates  - no two tweaks share one normalized action signature. This
                   gates the 2026-10-08 "strictly exactly-once" consolidation
                   (595 -> 577): any future copy-paste twin fails CI.
  3. conflicts   - every load-detected conflict pair (same Windows setting,
                   different values, or write-vs-delete) carries an audited
                   resolution on at least one side, so a new disagreeing pair
                   cannot ship silently.
  4. safety      - no BROKEN tweak (applies a change it cannot undo), no
                   OBSOLETE tweak (OUTDATED validation record), no executable
                   outside the audited set.
  5. data drift  - no orphan validation overrides, no resurrected removed
                   tweaks, audit DECISIONS covering exactly the shipped ids.

Counts (dispositions, tiers, conflict pairs) are printed as information even
when the gate passes. DANGEROUS/EXPERIMENTAL are recorded dispositions of the
current catalogue, reported but not failed - they are deliberate product
decisions, not drift. Guidance-only cards are exempt from the duplicate check
(nothing they do can fight another tweak) and an empty signature means the
card mutates nothing, so it can never be a duplicate of a mutating card.

Exit code is 1 on any failed check, so it can gate a script or CI.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import BY_ID  # noqa: E402
from database import audit_data  # noqa: E402
from database import tiers  # noqa: E402
from database import validation as V  # noqa: E402
from database.removed_tweaks import REMOVED_TWEAKS  # noqa: E402
from database.tweaks._base import _validate_action, validate_module  # noqa: E402

CORE_FIELDS = ("id", "name", "category", "desc", "why", "actions", "revert",
               "risk", "when")

#: Keywords that mark a conflict resolution inside an audit reason, used when
#: the reason does not name the counterpart id directly.
_RESOLUTION_MARKS = ("conflict", "mutually exclusive", "opposite", "surfaced")


def _norm_scalar(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, str):
        return x.lower()
    return str(x)


def _norm_action(action) -> tuple:
    kind = str(action[0]).lower()
    parts = [kind]
    for i, x in enumerate(action[1:]):
        v = _norm_scalar(x)
        if kind == "cmd" and i == 0 and isinstance(v, str):
            v = re.sub(r"\bpowercfg\s+/h\b", "powercfg /hibernate", v)
        parts.append(v)
    return tuple(str(p) if not isinstance(p, (bool, int)) else p for p in parts)


def check_schema() -> list[str]:
    errors: list[str] = []
    by_module: dict[str, list[dict]] = defaultdict(list)
    for t in BY_ID.values():
        by_module[str(t.get("module") or "?")].append(t)
    for name in sorted(by_module):
        try:
            validate_module(name, by_module[name])
        except ValueError as exc:
            errors.append(str(exc))
    for tid, t in sorted(BY_ID.items()):
        for field in CORE_FIELDS:
            if field not in t:
                errors.append(f"{tid}: missing core field {field!r}")
        for a in list(t.get("actions", [])) + list(t.get("revert", [])):
            try:
                _validate_action(a, tid)
            except ValueError as exc:
                errors.append(str(exc))
    return errors


def check_duplicates() -> list[str]:
    groups: dict[tuple, list[str]] = defaultdict(list)
    for tid, t in BY_ID.items():
        actions = [a for a in t.get("actions", []) if a[0] != "guidance"]
        if not actions:
            continue  # guidance-only cards mutate nothing
        sig = tuple(sorted((_norm_action(a) for a in actions), key=repr))
        groups[sig].append(tid)
    errors = []
    for sig, ids in sorted(groups.items(), key=lambda kv: kv[1][0]):
        if len(ids) >= 2:
            names = ", ".join(f"{i} {BY_ID[i]['name']!r}" for i in sorted(ids))
            errors.append(f"duplicate action signature: {names}")
    return errors


def check_conflicts_documented() -> list[str]:
    conflicts = V._conflicts(list(BY_ID.values()))
    pairs = sorted({tuple(sorted((a, b[0])))
                    for a, lst in conflicts.items() for b in lst})
    errors = []
    for a, b in pairs:
        ra = str(audit_data.DECISIONS.get(a, {}).get("reason") or "").lower()
        rb = str(audit_data.DECISIONS.get(b, {}).get("reason") or "").lower()

        def _docs(reason: str, other: str) -> bool:
            return other in reason or any(m in reason for m in _RESOLUTION_MARKS)

        if not (_docs(ra, b) or _docs(rb, a)):
            errors.append(f"undocumented conflict: {a} <-> {b}")
    return errors


def check_safety() -> tuple[list[str], dict[str, list[str]]]:
    errors: list[str] = []
    info: dict[str, list[str]] = defaultdict(list)
    for tid, t in sorted(BY_ID.items()):
        facts = tiers.extract_implementation(t)
        rec = tiers.audit_tweak(t)
        disp = rec["disposition"]
        if facts["unknown_exes"]:
            errors.append(
                f"{tid}: executable outside the audited set: "
                + ", ".join(sorted(facts["unknown_exes"])))
        if disp == tiers.BROKEN:
            errors.append(f"{tid}: not reversible - {rec['verify_reason']}")
        elif disp == tiers.OBSOLETE:
            errors.append(f"{tid}: OUTDATED validation record")
        elif disp in (tiers.DANGEROUS, tiers.EXPERIMENTAL, tiers.UNSUPPORTED,
                      tiers.DUPLICATE):
            info[disp].append(tid)
    return errors, dict(info)


def check_drift() -> list[str]:
    errors: list[str] = []
    live = set(BY_ID)
    removed = set(REMOVED_TWEAKS)
    orphans = sorted(V.orphaned_overrides())
    if orphans:
        errors.append(
            f"{len(orphans)} orphan validation override ids: "
            + ", ".join(orphans[:20]))
    resurrection = sorted(live & removed)
    if resurrection:
        errors.append("live ids also in removed_tweaks: "
                      + ", ".join(resurrection))
    decisions = set(audit_data.DECISIONS)
    missing = sorted(live - decisions)
    extra = sorted(decisions - live)
    if missing:
        errors.append("shipped ids without an audit decision: "
                      + ", ".join(missing[:20]))
    if extra:
        errors.append("audit decisions for non-shipped ids: "
                      + ", ".join(extra[:20]))
    return errors


def main() -> int:
    failed = False

    def report(title: str, errors: list[str]) -> None:
        nonlocal failed
        if errors:
            failed = True
            print(f"FAIL {title} ({len(errors)})")
            for e in errors:
                print(f"     - {e}")
        else:
            print(f"ok   {title}")

    report("schema", check_schema())
    report("exactly-once duplicates", check_duplicates())
    report("conflict resolutions", check_conflicts_documented())
    safety_errors, safety_info = check_safety()
    report("safety (reversible, known executables, fresh records)",
           safety_errors)
    report("data drift", check_drift())

    dispositions = Counter(t.get("disposition") for t in BY_ID.values())
    conflicts = V._conflicts(list(BY_ID.values()))
    pairs = len({tuple(sorted((a, b[0])))
                 for a, lst in conflicts.items() for b in lst})
    print()
    print(f"shipped tweaks : {len(BY_ID)}")
    print(f"conflict pairs : {pairs} (all audited unless FAIL above)")
    for name in ("VERIFIED", "UNVERIFIED", "DANGEROUS", "EXPERIMENTAL",
                 "BROKEN", "OBSOLETE", "UNSUPPORTED", "DUPLICATE"):
        print(f"  {name:<13}: {dispositions.get(name, 0)}")
    for disp in sorted(safety_info):
        print(f"  {disp} ids: {', '.join(safety_info[disp])}")

    if failed:
        print("\nGATE FAILED")
        return 1
    print("\nGATE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
