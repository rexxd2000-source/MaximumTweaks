"""Tag-based hardware applicability for the category optimizers.

Each tweak's ``tags`` are matched against the detected subsystem data + the
base hardware profile.  Tags with no hardware requirement are skipped.  A
tweak that requires a specific GPU vendor / adapter type / storage class that
the detected system does not have is marked *not applicable*; features that
are vendor-gated but also depend on driver or panel support we cannot confirm
are surfaced as *driver-dependent* instead of being silently applied.
"""
from __future__ import annotations

# tag -> (kind, value, driver_dependent)
#   kind "gpu":          value = vendor or ("any_of", (vendors,)) 
#   kind "gpu_type":     value = "dedicated" | "integrated"
#   kind "cpu":          value = vendor
#   kind "media":        value = "wifi" | "ethernet"
#   kind "storage":      value = "ssd" | "nvme" | "hdd"
#   kind "flag":         value = profile key that must be truthy
TAG_REQ = {
    "reflex":   ("gpu", "nvidia", True),
    "gsync":    ("gpu", "nvidia", True),
    "rebar":    ("gpu", ("any_of", ("nvidia", "intel")), True),
    "sam":      ("gpu", "amd", False),
    "freesync": ("gpu", "amd", False),
    "nvidia":   ("gpu", "nvidia", False),
    "amd":      ("gpu", "amd", False),
    "intel_gpu": ("gpu", "intel", False),
    "dedicated_gpu": ("gpu_type", "dedicated", False),
    "integrated_gpu": ("gpu_type", "integrated", False),
    "intel_cpu": ("cpu", "intel", False),
    "amd_cpu":  ("cpu", "amd", False),
    "wifi":     ("media", "wifi", False),
    "ethernet": ("media", "ethernet", False),
    "ssd":      ("storage", "ssd", False),
    "nvme":     ("storage", "nvme", False),
    "hdd":      ("storage", "hdd", False),
    "laptop":   ("flag", "laptop", False),
}

_VENDOR_NAMES = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}


def check_applicability(tweak: dict, data: dict, profile: dict):
    """Return (ok, note, driver_dependent) for a tweak against detected data.

    ``data``  — the probe's machine-readable dict (e.g. media, gpus).
    ``profile`` — merged hardware profile (gpu vendors, cpu_vendor, ssd, ...).
    """
    ok, note, driver_dependent = True, "", False
    gpu_vendors = profile.get("gpu") or [p.get("vendor") for p in
                                         (data.get("gpus") or []) if p.get("vendor")]
    if not gpu_vendors:
        gpu_vendors = data.get("vendors") or ["unknown"]

    gpu_types = profile.get("gpu_types") or [p.get("type") for p in
                                              (data.get("gpus") or []) if p.get("type")]
    if not gpu_types:
        gpu_types = []

    def _vendor_present(vendor):
        return vendor in gpu_vendors

    def _gpu_type_present(gpu_type):
        return gpu_type in gpu_types

    for tag in (tweak.get("tags") or []):
        req = TAG_REQ.get(tag)
        if not req:
            continue
        kind, value, dd = req
        if kind == "gpu":
            need = value
            if isinstance(value, tuple) and value[0] == "any_of":
                need = "/".join(_VENDOR_NAMES.get(v, v) for v in value[1])
                present = any(_vendor_present(v) for v in value[1])
            else:
                present = _vendor_present(value)
            if not present:
                return False, f"Requires a {need} GPU.", False
            if dd:
                driver_dependent = True
                note = (note or "") + (f"Requires {need} GPU with driver support. "
                                       if not note else "")
        elif kind == "gpu_type":
            if not _gpu_type_present(value):
                return False, f"Requires a {value} GPU.", False
        elif kind == "cpu":
            if profile.get("cpu_vendor") != value:
                return False, f"Requires an {_VENDOR_NAMES.get(value, value)} CPU.", False
        elif kind == "media":
            media = data.get("media") or profile.get("net_media")
            if media != value:
                label = "Wi-Fi" if value == "wifi" else "wired Ethernet"
                return False, f"Requires an active {label} connection.", False
        elif kind == "storage":
            has = profile.get(value)
            if not has:
                label = {"ssd": "an SSD", "nvme": "an NVMe SSD",
                         "hdd": "a mechanical HDD"}.get(value, value)
                return False, f"Requires {label}.", False
        elif kind == "flag":
            if not profile.get(value):
                return False, f"Requires a {value.replace('_', ' ')}.", False
    return ok, note.strip(), driver_dependent
