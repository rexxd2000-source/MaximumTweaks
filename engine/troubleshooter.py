"""Troubleshooting brain for the assistant.

Deterministic, fully-local triage: given a plain-text description of a
problem, figure out which applied tweak (or combination) is the likeliest
culprit on *this* machine, folding together:

  * what is actually applied (engine/state) and live-active (state_checker),
  * each tweak's validation metadata (status / evidence / verdict / note)
    and declared conflicts (already merged into ``t["conflicts"]`` by
    database/validation.apply()),
  * a curated failure-mode table for the audited high-risk set (GPU
    PowerMizer pins, the timer-resolution cluster, MMCSS over-tuning, TDR
    registry edits, network-throttling writers, USB power tweaks, ...),
  * and symptom keywords recovered from each tweak's own warn/changes/why
    text, so tweaks that self-describe a failure mode get blame without a
    hand entry.

The result is structured (ranked suspects with reasons + revert hints) so
both the offline router and the LLM provider answer from the same facts.
No network, no external APIs.
"""
from __future__ import annotations

import re

from database import BY_ID, TWEAKS
from engine import state as state_mgr
from engine import state_checker
from maxlog import logger


# ---------------------------------------------------------------------------
# Symptom groups: keywords matched against the user's description AND against
# each tweak's own warn/changes/why text (so data stays self-describing).
# ---------------------------------------------------------------------------

_GROUPS: dict[str, list[str]] = {
    "gpu_performance": [
        r"\bfps\b", r"\bframe", r"\bstutter", r"microstutter", r"\bhitch",
        r"\bdrop", r"\bdip", r"laggy", r"\bslow(?:er|est|ly)?\b",
        r"sluggish", r"60\b", r"low fps", r"frametime", r"frame rate",
        r"fps drop",
    ],
    "network": [
        r"\bping\b", r"latency", r"\blag\b", r"packet", r"jitter",
        r"rubber-?band", r"timeout", r"disconnect", r"internet",
        r"\bwifi\b", r"wi-?fi", r"throttl", r"upload", r"download",
        r"spike",
    ],
    "crash_freeze": [
        r"\bcrash", r"bsod", r"blue screen", r"freeze", r"\bhang",
        r"restart", r"reboot", r"black screen", r"error code",
        r"closing", r"shutdown", r"turning off", r"random reset",
    ],
    "boot": [
        r"\bboot", r"startup", r"sign-?in", r"\blogin", r"slow to start",
        r"welcome",
    ],
    "audio": [
        r"audio", r"sound", r"crackl", r"popping", r"microphone",
        r"\bmic\b", r"distort", r"glitchy", r"echo",
    ],
    "usb": [
        r"\busb\b", r"device disconnected", r"\bmouse\b", r"keyboard",
        r"controller", r"peripheral", r"unplug", r"device not recognized",
    ],
    "thermal": [
        r"\bhot\b", r"temperature", r"\btemp\b", r"thermal", r"overheat",
        r"throttl", r"fans", r"cooler",
    ],
}

_GROUP_RE = {g: re.compile("|".join(exprs), re.I) for g, exprs in _GROUPS.items()}

# Cached symptom scan of each tweak's own warn/changes/why text.
_self_hits_cache: dict[str, dict[str, int]] = {}

# Symptom group -> registry target affinity (from validation TARGET field).
_TARGET_AFFINITY = {
    "gpu_performance": "GPU",
    "network": "NETWORK",
    "audio": "AUDIO",
    "usb": "USB",
}


def match_groups(text: str) -> dict[str, int]:
    """Map a chunk of text to symptom groups with a small hit count."""
    if not text:
        return {}
    hits: dict[str, int] = {}
    for group, rx in _GROUP_RE.items():
        n = len(rx.findall(text))
        if n:
            hits[group] = min(n, 3)
    return hits


def looks_like_problem(text: str) -> bool:
    """True when the question reads like "something is wrong on my PC"."""
    if not text:
        return False
    q = text.lower()
    if match_groups(q):
        return True
    return any(k in q for k in (
        "why", "issue", "problem", "broken", "acting", "worse",
        "not working", "trouble", "fix", "anything wrong", "suspect",
        "is it safe", "causing", "cause",
    ))


# ---------------------------------------------------------------------------
# Curated failure-mode table for the audited high-risk set. Every entry is a
# dict of {symptom_group: weight} plus an optional "why" blurb. These are the
# tweaks the 500->60->500 FPS-collapse investigation hand-verified; the rest
# of the DB is blamed via its own metadata + self-description scan.
# ---------------------------------------------------------------------------

POWERMIZER_WHY = ("undocumented GPU PowerMizer/PerfLevelSrc write - on driver "
                  "builds that honor it the GPU can pin to a low clock state "
                  "and drop frames hard (the exact 500->60->500 pattern). "
                  "Flagged REMOVE/INVALID in the audit.")

TIMER_CLUSTER_WHY = ("the single optional Timer Resolution Diagnostic "
                     "(perf-001) only permits high-resolution timer requests; "
                     "it does not force 0.5 ms pacing, so any latency gain is "
                     "hardware-specific and should be benchmarked.")

TDR_WHY = ("TDR registry edits just raise the GPU watchdog timeout - they can "
           "turn a quick driver recovery into a long freeze instead of "
           "fixing the underlying stall.")

CURATED: dict[str, dict] = {
    "nv-003": {"gpu_performance": 65, "crash_freeze": 25, "thermal": 15,
               "why": POWERMIZER_WHY},
    "perf-001": {"gpu_performance": 55, "audio": 20, "why": TIMER_CLUSTER_WHY},
    "mmcss_game_priority": {"gpu_performance": 30, "audio": 25,
                            "why": ("MMCSS Games task to high priority; "
                                    "over-tuning can starve background work.")},
    "pre-006": {"gpu_performance": 20, "audio": 25,
                "why": ("SystemResponsiveness=10 gives games more CPU by "
                        "starving background tasks - on a busy system this "
                        "appears as background/audio stutter.")},
    "gpu-003": {"crash_freeze": 55, "why": TDR_WHY},
    "gpu-018": {"crash_freeze": 50, "why": TDR_WHY},
    "gpu-019": {"crash_freeze": 50, "why": TDR_WHY},
    "net-009": {"network": 55,
                "why": ("NetworkThrottlingIndex writes can cut bandwidth the "
                        "game sees from the system\'s throttling limit.")},
    "pre-003": {"network": 50, "why": ("NetworkThrottlingIndex writer (see "
                                       "net-009).")},
    "pre-005": {"network": 50, "why": ("NetworkThrottlingIndex writer (see "
                                       "net-009).")},
    "dd-019": {"usb": 40,
               "why": ("USBSelectiveSuspendDelay=5 can make USB devices "
                       "disconnect/relink in a hurry.")},
}

# Structural grid for anything not hand-curated.
_RISK = {"safe": 0, "low": 10, "moderate": 35, "advanced": 55}
_VERDICT = {"REMOVE": 70, "INVALID": 60, "OUTDATED": 15, "REVIEW": 0, "SHIP": 0}
_STATUS = {"CONFLICTING": 45, "INVALID": 45, "OUTDATED": 10, "PLACEBO": 10}
_CATEGORY_BLINDS = {
    "Network": 35, "Wi-Fi": 35, "Ethernet": 35,
    "Audio": 45, "USB": 40,
}
# category -> symptom group that makes that category relevant.
_CATEGORY_GROUP = {
    "Network": "network", "Wi-Fi": "network", "Ethernet": "network",
    "Audio": "audio", "USB": "usb",
}


def _revert_hint(t: dict) -> str:
    r = t.get("revert") or []
    if not r:
        return "its Revert button on the Tweaks page"
    try:
        a = r[0]
        kind = a[0]
        if kind in ("regdel", "regdelall"):
            return f"deletes registry value {a[3]!r}"
        if kind == "regkeydel":
            return f"deletes the registry key {a[2]!r}"
        if kind == "reg":
            return f"rewrites registry value {a[3]!r} to {a[4]!r}"
        if kind == "svc":
            return f"returns service {a[1]!r} to {a[2]}"
        if kind in ("svcstart", "svcstop"):
            return f"reverses service {a[1]!r} start state"
        if kind == "power":
            return f"restores power setting {a[1]!r}"
        if kind == "ini":
            return f"resets {a[2]!r} [{a[3]}] {a[4]}"
        return "its Revert button on the Tweaks page"
    except Exception:  # noqa: BLE001
        return "its Revert button on the Tweaks page"


def _status_blurb(t: dict) -> str | None:
    status = t.get("status")
    verdict = t.get("verdict")
    note = (t.get("validation_note") or "").strip()
    if verdict in ("REMOVE", "INVALID") or status in ("INVALID", "OUTDATED", "PLACEBO"):
        base = (f"flagged {status}/{verdict} - blocked from auto-apply"
                if status in ("INVALID", "OUTDATED", "PLACEBO")
                else f"flagged {verdict} ({status}) - not safe to auto-apply")
        return f"{base}." + (f" {note}" if note and "Conflicts" not in note else "")
    if status == "CONFLICTING":
        return f"conflicts with other tweaks - {note}" if note else "status CONFLICTING"
    if status == "UNKNOWN" and verdict == "REVIEW":
        return "low-evidence review tweak (UNKNOWN status)"
    if note:
        return note
    return None


def _check_live(tid: str) -> bool | None:
    try:
        return state_checker.check_id(tid)
    except Exception:  # noqa: BLE001
        return None


def _suspect(t: dict, applied: set[str], applied_at: dict,
             desc_hits: dict[str, int], self_hits: dict[str, int],
             live_cache: dict[str, bool | None]) -> dict | None:
    """Score one tweak; return a suspect record when it clears the bar."""
    tid = t["id"]
    base = _RISK.get(t.get("risk", "low"), 10)
    base += _VERDICT.get(t.get("verdict", "SHIP"), 0)
    base += _STATUS.get(t.get("status", "VALID"), 0)
    if t.get("recommended") in ("not_recommended", "experimental"):
        base += 25

    curated = CURATED.get(tid)
    is_applied = tid in applied
    why_parts: list[str] = []
    conflict_rows = t.get("conflicts") or []

    # No symptom recognized -> fall back to a pure risk/verdict ranking
    # (applied tweaks first). Good for "something is off" / audit questions.
    if not desc_hits:
        score = base
        if is_applied:
            score = score * 1.8 + 15
        live = live_cache.get(tid, "unprobed")
        if live is True:
            score += 45
            if not is_applied:
                why_parts.append(
                    "value is live on this system even though the app has no "
                    "apply record for it")
        applied_conflicts = [c for c in conflict_rows if c.get("with") in applied]
        if applied_conflicts:
            score += 45
            for c in applied_conflicts[:2]:
                why_parts.append(f"conflicts with {c['with']}: {c.get('reason', '')}")
        if score < 35:
            return None
        if not why_parts:
            blurb = _status_blurb(t)
            if blurb:
                why_parts.append(blurb)
        return _record(t, applied, applied_at, score, is_applied, why_parts,
                       conflict_rows, live_cache)

    # Symptom-driven scoring: the higher a tweak's fit against the reported
    # symptom, the higher it ranks - applied/live state adds real evidence.
    dominant = max(desc_hits, key=desc_hits.get)

    # Hand-curated failure knowledge, but only when it actually covers the
    # dominant symptom - otherwise a GPU-clock tweak would crowd out an
    # audio complaint that merely mentioned "stuttery".
    if curated and dominant in curated:
        why = curated.get("why")
        if why:
            why_parts.append(why)
        fit = sum(w * desc_hits[g]
                  for g, w in curated.items()
                  if g != "why" and g in desc_hits)
    else:
        fit = 0

    for g, hits in self_hits.items():
        if g in desc_hits:
            fit += int(12 * hits)

    cg = _CATEGORY_GROUP.get(t.get("category", ""))
    if cg in desc_hits and t.get("category") in _CATEGORY_BLINDS:
        fit += _CATEGORY_BLINDS[t.get("category")]

    target = t.get("target")
    for g, tgt in _TARGET_AFFINITY.items():
        if g in desc_hits and target == tgt:
            fit += 12

    # Live registry really shows the value -> real evidence. Only the applied
    # set and flagged/curated tweaks are live-checked (prewarmed once by
    # diagnose()); anything absent from the cache was not worth probing.
    live = live_cache.get(tid, "unprobed")
    if live is True:
        proof_bonus = base + 45
        if not is_applied:
            why_parts.append(
                "the value it writes is live on this system even though the "
                "app has no apply record for it - something else (or an "
                "older run) may have set it.")
    else:
        proof_bonus = base

    applied_conflicts = [c for c in conflict_rows if c.get("with") in applied]
    if applied_conflicts:
        proof_bonus += 55
        for c in applied_conflicts[:2]:
            why_parts.append(f"conflicts with {c['with']}: {c.get('reason', '')}")

    if is_applied:
        proof_bonus += 80 if fit else 50

    # A tweak with zero connection to the reported symptom, not applied and
    # not live is irrelevant to THIS complaint - drop it so unrelated flags
    # and inherited game settings don't pollute the answer.
    if not fit and not is_applied and live is not True:
        return None

    score = int(fit * 1.5 + proof_bonus)

    if not why_parts:
        blurb = _status_blurb(t)
        if score >= 40 and blurb:
            why_parts.append(blurb)

    # Silence the tail.
    if score < (30 if is_applied else 60):
        return None

    return _record(t, applied, applied_at, score, is_applied, why_parts,
                   conflict_rows, live_cache)


def _record(t: dict, applied: set[str], applied_at: dict, score: float,
            is_applied: bool, why_parts: list[str], conflict_rows: list[dict],
            live_cache: dict[str, bool | None]) -> dict:
    tid = t["id"]
    live = live_cache.get(tid)
    state_txt = (f"APPLIED {applied_at.get(tid)}"
                 if is_applied else "not applied")
    live_txt = (", live on disk" if live is True else "")
    why = "; ".join(dict.fromkeys(w for w in why_parts if w)) or (
        "no strong signal - listed because of its risk/verdict profile")
    return {
        "id": tid,
        "name": t.get("name", tid),
        "score": int(round(score)),
        "applied": is_applied,
        "live": live,
        "state": state_txt + live_txt,
        "why": why,
        "revert": _revert_hint(t),
        "conflicts_with": sorted({c.get("with", "") for c in conflict_rows}),
    }


def _answer_text(desc: str, suspects: list[dict],
                 applied_ids_set: set[str]) -> str:
    if not suspects:
        if not applied_ids_set:
            return ("Nothing is recorded as applied and no tweak is live on "
                    "this system that matches that symptom - so this looks "
                    "driver/Windows-side rather than a tweak issue. Clean "
                    "driver reinstall, check temps, and run with the app's "
                    "optimizers off to confirm. If the drop is in one game, "
                    "also check its shader cache / V-Sync cap first.")
        return ("None of the applied tweaks are a believable cause for that "
                "either - reason to look at drivers, GPU thermals, or the "
                "game itself first (transient shader-compile hitches and "
                "V-Sync caps cause exactly this). If anything changed, start "
                "by reverting the tweaks you applied last.")
    lines = [f"Here's what I'd check, in order for \"{desc}\":"]
    for i, s in enumerate(suspects, 1):
        tag = "APPLIED" if s["applied"] else "NOT-APPLIED"
        lines.append(
            f"{i}) [{s['id']}] {s['name']}  ({tag}, score {s['score']})\n"
            f"   {s['state']}.\n"
            f"   Why: {s['why']}\n"
            f"   Revert: {s['revert']}")
    lines.append("")
    lines.append("Test one revert at a time: revert -> reboot if it touched "
                 "HKLM/services -> benchmark -> next. If the top suspects are "
                 "'not applied' but live on disk, check them too - something "
                 "outside the app may have set them.")
    return "\n".join(lines)


def diagnose(description: str) -> str:
    """Return a ranked, revert-first troubleshooting answer (plain text)."""
    desc = (description or "").strip()
    if not desc:
        return ("Tell me what's happening - e.g. 'FPS drops from 500 to 60 "
                "and back', 'high ping in game', 'crashes to desktop', "
                "'slow boot after applying tweaks'.")
    try:
        applied_set = state_mgr.applied_ids()
        applied_at = {tid: (state_mgr.applied_at(tid) or "?")
                      for tid in applied_set}
        desc_hits = match_groups(desc)
        # Only live-check the applied set + curated/flagged tweaks: cheap.
        flagged_tids = set(CURATED) | {
            t["id"] for t in TWEAKS
            if t.get("verdict") in ("REMOVE", "INVALID")
            or t.get("status") in ("INVALID", "CONFLICTING", "OUTDATED")}
        live_cache: dict[str, bool | None] = {
            tid: _check_live(tid)
            for tid in sorted(applied_set | flagged_tids)
            if tid in BY_ID}

        scored: list[dict] = []
        for t in TWEAKS:
            tid = t["id"]
            self_hits = _self_hits_cache.get(tid)
            if self_hits is None:
                self_hits = match_groups(
                    " ".join([str(t.get("warn") or ""),
                              str(t.get("changes") or ""),
                              str(t.get("why") or "")]))
                _self_hits_cache[tid] = self_hits
            if not (met := _suspect(t, applied_set, applied_at, desc_hits,
                                    self_hits, live_cache)):
                continue
            scored.append(met)

        scored.sort(key=lambda s: (-s["score"], not s["applied"], s["id"]))
        top = scored[:6]
        return _answer_text(desc, top, applied_set)
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"troubleshooter.diagnose: {type(exc).__name__}: {exc}")
        return ("I hit an error while reading the system state "
                f"({type(exc).__name__}). Try again, or check the app log.")


def applied_risk_report() -> str:
    """Quick triage of whatever is applied right now, ranked by risk."""
    try:
        applied_set = state_mgr.applied_ids()
        if not applied_set:
            return "No tweaks are recorded as applied on this system."
        rows = []
        for tid in sorted(applied_set):
            t = BY_ID.get(tid)
            if t is None:
                rows.append((0, f"[{tid}] (unknown tweak id)"))
                continue
            score = _RISK.get(t.get("risk", "low"), 10)
            score += _VERDICT.get(t.get("verdict", "SHIP"), 0)
            score += _STATUS.get(t.get("status", "VALID"), 0)
            extras = []
            blurb = _status_blurb(t)
            if blurb:
                extras.append(blurb)
            for c in (t.get("conflicts") or []):
                if c.get("with") in applied_set:
                    extras.append(f"conflicts-with {c['with']}: {c.get('reason', '')}")
            rows.append((score, (f"[{tid}] {t.get('name')} - "
                                 f"risk {t.get('risk')}, "
                                 f"{t.get('status')}/{t.get('verdict')}"
                                 + (f"; {'; '.join(extras)}" if extras else ""))))
        rows.sort(key=lambda r: -r[0])
        return ("Riskiest applied tweaks first:\n" +
                "\n".join(f"{i}) {txt}" for i, (_, txt) in enumerate(rows, 1)))
    except Exception as exc:  # noqa: BLE001
        logger.warn(f"troubleshooter.applied_risk_report: "
                    f"{type(exc).__name__}: {exc}")
        return f"I couldn't read the applied-tweak state ({type(exc).__name__})."