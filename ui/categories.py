"""Category groups for the redesigned UI.

The database stores ~45 raw categories; the UI groups them into 12 clear,
user-facing sections. Every raw category maps to exactly one group.
"""
from __future__ import annotations

from pathlib import Path

from database import TWEAKS
from config.app_config import DIRS

# Category logo PNGs (real lucide hardware icons + the Fortnite emblem,
# tinted to each group's neon color) live in assets/icons/.
def logo_path(key: str) -> Path:
    return DIRS["assets"] / "icons" / f"{key}.png"

# Raw DB category -> "what it affects" label.
DB_AFFECTS = {
    "CPU": "CPU",
    "Scheduling": "CPU Scheduler",
    "GPU": "GPU",
    "NVIDIA": "NVIDIA GPU",
    "AMD": "AMD GPU",
    "Windows Graphics": "Graphics · DWM",
    "DirectX": "DirectX",
    "DirectX 12": "DirectX 12",
    "RAM": "RAM",
    "Windows": "Windows Shell",
    "System": "Core System",
    "Registry": "Registry",
    "Power Plans": "Power",
    "Power": "Power",
    "Services": "Services",
    "Debloat": "Apps",
    "Startup": "Startup",
    "Background": "Background Apps",
    "Privacy": "Privacy",
    "Telemetry": "Telemetry",
    "Audio": "Audio",
    "USB": "USB",
    "Security & Performance": "Security",
    "Display": "Display",
    "Monitor": "Monitor",
    "BIOS": "Firmware",
    "Advanced": "Advanced",
    "Experimental": "Experimental",
    "Network": "Network",
    "Ethernet": "Ethernet",
    "Wi-Fi": "Wi-Fi",
    "Mouse": "Mouse",
    "Input Latency": "Input Latency",
    "Aim": "Pointer",
    "Precision Tweaks": "Precision",
    "Keyboard": "Keyboard",
    "Storage": "Storage",
    "Fortnite": "Fortnite",
    "Gaming": "Gaming",
    "FPS": "FPS",
    "Frame Time": "Frame Time",
    "Game Profiles": "Game Profile",
    "System Tools": "Tools",
    "Diagnostics": "Diagnostics",
    "Repair": "Repair",
    "Guides": "Guide",
    "Laptop": "Laptop",
    "Performance": "Performance",
    "FPS Boost": "FPS Boost",
}

# Extra "affects" labels refined by tag (deduped against DB_AFFECTS).
TAG_AFFECTS = {
    "mmcss": "Multimedia Priority",
    "parking": "CPU Power",
    "cstate": "CPU Power",
    "boostmode": "CPU Boost",
    "turbo": "CPU Boost",
    "hpet": "Interrupts",
    "dpc": "DPC Latency",
    "interrupt": "Interrupts",
    "hags": "GPU Scheduling",
    "rebar": "GPU · ReBAR",
    "sam": "GPU · SAM",
    "reflex": "NVIDIA Reflex",
    "gsync": "G-Sync",
    "vrr": "Variable Refresh",
    "freesync": "FreeSync",
    "pagefile": "Virtual Memory",
    "superfetch": "Prefetch",
    "prefetch": "Prefetch",
    "trim": "SSD Trim",
    "ntfs": "NTFS",
    "journal": "NTFS",
    "tcp": "TCP/IP",
    "ack": "TCP/IP",
    "nagle": "TCP/IP",
    "lso": "NIC Offload",
    "rss": "NIC RSS",
    "dvr": "Game DVR",
    "gamebar": "Game Bar",
    "telemetry": "Telemetry",
    "diagtrack": "Telemetry",
    "defender": "Windows Defender",
    "onedrive": "OneDrive",
    "startup": "Startup",
    "registry": "Registry",
    "timer": "Timers",
    "affinity": "CPU Affinity",
    "core": "CPU",
    "lid": "Lid Action",
    "battery": "Battery",
    "modern_standby": "Modern Standby",
    "thermal": "Thermal",
    "hibernate": "Hibernation",
    "sound": "Audio",
    "audio": "Audio",
    "ducking": "Audio Ducking",
    "exclusive": "Audio Exclusive",
    "spatial": "Spatial Audio",
    "enhancements": "Audio DSP",
    "apo": "Audio Processing",
    "microphone": "Microphone",
    "bluetooth": "Bluetooth Audio",
    "headset": "Headset",
    "dac": "Audio Interface",
}

# Requested sections: key -> metadata + the raw DB categories they include.
CATEGORY_GROUPS = {
    "cpu": {
        "key": "cpu",
        "title": "CPU Tweaks",
        "icon": "\u2b22",
        "logo": "cpu",
        "color": "#8B5CF6",
        "blurb": "Processor scheduling, power management and Windows CPU optimizations.",
        "db": ["CPU", "Scheduling"],
    },
    "gpu": {
        "key": "gpu",
        "title": "GPU Tweaks",
        "icon": "\u25c6",
        "logo": "gpu",
        "color": "#C084FC",
        "blurb": "NVIDIA/AMD/Intel GPU optimizations, scheduling, and vendor-specific driver settings.",
        "db": ["GPU", "NVIDIA", "AMD", "Intel"],
    },
    "ram": {
        "key": "ram",
        "title": "RAM Tweaks",
        "icon": "\u2588",
        "logo": "ram",
        "color": "#F472B6",
        "blurb": "Memory management, virtual memory and background memory behavior.",
        "db": ["RAM"],
    },
    "mouse": {
        "key": "mouse",
        "title": "Mouse Tweaks",
        "icon": "\u21a8",
        "logo": "mouse",
        "color": "#A78BFA",
        "blurb": "Pointer precision, acceleration and polling for sharper response.",
        "db": ["Mouse"],
    },
    "keyboard": {
        "key": "keyboard",
        "title": "Keyboard Tweaks",
        "icon": "\u2328",
        "logo": "keyboard",
        "color": "#D946EF",
        "blurb": "Repeat delay, filter keys and keyboard input responsiveness.",
        "db": ["Keyboard"],
    },
    "input": {
        "key": "input",
        "title": "Pointer & Input",
        "icon": "\u2694",
        "logo": "input",
        "color": "#E879F9",
        "blurb": "Input-latency reductions so your clicks, keystrokes and pointer inputs register faster.",
        "db": ["Input Latency", "Aim", "Precision Tweaks"],
    },
    "network": {
        "key": "network",
        "title": "Network Tweaks",
        "icon": "\u2637",
        "logo": "network",
        "color": "#6366F1",
        "blurb": "TCP/IP stack, Ethernet and Wi-Fi tuning for lower ping and stable connections.",
        "db": ["Network", "Ethernet", "Wi-Fi"],
    },
    "storage": {
        "key": "storage",
        "title": "Storage / SSD",
        "icon": "\u25b6",
        "logo": "storage",
        "color": "#818CF8",
        "blurb": "NTFS, SSD trimming, filesystem and disk behavior optimizations.",
        "db": ["Storage"],
    },
    "audio": {
        "key": "audio",
        "title": "Audio Tweaks",
        "icon": "\U0001f50a",
        "logo": "audio",
        "color": "#06B6D4",
        "blurb": "Deep Windows audio engine, WASAPI, MMCSS scheduling, USB/Bluetooth audio, microphones, and gaming audio optimizations.",
        "db": ["Audio"],
    },
    "system": {
        "key": "system",
        "title": "Windows / System",
        "icon": "\u2699",
        "logo": "system",
        "color": "#C484FF",
        "blurb": "Windows shell, services, privacy, telemetry, DirectX, graphics stack and more.",
        "db": [
            "Windows", "System", "Registry", "Services",
            "Debloat", "Startup", "Background", "Privacy", "Telemetry",
            "USB", "Security & Performance", "Display", "Monitor", "BIOS",
            "Advanced", "Experimental", "Windows Explorer",
            "Windows Graphics", "DirectX", "DirectX 12",
        ],
    },
    "power": {
        "key": "power",
        "title": "Power Tweaks",
        "icon": "\u26a1",
        "logo": "power",
        "color": "#F59E0B",
        "blurb": "Power plans, CPU power states, sleep/hibernate and energy settings. Includes the MAXimum Premium Power Plan.",
        "db": ["Power Plans", "Power"],
    },
    "performance": {
        "key": "performance",
        "title": "Performance Tweaks",
        "icon": "\u26a1",
        "logo": "performance",
        "color": "#A855F7",
        "blurb": "FPS boosting and frame-pacing optimizations for smoother, more consistent gameplay.",
        "db": ["Performance", "FPS", "Frame Time"],
    },
    "fortnite": {
        "key": "fortnite",
        "title": "Fortnite",
        "icon": "\u25c9",
        "logo": "fortnite",
        "color": "#9333EA",
        "blurb": "Fortnite-only optimizations for FPS, input latency, graphics and network.",
        "db": ["Fortnite"],
    },
    "games": {
        "key": "games",
        "title": "Game Tweaks",
        "icon": "\u2605",
        "logo": "games",
        "color": "#EC4899",
        "blurb": "Game Mode, DVR, Game Bar and general gaming performance settings.",
        "db": ["Gaming"],
    },
    "profiles": {
        "key": "profiles",
        "title": "Game Profiles",
        "icon": "\u2654",
        "logo": "profiles",
        "color": "#B16CEA",
        "blurb": "One-click per-game performance profiles for popular esports titles.",
        "db": ["Game Profiles"],
    },
    "tools": {
        "key": "tools",
        "title": "System Tools",
        "icon": "\u26cf",
        "logo": "tools",
        "color": "#9D7BFF",
        "blurb": "Diagnostics, repair and quick-access tools for your system.",
        "db": ["System Tools", "Diagnostics", "Repair"],
    },
    "laptop": {
        "key": "laptop",
        "title": "Laptop Tweaks",
        "icon": "\u25c8",
        "logo": "laptop",
        "color": "#34D399",
        "blurb": "Battery, lid, hybrid-graphics and dedicated-GPU settings "
                "specific to laptops.",
        "db": ["Laptop"],
    },
    "fpsboost": {
        "key": "fpsboost",
        "title": "FPS Boost",
        "icon": "\u26a1",
        "logo": "fpsboost",
        "color": "#EF4444",
        "blurb": "Proven system-level tweaks to maximize FPS — VBS, ReBAR, "
                "core parking, GPU power management and more.",
        "db": ["FPS Boost"],
    },
}

GROUP_ORDER = [
    "cpu", "gpu", "ram", "power", "mouse", "keyboard", "input",
    "network", "storage", "audio", "system", "performance", "fortnite",
    "games", "profiles", "tools", "laptop", "fpsboost",
]

# Sidebar "Tweaks" sub-categories (no profiles/tools â€” those are top-level nav).
TWEAK_ORDER = [
    "cpu", "gpu", "ram", "power", "mouse", "keyboard", "input",
    "network", "storage", "audio", "system", "performance", "fortnite",
    "games", "laptop", "fpsboost",
]

# Raw category -> owning group key (every raw category maps to one group).
GROUP_BY_CAT = {}
for _k in GROUP_ORDER:
    for _c in CATEGORY_GROUPS[_k]["db"]:
        GROUP_BY_CAT.setdefault(_c, _k)

# Tool-like tweaks (reports, repair/cleanup actions) that live inside other
# categories but belong in the Tools section. Re-routed by id so the
# Windows/System section no longer shows them. Guide-only tweaks are excluded
# here - they are re-homed to their own "Guides" category by the DB loader.
TOOLS_IDS = {
    # BIOS reports
    "bios-001",
    # Monitor checks / reports
    "mon-003", "mon-014",
    # USB reports / reset
    "usb-003", "usb-004", "usb-012",
    # Power plan tools
    "pp-001", "pp-006", "pp-007", "pp-010",
    # Startup reports / cleanup
    "start-001",
    # System tools
    "sys-008",
    # Audio report
    "audio-012",
    # Debloat cleanup
    "db-014",
}

# Short pill / chip labels for the 12 browsable tweak groups.
CATEGORY_LABELS = {
    "cpu": "CPU",
    "gpu": "GPU",
    "ram": "RAM",
    "mouse": "Mouse",
    "keyboard": "Keyboard",
    "input": "Pointer & Input",
    "network": "Network",
    "storage": "Storage",
    "audio": "Audio",
    "system": "Windows",
    "performance": "Performance",
    "fortnite": "Fortnite",
    "games": "Games",
    "laptop": "Laptop",
    "power": "Power",
}

# All browsable groups in display order (excludes profiles/tools nav sections).
ALL_TWEAK_KEYS = TWEAK_ORDER

# Sidebar "TWEAKS" sub-category list, in display order: (group key, label).
SIDEBAR_TWEAKS = [
    ("cpu", "CPU"),
    ("gpu", "GPU"),
    ("ram", "RAM"),
    ("input", "INPUT"),
    ("mouse", "Mouse"),
    ("keyboard", "Keyboard"),
    ("network", "Network"),
    ("storage", "Storage"),
    ("audio", "Audio"),
    ("system", "Windows / System"),
    ("performance", "Performance"),
    ("fortnite", "Fortnite"),
    ("games", "Games"),
    ("laptop", "Laptop"),
    ("power", "Power"),
    ("fpsboost", "FPS Boost"),
]


def group_key_for_category(category: str, tweak: dict | None = None) -> str:
    if tweak is not None and tweak.get("id") in TOOLS_IDS:
        return "tools"
    return GROUP_BY_CAT.get(category, "system")

# Fortnite tweaks grouped into subsections (id lists, verified against DB).
FORTNITE_SECTIONS = {
    "Performance": ["fn-001"],
    "Input / Latency": ["fn-003", "fn-027"],
    "FPS": ["fn-002", "fn-004", "fn-034"],
    "Graphics": ["fn-005", "fn-006", "fn-009", "fn-011", "fn-012",
                 "fn-013", "fn-014", "fn-015", "fn-016", "fn-017",
                 "fn-018", "fn-019", "fn-020", "fn-021", "fn-022",
                 "fn-023", "fn-024", "fn-025", "fn-026", "fn-028",
                 "fn-029", "fn-035", "fn-036", "fn-037", "fn-038",
                 "fn-039"],
    "Rendering / Latency": ["fn-030", "fn-031", "fn-032"],
    "Mouse / Pointer": ["fn-033"],
    "Network": ["fn-010"],
    "Launch Options": ["fn-007"],
    "Config": ["fn-008"],
}
FORTNITE_ORDER = list(FORTNITE_SECTIONS)

# Game profile tweak ids, kept in a stable display order.
GAME_PROFILE_IDS = [
    "gp-001", "gp-002", "gp-003", "gp-004", "gp-005", "gp-006",
    "gp-007", "gp-008", "gp-009", "gp-010", "gp-011", "gp-012",
]


def group_tweaks(key: str) -> list[dict]:
    db_cats = set(CATEGORY_GROUPS[key]["db"])
    if key == "tools":
        return [t for t in TWEAKS if t["category"] in db_cats or t["id"] in TOOLS_IDS]
    return [t for t in TWEAKS if t["category"] in db_cats and t["id"] not in TOOLS_IDS]


# --- GPU vendor filter -------------------------------------------------------
# When the user selects a GPU vendor in the GPU selector, we filter the
# tweaks to show only those relevant to that vendor.  The filter logic:
#   * Include tweaks with NO ``when.gpu`` condition (generic GPU tweaks).
#   * Include tweaks whose ``when.gpu`` list contains the selected vendor.
#   * Include tweaks whose ``when.gpu_type`` matches:
#       nvidia / amd  →  ["dedicated"]
#       integrated    →  ["integrated"]
#   * Exclude tweaks whose ``when.gpu`` list does NOT contain the selected vendor.

GPU_VENDOR_MAP = {
    "nvidia": {"nvidia"},
    "amd": {"amd"},
    "integrated": {"intel"},
}

GPU_TYPE_MAP = {
    "nvidia": "dedicated",
    "amd": "dedicated",
    "integrated": "integrated",
}


def gpu_filter_tweaks(key: str, gpu_vendor: str) -> list[dict]:
    """Return tweaks for the GPU category filtered by vendor selection.

    When a vendor is selected, only tweaks whose ``when.gpu`` or
    ``when.gpu_type`` explicitly includes the vendor/type are shown.
    Untagged tweaks are *not* auto-included — they must carry an
    explicit ``when`` condition to appear for a specific vendor.
    """
    all_tweaks = group_tweaks(key)
    if not gpu_vendor:
        return all_tweaks
    vendor_set = GPU_VENDOR_MAP.get(gpu_vendor, set())
    gpu_type = GPU_TYPE_MAP.get(gpu_vendor)
    out = []
    for t in all_tweaks:
        when = t.get("when", {})
        req_gpu = when.get("gpu")
        req_gpu_type = when.get("gpu_type")
        # Untagged tweaks (no gpu / gpu_type condition) are excluded
        # when a vendor is selected — they must be explicitly tagged.
        if not req_gpu and not req_gpu_type:
            continue
        # If when.gpu is set, check vendor match.
        if req_gpu:
            req_set = set(req_gpu)
            if vendor_set & req_set:
                out.append(t)
                continue
        # If when.gpu_type is set, check type match.
        if req_gpu_type and gpu_type:
            if gpu_type in req_gpu_type:
                out.append(t)
                continue
    return out


# ── CPU vendor/form-factor filtering ──────────────────────────────────
# Works like GPU filtering: universal tweaks (no when.cpu_vendor / when.laptop)
# are ALWAYS shown; vendor/form-factor tagged tweaks are only shown when
# they match the detected hardware.

def cpu_filter_tweaks(key: str, cpu_vendor: str | None = None,
                      is_laptop: bool | None = None) -> list[dict]:
    """Return tweaks for the CPU category filtered by vendor and form factor.

    Universal tweaks (no ``when.cpu_vendor`` / ``when.laptop``) are always
    shown.  Vendor-tagged tweaks only appear when the detected CPU matches.
    Form-factor tweaks only appear when the detected laptop state matches.
    """
    all_tweaks = group_tweaks(key)
    if cpu_vendor is None and is_laptop is None:
        return all_tweaks
    out = []
    for t in all_tweaks:
        when = t.get("when", {})
        req_vendor = when.get("cpu_vendor")
        req_laptop = when.get("laptop")
        # If tweak specifies cpu_vendor, check match.
        if req_vendor and cpu_vendor:
            if cpu_vendor.lower() not in [v.lower() for v in req_vendor]:
                continue
        # If tweak specifies laptop, check match.
        if req_laptop is not None and is_laptop is not None:
            if req_laptop != is_laptop:
                continue
        out.append(t)
    return out


def affects_for(tweak: dict) -> list[str]:
    """Human-readable 'what it affects' labels for a tweak."""
    labels = []
    cat = DB_AFFECTS.get(tweak.get("category"))
    if cat:
        labels.append(cat)
    for tag in tweak.get("tags") or []:
        extra = TAG_AFFECTS.get(tag)
        if extra and extra not in labels:
            labels.append(extra)
    return labels[:4]


def recommended_count(tweaks) -> int:
    return sum(1 for t in tweaks if t.get("recommended") == "recommended")

