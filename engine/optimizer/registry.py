"""Concrete per-subsystem optimizers and their category-group mapping.

Each optimizer is a small :class:`~engine.optimizer.base.Optimizer` subclass
that owns one subsystem: which probe feeds it, which tweaks it scans, and any
subsystem-specific evaluation rules.  ``GROUP_OPTIMIZERS`` maps each UI tweak
group to the list of optimizers exposed on that group's page, so every
category has its own dedicated Optimize control and no global button exists.
"""
from __future__ import annotations

from .base import Optimizer, Rec, READY_STATES

# TCP-related tag clusters used to carve TCP/UDP/DNS subsystems out of the
# broad Network group without duplicating the database.
_TCP_TAGS = ("tcp", "tcpip", "window", "1323", "timestamps", "rss", "nagle",
             "ack", "tcpa", "tcpip6", "mtu", "sack")
_UDP_TAGS = ("udp",)
_DNS_TAGS = ("dns",)


class CpuOptimizer(Optimizer):
    key = "cpu"
    title = "Optimize CPU"
    subtitle = ("CPU scheduling, power management and Windows processor "
                "optimizations that match this CPU.")
    probe_name = "cpu"
    categories = ("CPU", "Scheduling")


class GpuOptimizer(Optimizer):
    key = "gpu"
    title = "Optimize GPU"
    subtitle = ("GPU settings filtered to the detected vendor, driver and "
                "capabilities.")
    probe_name = "gpu"
    categories = ("GPU", "NVIDIA", "AMD", "Intel", "Windows Graphics",
                  "DirectX", "DirectX 12")


class RamOptimizer(Optimizer):
    key = "ram"
    title = "Optimize RAM"
    subtitle = "Memory-management tweaks applicable to the installed modules."
    probe_name = "ram"
    categories = ("RAM",)


class NetworkOptimizer(Optimizer):
    key = "network"
    title = "Optimize Network"
    subtitle = ("Network-adapter and stack tweaks verified against the active "
                "adapter (manufacturer, driver, link type).")
    probe_name = "network"
    categories = ("Network", "Ethernet", "Wi-Fi")
    tags = _TCP_TAGS + _DNS_TAGS

    def evaluate(self, tweak, det, ctx, profile):
        media = (det.get("data") or {}).get("media")
        tid = tweak["id"]
        if tid.startswith("wifi") and media != "wifi":
            return Rec(tweak, "not_applicable",
                       "Requires an active Wi-Fi adapter.")
        if tid.startswith("eth") and media == "wifi":
            return Rec(tweak, "not_applicable",
                       "Requires a wired Ethernet adapter.")
        return super().evaluate(tweak, det, ctx, profile)


class TcpOptimizer(Optimizer):
    key = "tcp"
    title = "Optimize TCP"
    subtitle = "TCP/IP stack tuning — window scaling, timestamps, RSS, Nagle."
    probe_name = "tcp"
    tags = _TCP_TAGS


class UdpOptimizer(Optimizer):
    key = "udp"
    title = "Optimize UDP"
    subtitle = "UDP offload and checksum settings exposed by the NIC driver."
    probe_name = "udp"
    tags = _UDP_TAGS


class DnsOptimizer(Optimizer):
    key = "dns"
    title = "Optimize DNS"
    subtitle = "DNS resolution settings against the resolvers currently in use."
    probe_name = "dns"
    tags = _DNS_TAGS

    def evaluate(self, tweak, det, ctx, profile):
        rec = super().evaluate(tweak, det, ctx, profile)
        if rec.state == "compatible" and tweak["id"] == "net-014":
            rec.reason = ("Flushes the DNS resolver cache (one-shot command, "
                          "not a persistent setting).")
        return rec


class MouseOptimizer(Optimizer):
    key = "mouse"
    title = "Optimize Mouse"
    subtitle = ("Pointer precision and acceleration settings for the detected "
                "pointing device.")
    probe_name = "mouse"
    categories = ("Mouse",)


class KeyboardOptimizer(Optimizer):
    key = "keyboard"
    title = "Optimize Keyboard"
    subtitle = "Keyboard repeat and input responsiveness settings."
    probe_name = "keyboard"
    categories = ("Keyboard",)


class InputOptimizer(Optimizer):
    key = "input"
    title = "Optimize Input"
    subtitle = "Input-latency reductions for mouse, keyboard and gamepad."
    probe_name = "input"
    categories = ("Input Latency", "Aim", "Precision Tweaks")


class StorageOptimizer(Optimizer):
    key = "storage"
    title = "Optimize Storage"
    subtitle = "NTFS, TRIM and disk-behavior optimizations for the detected drives."
    probe_name = "storage"
    categories = ("Storage",)


class PowerOptimizer(Optimizer):
    key = "power"
    title = "Optimize Power"
    subtitle = ("Power-plan and CPU power settings appropriate for this "
                "laptop/desktop.")
    probe_name = "power"
    categories = ("Power", "Power Plans")


class DisplayOptimizer(Optimizer):
    key = "display"
    title = "Optimize Display"
    subtitle = "Display settings compatible with the detected monitors/GPU."
    probe_name = "display"
    categories = ("Display", "Monitor")


class AudioOptimizer(Optimizer):
    key = "audio"
    title = "Optimize Audio"
    subtitle = "Audio-device and Windows audio configuration settings."
    probe_name = "audio"
    categories = ("Audio",)


class SystemOptimizer(Optimizer):
    key = "system"
    title = "Optimize Windows"
    subtitle = ("Windows shell and system tweaks compatible with this edition, "
                "version and build.")
    probe_name = "system"
    categories = ("Windows", "System", "Advanced", "Experimental",
                  "Security & Performance")


class ServicesOptimizer(Optimizer):
    key = "services"
    title = "Optimize Services"
    subtitle = ("Windows services analyzed by live state — never blindly "
                "disabled; every recommendation is checked against the "
                "installed service.")
    probe_name = "services"
    categories = ("Services",)


class PrivacyOptimizer(Optimizer):
    key = "privacy"
    title = "Optimize Privacy"
    subtitle = "Privacy and telemetry settings read from the live configuration."
    probe_name = "privacy"
    categories = ("Privacy", "Telemetry")


class RegistryOptimizer(Optimizer):
    key = "registry"
    title = "Optimize Registry"
    subtitle = "Registry-behavior tweaks applicable to this Windows build."
    probe_name = "registry"
    categories = ("Registry",)


class StartupOptimizer(Optimizer):
    key = "startup"
    title = "Optimize Startup"
    subtitle = "Startup-behavior tweaks checked against the current startup set."
    probe_name = "startup"
    categories = ("Startup",)


class UsbOptimizer(Optimizer):
    key = "usb"
    title = "Optimize USB"
    subtitle = "USB power and polling tweaks."
    probe_name = "usb"
    categories = ("USB",)


class PerformanceOptimizer(Optimizer):
    key = "performance"
    title = "Optimize Performance"
    subtitle = "FPS / frame-pacing optimizations for the detected CPU/GPU."
    probe_name = "performance"
    categories = ("FPS", "Frame Time")


class FortniteOptimizer(Optimizer):
    key = "fortnite"
    title = "Optimize Fortnite"
    subtitle = "Fortnite-only optimizations (config- and hardware-aware)."
    probe_name = "fortnite"
    categories = ("Fortnite",)


class GamesOptimizer(Optimizer):
    key = "games"
    title = "Optimize Games"
    subtitle = "Game Mode / Game Bar / DVR settings for the detected system."
    probe_name = "games"
    categories = ("Gaming",)


class DiagnosticsOptimizer(Optimizer):
    key = "diagnostics"
    title = "Diagnostics"
    subtitle = "Reports and diagnostics for this system."
    probe_name = "diagnostics"
    categories = ("Diagnostics",)


#: Every optimizer, keyed by its subsystem key.
OPTIMIZERS: dict[str, Optimizer] = {
    cls.key: cls() for cls in (
        CpuOptimizer, GpuOptimizer, RamOptimizer,
        NetworkOptimizer, TcpOptimizer, UdpOptimizer, DnsOptimizer,
        MouseOptimizer, KeyboardOptimizer, InputOptimizer,
        StorageOptimizer, PowerOptimizer, DisplayOptimizer, AudioOptimizer,
        SystemOptimizer, ServicesOptimizer, PrivacyOptimizer,
        RegistryOptimizer, StartupOptimizer, UsbOptimizer,
        PerformanceOptimizer, FortniteOptimizer, GamesOptimizer,
        DiagnosticsOptimizer,
    )
}

#: UI tweak group -> the Optimize controls shown on that page.
GROUP_OPTIMIZERS: dict[str, list[str]] = {
    "cpu": ["cpu"],
    "gpu": ["gpu"],
    "ram": ["ram"],
    "mouse": ["mouse"],
    "keyboard": ["keyboard"],
    "input": ["input"],
    "network": ["network", "tcp", "udp", "dns"],
    "storage": ["storage"],
    "audio": ["audio"],
    "system": ["system", "services", "privacy", "registry", "startup",
               "power", "display", "usb"],
    "performance": ["performance"],
    "fortnite": ["fortnite"],
    "games": ["games"],
    "tools": ["diagnostics"],
}

#: Optimizer key -> short button label (e.g. "TCP", "Services").
BUTTON_LABELS = {
    "cpu": "CPU", "gpu": "GPU", "ram": "RAM",
    "network": "Network", "tcp": "TCP", "udp": "UDP", "dns": "DNS",
    "mouse": "Mouse", "keyboard": "Keyboard", "input": "Input",
    "storage": "Storage", "power": "Power", "display": "Display",
    "audio": "Audio", "system": "System", "services": "Services",
    "privacy": "Privacy", "registry": "Registry", "startup": "Startup",
    "usb": "USB", "performance": "Performance", "fortnite": "Fortnite",
    "games": "Games", "diagnostics": "Diagnostics",
}
