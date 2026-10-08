"""Guard tests for the Fortnite / anti-cheat surface.

The stress-test report once claimed the Fortnite section is "ban-safe by
design". Code cannot prove a vendor's policy - but it can prove the factual
part the claim rests on: every shipped fn-* tweak only edits Fortnite's own
GameUserSettings.ini, and no tweak action anywhere in the catalogue targets
an anti-cheat process or service. If either stops being true, these tests
fail before anything ships.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import BY_ID  # noqa: E402
from database.tweaks.fortnite import INI_PATH  # noqa: E402

# Anti-cheat processes/services (Riot Vanguard's driver pair is vgc/vgk).
FORBIDDEN = re.compile(r"\b(?:EasyAntiCheat|BattlEye|vgc|vgk)\b", re.IGNORECASE)

EXPECTED_FN_IDS = {f"fn-{n:03d}" for n in range(11, 39)}


def _iter_action_strings(tweak):
    for field in ("actions", "revert"):
        for action in tweak.get(field) or []:
            for part in action:
                if isinstance(part, str):
                    yield field, action, part


def test_fortnite_section_is_exactly_the_28_config_tweaks():
    """fn-011..fn-038 are the shipped section; fn-001..010 and fn-039 are
    permanently removed (guidance-only or dropped config edits). Reintroducing
    or losing any id must be a conscious, reviewed change."""
    live = {tid for tid in BY_ID if tid.startswith("fn-")}
    assert live == EXPECTED_FN_IDS, (
        f"unexpected Fortnite ids: added={sorted(live - EXPECTED_FN_IDS)} "
        f"missing={sorted(EXPECTED_FN_IDS - live)}"
    )


def test_fortnite_tweaks_only_edit_their_own_ini():
    """Every fn-* action and revert must be an ini/inidel op inside
    GameUserSettings.ini - no registry, no services, no exe targets."""
    violations = []
    for tid in sorted(EXPECTED_FN_IDS):
        tweak = BY_ID[tid]
        for field in ("actions", "revert"):
            for action in tweak.get(field) or []:
                op = action[0] if action else None
                path = action[1] if len(action) > 1 else None
                if op not in ("ini", "inidel") or path != INI_PATH:
                    violations.append(f"{tid}.{field}: {action[:2]}")
    assert violations == [], "Fortnite tweaks left GameUserSettings.ini:\n" + "\n".join(violations)


def test_no_tweak_action_targets_anti_cheat():
    """Catalogue-wide: no action or revert string may name an anti-cheat
    process/service (word-boundary match, case-insensitive)."""
    offenders = []
    for tid in sorted(BY_ID):
        for field, action, part in _iter_action_strings(BY_ID[tid]):
            if FORBIDDEN.search(part):
                offenders.append(f"{tid}.{field}: {part}")
    assert offenders == [], "anti-cheat references in tweak actions:\n" + "\n".join(offenders)


def test_fortnite_tweaks_never_silently_run_unattended():
    """The apply-time gate must mirror verification state: an unverified fn-*
    tweak is allowed but flagged requires_confirmation (never batched
    unattended); a verified one needs no flag. All 28 are unverified today
    (evidence=LOW), so every one of them must come back flagged."""
    from engine import entitlements as ENT

    problems = []
    for tid in sorted(EXPECTED_FN_IDS):
        tweak = BY_ID[tid]
        g = ENT.gate(tweak, held=ENT.MAXIMUM)
        if not g.get("allowed"):
            problems.append(f"{tid}: blocked even for the top plan ({g.get('code')})")
        elif bool(g.get("requires_confirmation")) is not (not tweak.get("verified")):
            problems.append(
                f"{tid}: requires_confirmation={g.get('requires_confirmation')} "
                f"but verified={tweak.get('verified')}")
    assert problems == [], "; ".join(problems)
