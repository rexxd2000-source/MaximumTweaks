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
    "BIOS": "BIOS / UEFI",
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
        "blurb": "NVIDIA/AMD optimizations, GPU scheduling, graphics settings and rendering.",
        "db": ["GPU", "NVIDIA", "AMD", "Intel", "Windows Graphics", "DirectX", "DirectX 12"],
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
    "system": {
        "key": "system",
        "title": "Windows / System",
        "icon": "\u2699",
        "logo": "system",
        "color": "#C484FF",
        "blurb": "Windows shell, services, power plans, privacy, telemetry, audio, USB and more.",
        "db": [
            "Windows", "System", "Registry", "Power Plans", "Power", "Services",
            "Debloat", "Startup", "Background", "Privacy", "Telemetry", "Audio",
            "USB", "Security & Performance", "Display", "Monitor", "BIOS",
            "Advanced", "Experimental", "Windows Explorer",
        ],
    },
    "performance": {
        "key": "performance",
        "title": "Performance Tweaks",
        "icon": "\u26a1",
        "logo": "performance",
        "color": "#A855F7",
        "blurb": "FPS boosting and frame-pacing optimizations for smoother, more consistent gameplay.",
        "db": ["FPS", "Frame Time"],
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
    "guides": {
        "key": "guides",
        "title": "Guides",
        "icon": "\u2139",
        "logo": "guides",
        "color": "#60A5FA",
        "blurb": "Step-by-step walkthroughs for manual settings you do in "
                "software, the BIOS, or the OS \u2014 informational only.",
        "db": ["Guides"],
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
}

GROUP_ORDER = [
    "cpu", "gpu", "ram", "mouse", "keyboard", "input",
    "network", "storage", "system", "performance", "fortnite", "games",
    "profiles", "tools", "guides", "laptop",
]

# Sidebar "Tweaks" sub-categories (no profiles/tools â€” those are top-level nav).
TWEAK_ORDER = [
    "cpu", "gpu", "ram", "mouse", "keyboard", "input",
    "network", "storage", "system", "performance", "fortnite", "games",
    "guides", "laptop",
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
    "system": "Windows",
    "performance": "Performance",
    "fortnite": "Fortnite",
    "games": "Games",
    "guides": "Guides",
    "laptop": "Laptop",
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
    ("system", "Windows / System"),
    ("performance", "Performance"),
    ("fortnite", "Fortnite"),
    ("games", "Games"),
    ("guides", "Guides"),
    ("laptop", "Laptop"),
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

