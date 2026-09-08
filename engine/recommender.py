"""Compatibility evaluation — decides which tweaks are ready for a profile."""
from __future__ import annotations

import platform

READY = "ready"
INCOMPATIBLE = "incompatible"
NOT_FOR_YOU = "not_for_you"   # vendor-specific guidance not matching this system
OPTIONAL = "optional"         # advanced / optional risk, compatible but user should decide
WARNING = "warning"           # risky for the detected hardware
UNKNOWN = "unknown"           # hardware not detected yet — cannot confirm compatibility

#: ``when`` condition keys the recommender actually evaluates against a profile.
HARDWARE_KEYS = ("gpu", "cpu_vendor", "intel_cpu", "cpu_cores", "ram_gb",
                 "ram_channels", "ssd", "hdd", "nvme", "laptop")


def windows_versions(tweak: dict) -> set[str]:
    """The set of Windows versions this tweak is designed for (e.g. {"10"})."""
    win = tweak.get("win") or ""
    return {v.strip() for v in win.split(",") if v.strip()}


def has_hardware_gates(tweak: dict) -> bool:
    """True when this tweak must not be applied without a detected profile."""
    when = tweak.get("when") or {}
    return any(k in when for k in HARDWARE_KEYS)


def _effective_win_version(profile: dict) -> str | None:
    """Detected Windows version ("10"|"11") from the profile, else the OS."""
    v = profile.get("win_version")
    if v in ("10", "11"):
        return v
    try:
        _, build, _, _ = platform.win32_ver()
        if build:
            return "11" if int(build) >= 22000 else "10"
    except Exception:  # noqa: BLE001
        pass
    return None


def _in(vals, key, profile):
    """Match an OR list against a scalar profile value."""
    if not isinstance(vals, (list, tuple)):
        vals = [vals]
    return any(v == profile.get(key) for v in vals)


def _numeric(cond, profile, key="cpu_cores"):
    """Handle {'<': n}, {'<=': n}, {'>': n}, {'>=': n}, or a bare scalar."""
    if isinstance(cond, dict):
        for op, limit in cond.items():
            try:
                val = float(profile.get(key) or 0)
            except (TypeError, ValueError):
                return False
            limit = float(limit)
            if op == "<=":
                return val <= limit
            if op == "<":
                return val < limit
            if op == ">=":
                return val >= limit
            if op == ">":
                return val > limit
        return True
    try:
        return float(profile.get(key) or 0) >= float(cond)
    except (TypeError, ValueError):
        return True


def _cond_text(cond) -> str:
    """Human-readable requirement text for a numeric when condition.

    A bare scalar means ``>= n`` (see :func:`_numeric`), so the reason must
    not claim ``Requires <= n`` — that text was actively misleading.
    """
    if isinstance(cond, dict):
        for op, limit in cond.items():
            return {"<=": "at most", "<": "under",
                    ">=": "at least", ">": "over"}.get(op, op) + f" {limit}"
    return f"at least {cond}"


def evaluate(tweak: dict, profile: dict) -> dict:
    """Return {"state": ..., "reasons": [str]} for a single tweak."""
    reasons = []
    when = tweak.get("when") or {}
    risk = tweak.get("risk", "safe")

    if when.get("gpu"):
        gpu = profile.get("gpu") or ["unknown"]
        if not set(when["gpu"]) & set(gpu):
            names = {
                "nvidia": "NVIDIA",
                "amd": "AMD",
                "intel": "Intel",
            }
            need = "/".join(names.get(v, v) for v in when["gpu"])
            reasons.append(f"Requires a {need} GPU")

    if when.get("cpu_vendor") and not _in(when["cpu_vendor"], "cpu_vendor", profile):
        reasons.append(f"Requires {'/'.join(when['cpu_vendor'])} CPU")

    if when.get("intel_cpu") is False and profile.get("cpu_vendor") == "intel":
        reasons.append("Designed for AMD systems")

    if when.get("cpu_cores") is not None and not _numeric(when["cpu_cores"], profile):
        reasons.append(f"Requires {_cond_text(when['cpu_cores'])} CPU cores")

    if when.get("ram_gb") is not None and not _numeric(when["ram_gb"], profile, key="ram_gb"):
        reasons.append(f"Requires {_cond_text(when['ram_gb'])} GB RAM")

    if when.get("ram_channels") is not None and not _numeric(
            when["ram_channels"], profile, key="ram_channels"):
        reasons.append(f"Requires {_cond_text(when['ram_channels'])} memory channel(s)")

    if when.get("ssd") and not profile.get("ssd"):
        reasons.append("Requires an SSD")
    if when.get("hdd") and not profile.get("hdd"):
        reasons.append("Requires a mechanical HDD")
    if when.get("nvme") and not profile.get("nvme"):
        reasons.append("Requires an NVMe SSD")
    if when.get("laptop") is True and not profile.get("laptop"):
        reasons.append("Requires a laptop")
    if when.get("laptop") is False and profile.get("laptop"):
        reasons.append("Not compatible with laptops — causes excessive battery drain or breaks hybrid graphics")

    # Windows version gating: the ``win`` field is the per-tweak support list
    # (e.g. "10" or "11"), and ``when.win_versions`` is the same as a condition.
    win = _effective_win_version(profile)
    if win is not None:
        supported = windows_versions(tweak)
        if supported and win not in supported:
            reasons.append(
                f"Designed for Windows {'/'.join(sorted(supported))} "
                f"(this PC runs Windows {win})")
        when_wins = when.get("win_versions")
        if when_wins and win not in set(when_wins):
            reasons.append(
                f"Requires Windows {'/'.join(when_wins)} "
                f"(this PC runs Windows {win})")

    state = READY
    if reasons:
        state = INCOMPATIBLE
    else:
        tags = tweak.get("tags") or []
        if "advanced" in tags or risk == "advanced":
            state = OPTIONAL
            reasons.append("Advanced — may reduce security/stability")
        elif "reboot" in tags:
            reasons.append("Reboot recommended after applying")

    return {"state": state, "reasons": reasons}


def evaluate_many(tweaks, profile) -> dict:
    """Map tweak id -> evaluation dict."""
    return {t["id"]: evaluate(t, profile) for t in tweaks}
