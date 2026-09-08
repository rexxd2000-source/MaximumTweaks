"""Category groups for the redesigned UI.

The database stores ~45 raw categories; the UI groups them into 12 clear,
user-facing sections. Every raw category maps to exactly one group.
"""
from __future__ import annotations

from database import TWEAKS

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
        "color": "#60a5fa",
        "blurb": "Processor scheduling, power management and Windows CPU optimizations.",
        "db": ["CPU", "Scheduling"],
    },
    "gpu": {
        "key": "gpu",
        "title": "GPU Tweaks",
        "icon": "\u25c6",
        "color": "#c084fc",
        "blurb": "NVIDIA/AMD optimizations, GPU scheduling, graphics settings and rendering.",
        "db": ["GPU", "NVIDIA", "AMD", "Intel", "Windows Graphics", "DirectX", "DirectX 12"],
    },
    "ram": {
        "key": "ram",
        "title": "RAM Tweaks",
        "icon": "\u2588",
        "color": "#f472b6",
        "blurb": "Memory management, virtual memory and background memory behavior.",
        "db": ["RAM"],
    },
    "mouse": {
        "key": "mouse",
        "title": "Mouse Tweaks",
        "icon": "\u21a8",
        "color": "#fb923c",
        "blurb": "Pointer precision, acceleration and polling for sharper response.",
        "db": ["Mouse"],
    },
    "keyboard": {
        "key": "keyboard",
        "title": "Keyboard Tweaks",
        "icon": "\u2328",
        "color": "#a3e635",
        "blurb": "Repeat delay, filter keys and keyboard input responsiveness.",
        "db": ["Keyboard"],
    },
    "input": {
        "key": "input",
        "title": "Pointer & Input",
        "icon": "\u2694",
        "color": "#e879f9",
        "blurb": "Input-latency reductions so your clicks, keystrokes and pointer inputs register faster.",
        "db": ["Input Latency", "Aim", "Precision Tweaks"],
    },
    "network": {
        "key": "network",
        "title": "Network Tweaks",
        "icon": "\u2637",
        "color": "#22d3ee",
        "blurb": "TCP/IP stack, Ethernet and Wi-Fi tuning for lower ping and stable connections.",
        "db": ["Network", "Ethernet", "Wi-Fi"],
    },
    "storage": {
        "key": "storage",
        "title": "Storage / SSD",
        "icon": "\u25b6",
        "color": "#2dd4bf",
        "blurb": "NTFS, SSD trimming, filesystem and disk behavior optimizations.",
        "db": ["Storage"],
    },
    "system": {
        "key": "system",
        "title": "Windows / System",
        "icon": "\u2699",
        "color": "#94a3b8",
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
        "color": "#38bdf8",
        "blurb": "FPS boosting and frame-pacing optimizations for smoother, more consistent gameplay.",
        "db": ["FPS", "Frame Time"],
    },
    "fortnite": {
        "key": "fortnite",
        "title": "Fortnite",
        "icon": "\u25c9",
        "color": "#818cf8",
        "blurb": "Fortnite-only optimizations for FPS, input latency, graphics and network.",
        "db": ["Fortnite"],
    },
    "games": {
        "key": "games",
        "title": "Game Tweaks",
        "icon": "\u2605",
        "color": "#fb7185",
        "blurb": "Game Mode, DVR, Game Bar and general gaming performance settings.",
        "db": ["Gaming"],
    },
    "profiles": {
        "key": "profiles",
        "title": "Game Profiles",
        "icon": "\u2654",
        "color": "#a78bfa",
        "blurb": "One-click per-game performance profiles for popular esports titles.",
        "db": ["Game Profiles"],
    },
    "tools": {
        "key": "tools",
        "title": "System Tools",
        "icon": "\u26cf",
        "color": "#5eead4",
        "blurb": "Diagnostics, repair and quick-access tools for your system.",
        "db": ["System Tools", "Diagnostics", "Repair"],
    },
}

GROUP_ORDER = [
    "cpu", "gpu", "ram", "mouse", "keyboard", "input",
    "network", "storage", "system", "performance", "fortnite", "games",
    "profiles", "tools",
]

# Sidebar "Tweaks" sub-categories (no profiles/tools â€” those are top-level nav).
TWEAK_ORDER = [
    "cpu", "gpu", "ram", "mouse", "keyboard", "input",
    "network", "storage", "system", "performance", "fortnite", "games",
]

# Raw category -> owning group key (every raw category maps to one group).
GROUP_BY_CAT = {}
for _k in GROUP_ORDER:
    for _c in CATEGORY_GROUPS[_k]["db"]:
        GROUP_BY_CAT.setdefault(_c, _k)

# Tool-like tweaks (reports, guidance, repair/cleanup actions) that live inside
# other categories but belong in the Tools section. Re-routed by id so the
# Windows/System section no longer shows them.
TOOLS_IDS = {
    # BIOS guidance / reports
    "bios-001", "bios-002", "bios-003", "bios-004", "bios-005", "bios-006",
    "bios-007", "bios-008", "bios-009", "bios-010", "bios-011", "bios-012",
    # Monitor checks / guidance
    "mon-003", "mon-004", "mon-010", "mon-012", "mon-014",
    # Display guidance / reset
    "disp-006", "disp-007", "disp-011",
    # USB reports / guidance / reset
    "usb-003", "usb-004", "usb-005", "usb-007", "usb-008", "usb-010", "usb-012",
    # Power plan tools
    "pp-001", "pp-006", "pp-007", "pp-010", "pp-012",
    # Startup reports / guidance / cleanup
    "start-001", "start-008", "start-011",
    # System tools
    "sys-008", "sys-011",
    # Audio report
    "audio-012",
    # Debloat cleanup
    "db-014",
    # Security guidance
    "sec-007",
}

# Monochromatic design: every category icon is the same neutral slate tone.
NEUTRAL_ICON = "#94a3b8"
for _g in CATEGORY_GROUPS.values():
    _g["color"] = NEUTRAL_ICON

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

