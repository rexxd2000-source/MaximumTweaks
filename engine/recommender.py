"""Compatibility evaluation — decides which tweaks are ready for a profile."""
from __future__ import annotations

READY = "ready"
INCOMPATIBLE = "incompatible"
NOT_FOR_YOU = "not_for_you"   # vendor-specific guidance not matching this system
OPTIONAL = "optional"         # advanced / optional risk, compatible but user should decide
WARNING = "warning"           # risky for the detected hardware


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
        reasons.append(f"Requires <= {when['cpu_cores']} CPU cores")

    if when.get("ram_gb") is not None and not _numeric(when["ram_gb"], profile, key="ram_gb"):
        reasons.append(f"Requires {when['ram_gb']} GB RAM")

    if when.get("ram_channels") is not None and not _numeric(
            when["ram_channels"], profile, key="ram_channels"):
        reasons.append("Requires a single RAM stick")

    if when.get("ssd") and not profile.get("ssd"):
        reasons.append("Requires an SSD")
    if when.get("hdd") and not profile.get("hdd"):
        reasons.append("Requires a mechanical HDD")
    if when.get("nvme") and not profile.get("nvme"):
        reasons.append("Requires an NVMe SSD")
    if when.get("laptop") and not profile.get("laptop"):
        reasons.append("Requires a laptop")

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
