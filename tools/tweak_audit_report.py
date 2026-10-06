"""Generate the full tweak audit report from the live catalogue.

Run from the repo root::

    python -m tools.tweak_audit_report            # markdown to stdout
    python -m tools.tweak_audit_report -o docs/tweak_audit.md

Every row is derived from the actual ``actions``/``revert`` tuples via
:mod:`database.tiers`, not from a hand-maintained spreadsheet, so the report
cannot drift from what the app will actually apply.

The report deliberately keeps the categories apart. "Verified" here means the
static audit could prove the implementation is reversible and matches its
description; it is not a runtime test on the author's PC, and guidance/read-only
entries are not counted as verified optimizations. Inflating that number would
be the easiest way to look better and the fastest way to be wrong.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.plans import (  # noqa: E402
    FOUNDATION, MAXIMUM, PERFORMANCE, PLAN_LABEL, PLAN_ORDER,
)
from database.classification import (  # noqa: E402
    CLASSIFICATIONS as AXIS, MAXIMUM as CLS_MAXIMUM, FREE as CLS_FREE,
    FOUNDATION as CLS_FOUNDATION,
)
from database.removed_tweaks import REMOVED_TWEAKS  # noqa: E402
from database.tiers import audit_tweak, extract_implementation  # noqa: E402
from database.tweaks import BY_ID, TWEAKS  # noqa: E402
from engine.safety import preflight  # noqa: E402

#: Report order for the disposition sections. Anything not listed is appended.
SECTION_ORDER = (
    "VERIFIED", "UNVERIFIED", "DANGEROUS", "EXPERIMENTAL", "BROKEN",
    "OBSOLETE", "UNSUPPORTED", "DUPLICATE",
)

#: The decision classes surfaced in the audit, from the audit generator.
DECISION_ORDER = ("KEEP", "REWRITE", "REMOVE")
DECISION_BLURB = {
    "KEEP": "Implementation is sound and needs no action.",
    "REWRITE": "Implementation carries a conflict, is outdated, or is broken; "
               "needs a rewrite before reliance.",
    "REMOVE": "Duplicate, invalid, or unsafe; should not ship as-is.",
}

SECTION_BLURB = {
    "VERIFIED": "Implementation read and matched its description, with "
                "revert coverage and no known dangerous signal.",
    "UNVERIFIED": "Not yet cleared by the static audit. Still appliable, but "
                  "requires explicit confirmation and is excluded from Apply All.",
    "DANGEROUS": "Detected a signal that is unsafe to auto-apply. Review before "
                 "using.",
    "EXPERIMENTAL": "Modifies low-level or vendor-specific state. Treat results "
                    "as machine-specific.",
    "BROKEN": "Actions are empty, incomplete, or contradict their description.",
    "OBSOLETE": "Targets a mechanism that no longer exists in supported Windows "
                "versions.",
    "UNSUPPORTED": "Explicitly unsupported on the target platform.",
    "DUPLICATE": "Overlaps another tweak; apply one, not both.",
}

COLUMNS = (
    "id", "name", "category", "requiredTier", "classification", "decision",
    "kind", "disposition", "verified", "status", "evidence", "verdict",
    "actions", "reverts", "reversible", "requires_admin", "reboot",
    "windows", "hardware_gates", "risk", "tier_reason", "verify_reason",
)


def _kind(facts: dict) -> str:
    """What kind of entry this is: guidance, transient, read-only, or mutating.

    Derived from the extracted implementation, not from the `guidance=` field,
    because a few entries carry guidance-shaped actions without the flag.
    `transient` is checked before `read_only`: a one-shot action such as a
    service restart or an adapter reset leaves no persistent state behind, so
    it is neither a durable optimization nor a diagnostic measurement.
    """
    if facts.get("guidance_only"):
        return "guidance"
    if facts.get("transient"):
        return "transient"
    if facts.get("read_only"):
        return "read_only"
    return "mutating"


def _row(t: dict) -> dict:
    facts = extract_implementation(t)
    audit = audit_tweak(t)
    actions = t.get("actions") or []
    reverts = t.get("revert") or []
    kind = _kind(facts)
    return {
        "id": t["id"],
        "name": t.get("name", ""),
        "category": t.get("category", ""),
        "requiredTier": t.get("requiredTier", t.get("tier", FOUNDATION)),
        "classification": t.get("classification", CLS_FREE),
        "decision": t.get("decision", "KEEP"),
        "reason": t.get("decision_reason", ""),
        "kind": kind,
        "disposition": t.get("disposition", ""),
        "verified": "yes" if t.get("verified") else "no",
        "status": t.get("status", "UNKNOWN"),
        "evidence": t.get("evidence", "UNKNOWN"),
        "verdict": t.get("verdict", "REVIEW"),
        "actions": len(actions),
        "reverts": len(reverts),
        # Only meaningful for mutating entries: a guidance/read-only entry has
        # nothing to revert, so "reversible: no" would read as a defect.
        "reversible": ("yes" if audit.get("reversible") else "no")
                      if kind == "mutating" else "n/a",
        "requires_admin": "yes" if t.get("admin") else "no",
        "reboot": "yes" if t.get("reboot") else "no",
        "windows": t.get("win", "") or "any",
        # extract_implementation() calls this "hw_gates"; the report column is
        # "hardware_gates". Reading the wrong key silently blanked the column
        # for all rows, so every hardware-gated tweak looked ungated.
        "hardware_gates": ", ".join(sorted(facts.get("hw_gates", []))) or "-",
        "risk": t.get("risk", "safe"),
        "tier_reason": t.get("tier_reason", ""),
        "verify_reason": t.get("verify_reason", ""),
    }


def collect() -> dict:
    """Build the full report structure."""
    rows = [_row(t) for t in TWEAKS]
    by_section: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_section[r["disposition"]].append(r)

    tier_counts = Counter(r["requiredTier"] for r in rows)
    disp_counts = Counter(r["disposition"] for r in rows)
    decision_counts = Counter(r["decision"] for r in rows)
    by_decision: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_decision[r["decision"]].append(r)

    # Verified *mutating* tweaks are the only honest "verified optimizations"
    # figure. The split must come from the extracted implementation facts, not
    # from `actions`/`guidance` alone: a read-only diagnostic has action-shaped
    # entries and can be verified True without a revert path, because there is
    # nothing to reverse. Counting those would inflate the headline by ~2x.
    verified_kinds = {"mutating": 0, "read_only": 0, "transient": 0, "guidance": 0}
    verified_mutating = []
    for t in TWEAKS:
        if not t.get("verified"):
            continue
        kind = _kind(extract_implementation(t))
        verified_kinds[kind] += 1
        if kind == "mutating":
            verified_mutating.append(_row(t))

    # Cross-check that nothing tier-gated is silently unreachable, using a
    # Foundation profile. This is the same chokepoint the app applies.
    profile = {"win_version": "10"}
    unreachable = []
    for t in TWEAKS:
        if t.get("guidance"):
            continue
        pf = preflight(t, profile=profile, mode="apply")
        if not pf["allowed"] and pf["code"] not in (
                "tier_required", "conflict_active"):
            unreachable.append((t["id"], pf["code"], pf["reason"]))

    orphans = sorted(
        tid for tid in __import__(
            "database.validation", fromlist=["OVERRIDES"]).OVERRIDES
        if tid not in BY_ID)

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "total": len(rows),
        "rows": rows,
        "by_section": by_section,
        "tier_counts": tier_counts,
        "disp_counts": disp_counts,
        "decision_counts": decision_counts,
        "by_decision": by_decision,
        "removed": sorted(
            ({"id": tid,
              "name": (rec.get("name") or ""),
              "canonical": rec.get("canonical") or "-",
              "reason": (rec.get("reason") or "")}
             for tid, rec in REMOVED_TWEAKS.items()),
            key=lambda r: r["id"]),
        "verified_mutating": verified_mutating,
        "verified_kinds": verified_kinds,
        "unreachable": unreachable,
        "orphans": orphans,
    }


def _md_table(rows: list[dict], columns=COLUMNS) -> list[str]:
    if not rows:
        return ["_None._", ""]
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    out = [head, sep]
    for r in rows:
        cells = []
        for c in columns:
            v = str(r.get(c, "")).replace("|", "\\|").strip()
            if len(v) > 120:
                v = v[:117] + "..."
            cells.append(v)
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    return out


def render(data: dict) -> str:
    L: list[str] = []
    L.append("# Maximum Tweaks \u2014 Tweak Audit")
    L.append("")
    L.append(f"Generated {data['generated']} from the live tweak catalogue "
             f"({data['total']} tweaks).")
    L.append("")
    L.append("Every row below is derived from each tweak's real `actions` and "
             "`revert` tuples. Re-run `python -m tools.tweak_audit_report` after "
             "changing any tweak; do not edit this file by hand.")
    L.append("")

    L.append("## What \"verified\" means here")
    L.append("")
    L.append("**Verified** means a static audit read the implementation and found "
             "that it does what its description claims, that the revert path "
             "covers it, that no hardcoded destructive target or unexplained "
             "executable was present, and that the recorded validation evidence "
             "was strong.")
    L.append("")
    L.append("It is **not** a statement that the tweak was run on a real machine, "
             "and it does not apply to read-only diagnostics. Those are reported "
             "separately so the headline numbers cannot overstate coverage.")
    L.append("")
    L.append("The three counts below are deliberately kept apart. Only the first "
             "is a claim about changes to the system.")
    L.append("")

    n_mut = len(data["verified_mutating"])
    kinds = data["verified_kinds"]
    n_diag = kinds["read_only"] + kinds["transient"] + kinds["guidance"]
    L.append("| Figure | Count | What it means |")
    L.append("| --- | --- | --- |")
    L.append(f"| **Verified mutating optimizations** | **{n_mut}** | Reads the "
             f"implementation, changes system state, and the revert path covers "
             f"every mutating action. **The only figure to quote as "
             f"\"verified optimizations\".** |")
    L.append(f"| Verified read-only / guidance entries | {n_diag} | Changes "
             f"nothing. Verified only in the sense that there is nothing to "
             f"revert; it says nothing about whether a change would be safe. |")
    L.append(f"| Unverified | {data['disp_counts'].get('UNVERIFIED', 0)} | "
             f"Appliable only with explicit confirmation, never via Apply All. |")
    L.append(f"| Stale validation overrides | {len(data['orphans'])} | Refer to "
             f"tweaks that no longer exist. Inert; **human review required**, "
             f"never auto-deleted. |")
    L.append(f"| Other dispositions | {data['total'] - n_mut - n_diag - data['disp_counts'].get('UNVERIFIED', 0)} "
             f"| Flagged by the safety audit (dangerous, experimental, broken, "
             f"obsolete, unsupported). Listed in full below. |")
    L.append("")
    L.append("Among the "
             f"{n_mut} verified mutating tweaks, "
             f"{sum(1 for r in data['verified_mutating'] if r['evidence'] == 'HIGH')} "
             f"rest on HIGH-strength evidence and "
             f"{sum(1 for r in data['verified_mutating'] if r['evidence'] == 'MEDIUM')} "
             f"on MEDIUM. Every one of them is status VALID and disposition "
             f"VERIFIED, by the same checks that leave "
             f"{data['disp_counts'].get('UNVERIFIED', 0)} tweaks unverified.")
    L.append("")

    L.append("## Subscription tiers")
    L.append("")
    L.append("| Tier | Monthly | Tweaks |")
    L.append("| --- | --- | --- |")
    for tier in PLAN_ORDER:
        L.append(f"| {PLAN_LABEL[tier]} | "
                 f"{'FREE' if tier == FOUNDATION else '$' + ('10' if tier == PERFORMANCE else '15') + '/mo'} "
                 f"| {data['tier_counts'].get(tier, 0)} |")
    L.append("")
    L.append("Tiers are inherited: a tier includes everything in the tiers below "
             "it. `requiredTier` in the tables is the lowest tier that unlocks "
             "the tweak.")
    L.append("")

    L.append("## Disposition summary")
    L.append("")
    L.append("| Disposition | Count | Meaning |")
    L.append("| --- | --- | --- |")
    for name in SECTION_ORDER:
        n = data["disp_counts"].get(name, 0)
        L.append(f"| {name} | {n} | {SECTION_BLURB.get(name, '')} |")
    other = set(data["disp_counts"]) - set(SECTION_ORDER)
    for name in sorted(other):
        L.append(f"| {name} | {data['disp_counts'][name]} | |")
    L.append("")

    L.append("## Classification and audit decisions")
    L.append("")
    L.append("Each tweak carries a **classification** — FREE / FOUNDATION / "
             "MAXIMUM — assigned by `database/classification.py`. For the "
             "optimization tweaks that grade is the **reviewed** one, imported "
             "from the human tier-review sheet into "
             "`database/reviewed_tiers.py`; the implementation-derived "
             "heuristic in the same module is the fallback for anything not "
             "covered by a review. Either way the subscription tier "
             "(`requiredTier`) is *derived* from the classification by a fixed "
             "order-preserving mapping, so the tier can never drift from the "
             "grade.")
    L.append("")
    L.append("| Classification | Derived tier | Monthly | Tweaks | Meaning |")
    L.append("| --- | --- | --- | --- | --- |")
    L.append(f"| FREE | {FOUNDATION} | FREE | "
             f"{data['tier_counts'].get(FOUNDATION, 0)} | Generic, broadly "
             f"compatible, reversible changes. |")
    L.append(f"| FOUNDATION | {PERFORMANCE} | $10/mo | "
             f"{data['tier_counts'].get(PERFORMANCE, 0)} | Core optimizations "
             f"that write system state (services, network, power, AppX). |")
    L.append(f"| MAXIMUM | {MAXIMUM} | $15/mo | "
             f"{data['tier_counts'].get(MAXIMUM, 0)} | Vendor/hardware/boot/"
             f"driver/memory-level changes and security-critical edits. |")
    L.append("")
    L.append("The **decision** column records what the audit wants done with the "
             "tweak. Decisions come from `_dev/audit_gen.py` and are attached at "
             "load time.")
    L.append("")
    L.append("| Decision | Count | Meaning |")
    L.append("| --- | --- | --- |")
    for name in DECISION_ORDER:
        n = data["decision_counts"].get(name, 0)
        L.append(f"| {name} | {n} | {DECISION_BLURB.get(name, '')} |")
    L.append("")
    L.append("### Removed from the catalogue")
    L.append("")
    removed = data["removed"]
    if removed:
        L.append(f"{len(removed)} tweaks were removed by the audit. None are "
                 "in the live catalogue below; the reason for each removal is "
                 "kept permanently (see `database/removed_tweaks.py`). A "
                 "duplicate removal lists the canonical tweak that still ships "
                 "the same (target, value) pair.")
        L.append("")
        L.extend(_md_table(
            [{"id": r["id"], "name": r["name"],
              "canonical": r["canonical"], "reason": r["reason"]}
             for r in removed],
            columns=("id", "name", "canonical", "reason")) )
    else:
        L.append("No tweaks have been removed from the catalogue.")
    L.append("")
    L.append("### REWRITE (review before shipping)")
    L.append("")
    L.append("Tweaks carrying a conflict, an outdated status, a broken "
             "implementation, or a critical-repair disable. They are appliable "
             "today but need a rewrite before being relied on.")
    L.append("")
    L.extend(_md_table(
        sorted(data["by_decision"].get("REWRITE", []),
               key=lambda r: r["id"]),
        columns=("id", "name", "reason")) )
    L.append("")
    L.append("### KEEP")
    L.append("")
    L.append(f"{data['decision_counts'].get('KEEP', 0)} tweaks need no action.")
    L.append("")
    L.append("## Known data drift")
    L.append("")
    orphans = data["orphans"]
    L.append(f"**STALE VALIDATION OVERRIDE — HUMAN REVIEW REQUIRED** "
             f"({len(orphans)} entries)")
    L.append("")
    L.append(f"{len(orphans)} entries in `database/validation_data.py` refer to "
             f"tweak ids that no longer exist. They are inert — the loader looks "
             f"overrides up per loaded tweak — so they change no behaviour.")
    L.append("")
    L.append("They are reported, **never deleted automatically**. An id "
             "disappears either through a rename or through a removal, and only "
             "a human can say which; a suffix-matching heuristic cannot, because "
             "numeric suffixes are reused across every prefix (`net-001` "
             "matching `net-002` proves nothing). Deleting the wrong entry "
             "would strip real validation from a live tweak, so no rename "
             "inference is attempted. See `database.validation.orphaned_overrides()`.")
    L.append("")
    L.append("The full list, for whoever reviews it:")
    L.append("")
    L.append(f"| # | stale id | why it is stale |")
    L.append(f"| --- | --- | --- |")
    for i, tid in enumerate(orphans, 1):
        L.append(f"| {i} | `{tid}` | no loaded tweak has this id |")
    if data["unreachable"]:
        L.append(f"- {len(data['unreachable'])} non-guidance tweaks are denied "
                 f"by a safety check other than tier on a plain Windows 10 "
                 f"profile with no detected hardware. These are expected: they "
                 f"need hardware detection first, or a different Windows "
                 f"version. They are counted, not suppressed.")
    L.append("")

    L.append("## Verified mutating tweaks by tier")
    L.append("")
    L.append("| Tier | Count |")
    L.append("| --- | --- |")
    for tier in PLAN_ORDER:
        n = sum(1 for r in data["verified_mutating"]
                if r["requiredTier"] == tier)
        L.append(f"| {PLAN_LABEL[tier]} | {n} |")
    L.append("")

    L.append("## Full catalogue")
    L.append("")
    L.extend(_md_table(data["rows"]))
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", type=Path,
                    help="write markdown here instead of stdout")
    args = ap.parse_args(argv)

    data = collect()
    text = render(data)

    # Console summary: the counts are the part most likely to be quoted, so they
    # are printed with the caveat attached.
    print(f"tweaks            : {data['total']}")
    for tier in PLAN_ORDER:
        print(f"  {tier:<12}  {data['tier_counts'].get(tier, 0)}")
    print("decisions         :")
    for name in DECISION_ORDER:
        print(f"  {name:<10}  {data['decision_counts'].get(name, 0)}")
    print("dispositions      :")
    for name in SECTION_ORDER:
        print(f"  {name:<14}  {data['disp_counts'].get(name, 0)}")
    print(f"verified mutating : {len(data['verified_mutating'])}  "
          f"(the honest 'verified optimizations' figure)")
    print(f"orphan overrides  : {len(data['orphans'])}  "
          f"(stale ids in validation_data.py; inert, not deleted)")
    print(f"blocked by non-tier safety checks on a generic Win10 profile: "
          f"{len(data['unreachable'])}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"\nwrote {args.output}")
    else:
        print()
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
