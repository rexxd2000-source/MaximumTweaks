"""Tweak grade axis: FREE / FOUNDATION / MAXIMUM.

Two vocabularies live in this project and they are kept deliberately apart:

**Grade** (this module) -- what a tweak is *graded* as.
    ``FREE`` / ``FOUNDATION`` / ``MAXIMUM``. Uppercase ids, stored on a tweak as
    ``classification``. ``FOUNDATION`` the grade is *not* ``foundation`` the plan.

**Plan** (:mod:`config.plans`) -- what a subscriber has *bought*.
    ``foundation`` / ``performance`` / ``maximum``. Lowercase ids, stored on a
    tweak as ``requiredTier``.

A tweak has exactly one grade; the product then derives the plan that unlocks it
from that grade through one fixed, order-preserving mapping (``PLAN_FOR_GRADE``)::

    FREE       -> foundation  plan  ($0)
    FOUNDATION -> performance plan  ($10)
    MAXIMUM    -> maximum     plan  ($15)

The vocabularies cannot drift into each other because nothing converts between
them by string equality: grades only ever resolve through
:data:`CLASSIFICATION_TO_TIER`, and :func:`normalize_grade` / :func:`normalize_plan`
each reject the *other* vocabulary's tokens outright. :func:`normalize_grade` is
case-sensitive on purpose -- the grade ids are the plan ids uppercased, so
folding case would let ``"foundation"`` (a plan) read back as ``FOUNDATION``
(a grade).

Where a grade comes from
-------------------------
:func:`grade_optimization` is what the store and the audit both call. It returns
the **reviewed** grade from :mod:`database.reviewed_tiers` (imported from the
human tier-review sheet, which is the source of truth) whenever the tweak has
one, and otherwise falls back to :func:`classify_optimization`.

:func:`classify_optimization` is the *heuristic*: a pure function of the loaded
implementation facts (the same ``actions`` / ``revert`` / ``when`` tuples
:mod:`database.tiers` inspects). It is deliberately left intact rather than
deleted, so the shipped grade stays auditable -- review and heuristic differ on
a known, countable set of tweaks instead of being silently conflated. The old
``tier=`` pins are *not* consulted: they were hand-authored for all 863 tweaks,
carry no independent information, and are exactly the staleness this axis
removes.

Danger is judged from the implementation, never from the module or name. A
tweak in a module named ``aim`` that simply clears a registry policy value is
not a cheat; a benign-looking telemetry card that actually disables Windows
Update's repair service (``WaaSMedicSvc``) is a hazard. Only the tuples decide.
"""
from __future__ import annotations

from config.plans import (  # noqa: E402  (plan names re-exported below)
    FOUNDATION as PLAN_FOUNDATION,
    MAXIMUM as PLAN_MAXIMUM,
    PERFORMANCE as PLAN_PERFORMANCE,
)
from config.plans import normalize_tier as normalize_plan  # noqa: E402

#: The grade axis, lowest first. Deliberately uppercase and distinct from the
#: lowercase plan ids in config.plans so the two vocabularies never collide and
#: a grade can never silently become a plan name.
FREE = "FREE"
FOUNDATION = "FOUNDATION"
MAXIMUM = "MAXIMUM"
CLASSIFICATIONS: tuple[str, str, str] = (FREE, FOUNDATION, MAXIMUM)

#: Same axis under its unambiguous name. ``GRADES`` is what new code should
#: reach for; ``CLASSIFICATIONS`` stays because it is the name stored on every
#: tweak dict and is part of the existing public surface.
GRADES = CLASSIFICATIONS
GRADE_RANK: dict[str, int] = {g: i for i, g in enumerate(GRADES)}

#: Grade -> plan that unlocks the tweak. Order-preserving mapping.
CLASSIFICATION_TO_TIER: dict[str, str] = {
    FREE: PLAN_FOUNDATION,
    FOUNDATION: PLAN_PERFORMANCE,
    MAXIMUM: PLAN_MAXIMUM,
}

#: Same mapping under its unambiguous name. ``PLAN_FOR_GRADE`` reads as
#: "which plan does this grade need", which is the only question it answers.
PLAN_FOR_GRADE = CLASSIFICATION_TO_TIER

#: The plan vocabulary, for callers that need to assert disjointness without
#: importing config.plans themselves.
PLANS: tuple[str, str, str] = (PLAN_FOUNDATION, PLAN_PERFORMANCE, PLAN_MAXIMUM)

__all__ = [
    "FREE", "FOUNDATION", "MAXIMUM", "CLASSIFICATIONS", "GRADES", "GRADE_RANK",
    "CLASSIFICATION_TO_TIER", "PLAN_FOR_GRADE", "PLANS",
    "classify_optimization", "grade_optimization", "reviewed_grade",
    "normalize_grade", "normalize_plan", "tier_for",
]

#: Windows services that must never be silently disabled. Setting any of these
#: to ``disabled``/``STOP`` is a hazard even when the writer thinks otherwise.
_CRITICAL_SERVICES = frozenset({
    # Windows Update infrastructure: disabling breaks security patching, not
    # just "telemetry". WaaSMedicSvc repairs the update pipeline itself.
    "wuauserv", "usosvc", "waasmedicsvc",
    # Security essentials.
    "windefend", "securityhealthservice", "wscsvc", "mpssvc", "sense",
    # Credential storage: everything from Windows Hello to Wi-Fi keys uses it.
    "vaultsvc",
    # Core services whose removal destabilises the desktop/session.
    "eventlog", "schedule", "rpcs", "dcomlaunch", "lsass", "nsi",
    "lanmanworkstation", "lanmanserver", "winmgmt",
})

#: Service names that are part of a vendor/audio stack and must stay coherent
#: as a group; stopping just one member breaks the rest. These are a warning
#: (MAXIMUM, not a silent disable), not an automatic removal.
_VENDOR_SERVICE_GROUPS = {
    "nvvapi": {"nvdisplay.container", "nvtmmon", "nvtmrep", "nvvapi"},
}

#: Registry policy/value patterns that mean "switch Windows Update off".
_DISABLE_WU_MARKERS = (
    r"HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate",
    r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate",
    r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU",
)


def _disables_critical_service(facts: dict) -> str | None:
    """Return the critical service a tweak disables, or None."""
    actions = facts["actions"]
    for a in actions:
        kind = a[0]
        if kind in ("svc", "svcstop") and len(a) >= 2:
            if str(a[1]).lower() in _CRITICAL_SERVICES:
                return str(a[1])
        elif kind == "sc" and len(a) >= 3:
            if str(a[1]).lower() in ("disable", "stop") \
                    and str(a[2]).lower() in _CRITICAL_SERVICES:
                return str(a[2])
    return None


def _turns_off_windows_update(facts: dict) -> str | None:
    """Return the reason when the tweak flips the global auto-update switch."""
    for a in facts["actions"]:
        if a[0] == "reg" and len(a) >= 5:
            path = (str(a[1]) + "\\" + str(a[2])).lower()
            if any(m.lower() in path for m in _DISABLE_WU_MARKERS):
                if str(a[3]).lower() == "noautoupdate" and str(a[4]) == "1":
                    return "NoAutoUpdate=1 disables Windows Update entirely"
    return None


def tier_for(classification: str) -> str:
    """Map a classification to the plan tier that unlocks it.

    Fails closed: anything that is not a known grade resolves to the free plan,
    *as a plan name* -- never to the classifier's own uppercase vocabulary.
    """
    if classification not in CLASSIFICATION_TO_TIER:
        return PLAN_FOUNDATION
    return CLASSIFICATION_TO_TIER[classification]


def normalize_grade(value: object) -> str | None:
    """Coerce input to a valid *grade*, or None when it is not one.

    Accepts the grade vocabulary only, as the exact uppercase tokens (leading
    and trailing whitespace tolerated), which is what lets a review sheet's
    ``new_tier`` column be read verbatim.

    Case is load-bearing and deliberately **not** folded: the plan ids are the
    same words lowercased, so a case-insensitive match would make
    ``normalize_grade("foundation")`` return ``FOUNDATION`` and quietly resolve
    a plan as a grade -- exactly the confusion this axis exists to prevent.
    ``normalize_grade("foundation")`` is therefore ``None``; use
    :func:`normalize_plan` for plans.
    """
    if not isinstance(value, str):
        return None
    key = value.strip()
    return key if key in GRADE_RANK else None


def reviewed_grade(tweak_id: object) -> str | None:
    """The reviewed grade for ``tweak_id``, or None when it was not reviewed.

    Imported lazily so :mod:`database.reviewed_tiers` can import
    :data:`GRADES` from here without a circular import at module load.
    """
    from database.reviewed_tiers import reviewed_grade as _reviewed

    return _reviewed(tweak_id)


def grade_optimization(facts: dict, tweak: dict | None = None) -> tuple[str, str]:
    """Grade one tweak as FREE / FOUNDATION / MAXIMUM: the shipped answer.

    The reviewed tier-review sheet is the source of truth, so a reviewed tweak
    gets its reviewed grade verbatim and says so in the reason. Anything not
    covered by the review -- the Diagnostic / System Tools entries, which carry
    no tier review, and any optimization tweak added before the next review pass
    -- falls back to the heuristic in :func:`classify_optimization`.

    Splitting the two keeps a machine-derived guess from ever quietly
    overriding a human decision, and keeps the heuristic available to compute
    what the review disagreed with.
    """
    if tweak is not None:
        override = reviewed_grade(tweak.get("id"))
        if override is not None:
            return override, (
                f"Reviewed tier: graded {override} in the tier review "
                f"({reviewed_source()})."
            )
    return classify_optimization(facts, tweak)


def reviewed_source() -> str:
    """Name of the review sheet currently loaded, or a placeholder."""
    try:
        from database.reviewed_tiers import IMPORTED, SOURCE

        return f"{SOURCE}, imported {IMPORTED}"
    except Exception:  # pragma: no cover - the generated table is always present
        return "no review sheet loaded"


def classify_optimization(facts: dict, tweak: dict | None = None) -> tuple[str, str]:
    """Heuristically grade one tweak as FREE / FOUNDATION / MAXIMUM.

    This is the *machine* opinion, computed purely from what the implementation
    *does*. The grade that actually ships comes from
    :func:`grade_optimization`, which prefers the reviewed value; this function
    stays intact so the two can be diffed.

    The grade is decided purely by what the implementation *does*:

    MAXIMUM
        anything that reaches outside generic Windows: a specific GPU vendor,
        the boot loader, a driver/device, a custom power scheme, filesystem
        servicing, memory/MMCSS scheduling, a confirmed-risky switch, or that
        disables a security/update-critical service.

    FOUNDATION
        core optimizations that are still safe to think about: hardware-gated
        changes, service/network/power/AppX/scheduled-task/config-file edits,
        cross-hive writes and process control.

    FREE
        everything left: generic, broadly compatible, reversible changes that
        any supported Windows PC can accept without risk.

    ``tweak`` is accepted for API symmetry with :func:`database.tiers.classify_tier`
    but is deliberately not read: authored ``tier=``/``disposition=`` labels are
    exactly the staleness this audit removes.
    """
    flags = facts["flags"]
    critical = _disables_critical_service(facts)
    wu_off = _turns_off_windows_update(facts)

    agg = {
        "gpu_vendor_specific": "GPU vendor-specific tuning in the implementation",
        "boot_config": "boot configuration changed via bcdedit",
        "driver_control": "direct driver/device control (PnP / nvidia-smi / pnputil)",
        "custom_power_scheme": "creates or modifies a named power scheme",
        "filesystem_servicing": "runs a filesystem/component-servicing tool (chkdsk/defrag/sfc/dism)",
        "confirmed_risky": "flagged confirm=True (low-level CPU/security behaviour)",
        "mmcss_scheduler": "multimedia class scheduler / GPU scheduling priority keys",
        "memory_tuning": "direct memory/AGP/aperture/large-page tuning",
        "deep_hardware_tier": "hardware-specific tuning gated on CPU family/memory topology",
    }
    for key, reason in agg.items():
        if flags.get(key):
            return MAXIMUM, reason + "."
    if critical:
        return MAXIMUM, f"disables critical service '{critical}', which breaks update/security plumbing."
    if wu_off:
        return MAXIMUM, wu_off + "."

    core = {
        "hardware_gate": "hardware-gated: only valid on specific GPU/CPU/storage/audio hardware",
        "service_change": "modifies a Windows service start type or runtime state",
        "scheduled_task_change": "modifies a Windows scheduled task",
        "network_stack": "changes the TCP/IP or network-adapter stack",
        "appx_removal": "removes or re-registers an AppX package",
        "power_setting": "alters a Windows power setting",
        "app_config_write": "writes a game or application configuration file",
        "cross_hive_write": "writes multiple registry hives (machine-wide state)",
        "process_control": "controls game processes at runtime",
    }
    for key, reason in core.items():
        if flags.get(key):
            return FOUNDATION, reason + "."

    if not facts["mutating_count"] or facts["guidance_only"]:
        return FREE, "Informational/read-only: changes no system state."

    return FREE, (
        "Generic, broadly compatible Windows change: "
        f"{facts['mutating_count']} reversible action(s), no vendor, service, "
        "driver, memory or hardware dependency."
    )