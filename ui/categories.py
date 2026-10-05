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


def logo_data_uri(key: str) -> str:
    """Base64 data URI for a category logo, or '' if the PNG is missing.

    Used by the HTML pages (dashboard + tweak cards) so the real category
    logos render with no filesystem-path dependence in either dev or the
    frozen (PyInstaller extraction-dir) builds.
    """
    p = logo_path(key)
    if not p.is_file():
        return ""
    import base64

    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")

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
    "Game Process": "CPU",
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
    "Delay Destroyer": "Delay Destroyer",
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
        "logo": "cpu",
        "color": "#3FDC98",
        "blurb": "Processor scheduling, power management and Windows CPU optimizations.",
        "db": ["CPU", "Scheduling", "Game Process"],
    },
    "gpu": {
        "key": "gpu",
        "title": "GPU Tweaks",
        "logo": "gpu",
        "color": "#3FDC98",
        "blurb": "NVIDIA/AMD/Intel GPU optimizations, scheduling, and vendor-specific driver settings.",
        "db": ["GPU", "NVIDIA", "AMD", "Intel"],
    },
    "ram": {
        "key": "ram",
        "title": "RAM Tweaks",
        "logo": "ram",
        "color": "#3FDC98",
        "blurb": "Memory management, virtual memory and background memory behavior.",
        "db": ["RAM"],
    },
    "mouse": {
        "key": "mouse",
        "title": "Mouse Tweaks",
        "logo": "mouse",
        "color": "#FF6F6F",
        "blurb": "Pointer precision, acceleration and polling for sharper response.",
        "db": ["Mouse"],
    },
    "keyboard": {
        "key": "keyboard",
        "title": "Keyboard Tweaks",
        "logo": "keyboard",
        "color": "#FF6F6F",
        "blurb": "Repeat delay, filter keys and keyboard input responsiveness.",
        "db": ["Keyboard"],
    },
    "input": {
        "key": "input",
        "title": "Pointer & Input",
        "logo": "input",
        "color": "#FF6F6F",
        "blurb": "Input-latency reductions so your clicks, keystrokes and pointer inputs register faster.",
        "db": ["Input Latency", "Aim", "Precision Tweaks"],
    },
    "network": {
        "key": "network",
        "title": "Network Tweaks",
        "logo": "network",
        "color": "#6C93FF",
        "blurb": "TCP/IP stack, Ethernet and Wi-Fi tuning for lower ping and stable connections.",
        "db": ["Network", "Ethernet", "Wi-Fi"],
    },
    "storage": {
        "key": "storage",
        "title": "Storage / SSD",
        "logo": "storage",
        "color": "#6C93FF",
        "blurb": "NTFS, SSD trimming, filesystem and disk behavior optimizations.",
        "db": ["Storage"],
    },
    "audio": {
        "key": "audio",
        "title": "Audio Tweaks",
        "logo": "audio",
        "color": "#6C93FF",
        "blurb": "Deep Windows audio engine, WASAPI, MMCSS scheduling, USB/Bluetooth audio, microphones, and gaming audio optimizations.",
        "db": ["Audio"],
    },
    "system": {
        "key": "system",
        "title": "Windows / System",
        "logo": "system",
        "color": "#6C93FF",
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
        "logo": "power",
        "color": "#3FDC98",
        "blurb": "Power plans, CPU power states, sleep/hibernate and energy settings. Includes the Maximum Power Plan.",
        "db": ["Power Plans", "Power"],
    },
    "performance": {
        "key": "performance",
        "title": "Performance Tweaks",
        "logo": "performance",
        "color": "#3FDC98",
        "blurb": "FPS boosting and frame-pacing optimizations for smoother, more consistent gameplay.",
        "db": ["Performance", "FPS", "Frame Time"],
    },
    "fortnite": {
        "key": "fortnite",
        "title": "Fortnite",
        "logo": "fortnite",
        "color": "#E879C9",
        "blurb": "Fortnite-only optimizations for FPS, input latency, graphics and network.",
        "db": ["Fortnite"],
    },
    "games": {
        "key": "games",
        "title": "Game Tweaks",
        "logo": "games",
        "color": "#3FDC98",
        "blurb": "Game Mode, DVR, Game Bar and general gaming performance settings.",
        "db": ["Gaming"],
    },
    "profiles": {
        "key": "profiles",
        "title": "Game Profiles",
        "logo": "profiles",
        "color": "#E879C9",
        "blurb": "One-click per-game performance profiles for popular esports titles.",
        "db": ["Game Profiles"],
    },
    "tools": {
        "key": "tools",
        "title": "System Tools",
        "logo": "tools",
        "color": "#FFB454",
        "blurb": "Diagnostics, repair and quick-access tools for your system.",
        "db": ["System Tools", "Diagnostics", "Repair"],
    },
    "laptop": {
        "key": "laptop",
        "title": "Laptop Tweaks",
        "logo": "laptop",
        "color": "#6C93FF",
        "blurb": "Battery, lid, hybrid-graphics and dedicated-GPU settings "
                "specific to laptops.",
        "db": ["Laptop"],
    },
    "fpsboost": {
        "key": "fpsboost",
        "title": "FPS Boost",
        "logo": "fpsboost",
        "color": "#3FDC98",
        "blurb": "Proven system-level tweaks to maximize FPS — VBS, ReBAR, "
                "core parking, GPU power management and more.",
        "db": ["FPS Boost"],
    },
    "delay_destroyer": {
        "key": "delay_destroyer",
        "title": "Delay Destroyer",
        "logo": "performance",
        "color": "#FFB454",
        "blurb": "Input latency, system responsiveness, frame pacing, network and USB tweaks — one card per optimization.",
        "db": ["Delay Destroyer"],
    },
}

GROUP_ORDER = [
    "cpu", "gpu", "ram", "power", "mouse", "keyboard", "input",
    "network", "storage", "audio", "system", "performance", "fortnite",
    "games", "profiles", "tools", "laptop", "fpsboost", "delay_destroyer",
]

# Sidebar "Tweaks" sub-categories (profiles/tools are top-level nav).
TWEAK_ORDER = [
    "cpu", "gpu", "ram", "power", "mouse", "keyboard", "input",
    "network", "storage", "audio", "system", "performance", "fortnite",
    "games", "laptop", "fpsboost", "delay_destroyer",
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

# Diagnostic scans/tests that used to sit inside tweak categories (they were
# wrongly filed as System/Tools "tweaks" — they don't change anything, they
# measure). Hidden from every tweak group; re-homed as real tests on the
# Diagnostics page (ui/pages/diagnostics.py + engine/diagnostics.py).
DIAG_IDS = {
    "diag-new-002",   # GPU Throttling Reason Scanner
    "diag-new-005",   # Background Game Recording Process Scanner
    "diag-new-001",   # GPU PCIe Link Width / Speed Diagnostic
    "diag-new-003",   # Hard Fault / Memory Pressure Detector
    "diag-new-004",   # Refresh Rate / Display Mode Verification
    "net-new-001",    # Network Jitter + Packet Loss Test
    "net-new-002",    # Bufferbloat Test
    "diag-009",       # Network Latency Test
    "ram-012",        # Memory Stability Test (Windows Memory Diagnostic)
    "stor-011",       # NTFS Scan (Read-Only)
    "rep-003",        # Scan Disk for Errors
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
    "delay_destroyer": "Delay Destroyer",
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


def compatible_tweaks(tweaks, eval_states, profile=None):
    """Tweaks that belong on THIS machine (dashboard hero + scan count).

    Matches the filter the rest of the UI uses: no guidance rows, nothing the
    evaluator marked incompatible, and no form-factor mismatch (the whole
    Laptop category is laptop-only hardware/OS behaviour even though those DB
    rows carry no gates).
    """
    is_laptop = bool((profile or {}).get("laptop"))
    out = []
    for t in tweaks:
        if t.get("guidance"):
            continue
        state = (eval_states or {}).get(t["id"], {}).get("state", "ready")
        if state == "incompatible":
            continue
        when = t.get("when") or {}
        if when.get("laptop") is True and not is_laptop:
            continue
        if when.get("laptop") is False and is_laptop:
            continue
        if group_key_for_category(t.get("category") or "") == "laptop" \
                and not is_laptop:
            continue
        out.append(t)
    return out

# Fortnite tweaks grouped into subsections (id lists, verified against DB).
FORTNITE_SECTIONS = {
    "Performance": ["fn-001"],
    "Input / Latency": ["fn-003", "fn-027"],
    "FPS": ["fn-002", "fn-004", "fn-034"],
    "Graphics": ["fn-005", "fn-006", "fn-009", "fn-011", "fn-012",
                 "fn-013", "fn-014", "fn-015", "fn-016", "fn-017",
                 "fn-018", "fn-019", "fn-020", "fn-021", "fn-022",
                 "fn-023", "fn-024", "fn-025", "fn-026", "fn-028",
                 "fn-029", "fn-035", "fn-036", "fn-037", "fn-038"],
    "Rendering / Latency": ["fn-030", "fn-031", "fn-032"],
    "Mouse / Pointer": ["fn-033"],
    "Network": ["fn-010"],
    "Launch Options": ["fn-007"],
    "Config": ["fn-008"],
}
FORTNITE_ORDER = list(FORTNITE_SECTIONS)

# Game profile tweak ids, kept in a stable display order.
GAME_PROFILE_IDS = [
    "gp-001", "gp-002", "gp-003",
]


def group_tweaks(key: str) -> list[dict]:
    db_cats = set(CATEGORY_GROUPS[key]["db"])
    if key == "tools":
        return [t for t in TWEAKS
                if (t["category"] in db_cats or t["id"] in TOOLS_IDS)
                and t["id"] not in DIAG_IDS]
    return [t for t in TWEAKS if t["category"] in db_cats
            and t["id"] not in TOOLS_IDS and t["id"] not in DIAG_IDS]


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


# == CPU vendor/form-factor filtering ==================================
# Works like GPU filtering: universal tweaks (no when.cpu_vendor / when.laptop)
# are ALWAYS shown; vendor/form-factor tagged tweaks are only shown when
# they match the detected hardware.

# The seven CPU categories offered by the CPU page picker.  This is a manual
# navigation choice, NOT hardware detection: picking "Intel Hybrid" filters the
# card list but does not claim the machine is a hybrid CPU, and does not
# authorise applying a card the machine does not support.
CPU_FAMILIES: list[dict] = [
    {
        "key": "amd_am4",
        "label": "AMD AM4 (non-X3D)",
        "sub": "Ryzen 1000-5000",
        "features": "Boost, power policy, unparking",
        "color": "#ED1C24",
    },
    {
        "key": "amd_am4_x3d",
        "label": "AMD AM4 X3D",
        "sub": "Ryzen 5000 X3D",
        "features": "Boost limits, unparking, 3D V-Cache aware",
        "color": "#ED1C24",
    },
    {
        "key": "amd_am5",
        "label": "AMD AM5 (non-X3D)",
        "sub": "Ryzen 7000+",
        "features": "Boost, power policy, unparking",
        "color": "#ED1C24",
    },
    {
        "key": "amd_am5_x3d",
        "label": "AMD AM5 X3D",
        "sub": "Ryzen 7000+ X3D / X",
        "features": "Boost limits, unparking, V-Cache aware",
        "color": "#ED1C24",
    },
    {
        "key": "intel_legacy",
        "label": "Intel Legacy / Non-Hybrid",
        "sub": "Core i7/i9, no P-cores+E-cores",
        "features": "Boost, power policy, turbo",
        "color": "#0071C5",
    },
    {
        "key": "intel_hybrid",
        "label": "Intel Hybrid",
        "sub": "Alder Lake+ 12th gen+ (P-cores + E-cores)",
        "features": "P-core / E-core scheduling preserved",
        "color": "#0071C5",
    },
    {
        "key": "intel_core_ultra",
        "label": "Intel Core Ultra",
        "sub": "Meteor Lake+",
        "features": "Tile / E-core aware scheduling",
        "color": "#0071C5",
    },
]

CPU_FAMILY_KEYS = [f["key"] for f in CPU_FAMILIES]


def cpu_filter_tweaks(key: str, cpu_vendor: str | None = None,
                      is_laptop: bool | None = None,
                      cpu_family: str | None = None) -> list[dict]:
    """Return tweaks for the CPU category filtered by vendor, form factor and family.

    Universal tweaks (no ``when.cpu_vendor`` / ``when.laptop`` /
    ``when.cpu_family``) are always shown.  Tagged tweaks only appear when the
    matching selection matches.

    ``cpu_family`` is the manual CPU-page pick, not a hardware probe: a card is
    shown because the user asked for that category, and the executor still
    verifies the underlying setting exists before writing.  A family-tagged
    card is hidden while no family is selected, so an AMD-only control is never
    shown on the undifferentiated list.
    """
    all_tweaks = group_tweaks(key)
    out = []
    for t in all_tweaks:
        when = t.get("when", {})
        req_vendor = when.get("cpu_vendor")
        req_laptop = when.get("laptop")
        req_family = when.get("cpu_family")
        if req_vendor and cpu_vendor:
            if cpu_vendor.lower() not in [v.lower() for v in req_vendor]:
                continue
        if req_family:
            if not cpu_family:
                continue
            if cpu_family not in req_family:
                continue
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

