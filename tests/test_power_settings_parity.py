"""Apply and detect must share ONE power-settings GUID table.

Regression guard for the audit finding where engine/state_checker.POWER_NAMES
and database/executor.POWER_SETTINGS had drifted: 4 wrong GUIDs and 10 missing
keys on the detect side, so 7 tweaks applied changes the auditor could never
see. The tables are now a single object (executor aliases state_checker), and
the tests below fail if that is ever undone or if a tweak grows a power action
whose setting name has no GUID mapping.
"""
import re

from database.executor import POWER_SETTINGS
from engine.state_checker import POWER_NAMES
from database.tweaks import BY_ID

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Power-setting names referenced by tweaks that have no verified Windows GUID
# mapping yet. Apply fails closed (RuntimeError before any write) until the
# tweak is resolved. Empty as of the lap-050 fix: its dead "processor_idle_allow"
# action (a setting that does not exist in Windows) was dropped, leaving only
# the verified demote-threshold mapping.
PENDING_UNMAPPED: set[str] = set()


def test_single_source_of_truth():
    assert POWER_SETTINGS is POWER_NAMES, (
        "POWER_SETTINGS must alias POWER_NAMES — two tables drift apart "
        "(this exact bug shipped once: 4 wrong GUIDs, 10 missing keys)")


def test_guid_format():
    for name, spec in POWER_NAMES.items():
        subgroup, setting = spec
        assert _GUID.match(subgroup.lower()), f"{name}: bad subgroup {subgroup!r}"
        assert _GUID.match(setting.lower()), f"{name}: bad setting {setting!r}"


def test_no_duplicate_setting_guids():
    seen = {}
    for name, (_sub, setting) in POWER_NAMES.items():
        assert setting not in seen, (
            f"{name} and {seen[setting]} share setting GUID {setting}")
        seen[setting] = name


def test_every_tweak_power_action_is_mapped():
    unmapped = set()
    for tweak in BY_ID.values():
        for group in ("actions", "revert"):
            for action in tweak.get(group) or ():
                if len(action) >= 2 and action[0] == "power":
                    if action[1] not in POWER_NAMES:
                        unmapped.add(action[1])
    assert unmapped <= PENDING_UNMAPPED, (
        f"power settings with no GUID mapping: {sorted(unmapped - PENDING_UNMAPPED)} "
        f"— apply would fail closed; add them to POWER_NAMES "
        "(verified against HKLM ...\\Power\\PowerSettings\\<sub>\\<guid> FriendlyName)")


def test_pending_allowlist_is_still_needed():
    # The allowlist must never go stale: an entry that no tweak references
    # (or that now has a real GUID mapping) has to be deleted so this list
    # cannot silently grow.
    used = set()
    for tweak in BY_ID.values():
        for group in ("actions", "revert"):
            for action in tweak.get(group) or ():
                if len(action) >= 2 and action[0] == "power":
                    used.add(action[1])
    stale = {n for n in PENDING_UNMAPPED if n not in used or n in POWER_NAMES}
    assert not stale, f"remove stale entries from PENDING_UNMAPPED: {sorted(stale)}"
