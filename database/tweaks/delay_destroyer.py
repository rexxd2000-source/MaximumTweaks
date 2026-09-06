"""Category: Delay Destroyer — latency-focused optimizations.

Each tweak targets a specific source of input, system, frame, network, or
USB latency.  Every tweak is unique and does NOT overlap with existing
Maximum tweaks in other categories.

Registry paths and default values are verified against Windows 10/11.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Delay Destroyer", win_default="10,11")
CATEGORY = "Delay Destroyer"

TWEAKS = validate_module("delay_destroyer", [

    # ── INPUT LATENCY ─────────────────────────────────────────────

    T("dd-001", "Reduce Mouse Input Buffer",
      "Shrinks the OS mouse input queue so cursor updates reach applications faster.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\mouclass\Parameters",
           "MouseDataQueueSize", 16, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\mouclass\Parameters",
           "MouseDataQueueSize", 100, "DWORD"),
      ],
      why="A deep input queue adds latency: each queued event waits behind earlier ones. "
          "Reducing the buffer means the latest position is processed sooner.",
      changes="Sets MouseDataQueueSize to 16 (default ~100).",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["mouse", "input", "buffer", "latency"],
      sub_category="Input Latency"),

    T("dd-002", "Reduce Keyboard Input Buffer",
      "Shrinks the OS keyboard input queue so key events reach applications faster.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\kbdclass\Parameters",
           "KeyboardDataQueueSize", 16, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\kbdclass\Parameters",
           "KeyboardDataQueueSize", 100, "DWORD"),
      ],
      why="A deep keyboard queue adds latency to every keystroke. Reducing the buffer "
          "means key-down events are delivered to the foreground app sooner.",
      changes="Sets KeyboardDataQueueSize to 16 (default ~100).",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["keyboard", "input", "buffer", "latency"],
      sub_category="Input Latency"),

    T("dd-003", "Disable Mouse Ballistics",
      "Disables the OS-level mouse sensitivity scaling for raw 1:1 pointer movement.",
      actions=[
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseSensitivity", "10", "STRING"),
      ],
      revert=[
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseSensitivity", "6", "STRING"),
      ],
      why="MouseSensitivity at 10 gives a 1:1 ratio between physical and on-screen "
          "movement. The default of 6 applies scaling that can distort fast swipes.",
      changes="Sets MouseSensitivity to 10 (1:1 ratio).",
      risk="safe", impact="low", recommended="recommended",
      tags=["mouse", "sensitivity", "ballistics", "input"],
      sub_category="Input Latency"),

    T("dd-004", "Optimize HID Button Response",
      "Reduces the low-level hook timeout so HID button presses are processed faster.",
      actions=[
          ("reg", "HKCU", r"Control Panel\Desktop", "LowLevelHooksTimeout", 1000, "DWORD"),
      ],
      revert=[
          ("regdel", "HKCU", r"Control Panel\Desktop", "LowLevelHooksTimeout"),
      ],
      why="Windows kills low-level hooks that don't respond within 300 ms. Setting a "
          "higher timeout prevents premature hook termination during high-load moments.",
      changes="Sets LowLevelHooksTimeout to 1000 ms.",
      risk="safe", impact="low", recommended="recommended",
      tags=["hid", "hooks", "input", "timeout"],
      sub_category="Input Latency"),

    T("dd-005", "Disable USB Hub Power Management",
      "Prevents USB hubs from entering power-saving states that add wake latency.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB", "DisableHPS", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB", "DisableHPS", 0, "DWORD"),
      ],
      why="USB hub power management can put ports to sleep, adding wake latency when "
          "a device is accessed. Disabling it keeps hubs fully active.",
      changes="Disables USB hub power management.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["usb", "hub", "power", "latency"],
      sub_category="Input Latency"),

    # ── GAMING & FRAME TIME ──────────────────────────────────────

    T("dd-010", "Disable Game Bar Tips",
      "Disables Game Bar tip notifications that appear during gameplay.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar", "ShowStartupPanel", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar", "ShowStartupPanel", 1, "DWORD"),
      ],
      why="Game Bar tips can pop up during gameplay, causing focus loss and frame drops. "
          "Disabling them prevents these interruptions.",
      changes="Disables Game Bar tip notifications.",
      risk="safe", impact="low", recommended="recommended",
      tags=["gamebar", "tips", "gaming", "overlay"],
      sub_category="Gaming & Frame Time"),

    T("dd-011", "Disable Game Bar Keyboard Shortcuts",
      "Disables Game Bar keyboard shortcuts that can trigger during gameplay.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar", "UseNexusForGameBarEnabled", 0, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\GameBar", "UseNexusForGameBarEnabled", 1, "DWORD"),
      ],
      why="Game Bar keyboard shortcuts (like Win+G) can accidentally trigger during "
          "intense gameplay, causing focus loss and frame drops.",
      changes="Disables Game Bar keyboard shortcut integration.",
      risk="safe", impact="low", recommended="recommended",
      tags=["gamebar", "shortcuts", "gaming", "overlay"],
      sub_category="Gaming & Frame Time"),

    T("dd-012", "Optimize Fullscreen Game Priority",
      "Boosts the CPU priority of fullscreen exclusive games.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "AllTasksPriority", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "AllTasksPriority", 0, "DWORD"),
      ],
      why="AllTasksPriority raises the base priority of all multimedia threads, giving "
          "fullscreen games a scheduling edge over background work.",
      changes="Sets multimedia AllTasksPriority to 1 (default 0).",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["priority", "fullscreen", "gaming", "mmcss"],
      sub_category="Gaming & Frame Time"),

    # ── NETWORK ──────────────────────────────────────────────────

    T("dd-013", "Optimize TCP ACK Frequency",
      "Disables delayed ACKs so TCP acknowledgments are sent immediately.",
      actions=[
          ("regall", "HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
           "TcpAckFrequency", 1, "DWORD"),
      ],
      revert=[
          ("regdelall", "HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
           "TcpAckFrequency"),
      ],
      why="Delayed ACKs batch acknowledgments to reduce packet count, but add up to "
          "200 ms of latency per interaction. Immediate ACKs reduce game network lag.",
      changes="Sets TcpAckFrequency to 1 (immediate ACK) on all interfaces.",
      risk="safe", impact="high", recommended="recommended", admin=True,
      tags=["tcp", "ack", "latency", "network"],
      sub_category="Network"),

    T("dd-014", "Disable TCP Nagle Algorithm",
      "Disables Nagle's algorithm so small packets are sent immediately.",
      actions=[
          ("regall", "HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
           "TcpNoDelay", 1, "DWORD"),
      ],
      revert=[
          ("regdelall", "HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces",
           "TcpNoDelay"),
      ],
      why="Nagle's algorithm buffers small TCP writes to improve throughput, but adds "
          "latency to real-time game traffic. Disabling it sends packets immediately.",
      changes="Sets TcpNoDelay to 1 on all network interfaces.",
      risk="low", impact="high", recommended="recommended", admin=True,
      tags=["tcp", "nagle", "latency", "network"],
      sub_category="Network"),

    T("dd-015", "Optimize Network Interrupt Moderation",
      "Disables interrupt moderation on network adapters for lower latency.",
      actions=[
          ("regall", "HKLM", r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}",
           "InterruptModeration", 0, "DWORD"),
      ],
      revert=[
          ("regdelall", "HKLM", r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}",
           "InterruptModeration"),
      ],
      why="Interrupt moderation batches network interrupts to reduce CPU overhead, but "
          "adds latency to each packet. Disabling it processes packets immediately.",
      changes="Disables interrupt moderation on all network adapters.",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["network", "interrupt", "moderation", "latency"],
      sub_category="Network"),

    T("dd-016", "Optimize DNS Cache Timeout",
      "Reduces DNS cache timeout to refresh DNS entries more frequently.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\Dnscache\Parameters",
           "MaxCacheTtl", 300, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\Dnscache\Parameters",
           "MaxCacheTtl", 86400, "DWORD"),
      ],
      why="A long DNS cache timeout can cause connections to use stale DNS entries after "
          "server migrations. A shorter timeout ensures fresh lookups.",
      changes="Sets DNS cache MaxCacheTtl to 300 seconds (default 86400).",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["dns", "cache", "network", "latency"],
      sub_category="Network"),

    # ── USB & PERIPHERALS ────────────────────────────────────────

    T("dd-017", "Optimize USB Transfer Timeout",
      "Reduces the USB transfer timeout for faster error recovery.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB",
           "DefaultRwTimeout", 5000, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB",
           "DefaultRwTimeout", 10000, "DWORD"),
      ],
      why="A shorter USB transfer timeout means faster detection and recovery from "
          "transfer errors, reducing momentary input device freezes.",
      changes="Sets USB DefaultRwTimeout to 5000 ms (default ~10000).",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["usb", "timeout", "transfer", "latency"],
      sub_category="USB & Peripherals"),

    T("dd-018", "Optimize USB Endpoint Response",
      "Reduces USB endpoint error recovery time for faster device responsiveness.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB",
           "ErrorRecoveryTimeout", 5000, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB",
           "ErrorRecoveryTimeout", 10000, "DWORD"),
      ],
      why="USB endpoint error recovery adds latency when a transfer fails. Reducing "
          "the timeout means devices recover from errors faster.",
      changes="Sets USB ErrorRecoveryTimeout to 5000 ms (default ~10000).",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["usb", "endpoint", "error", "latency"],
      sub_category="USB & Peripherals"),

    T("dd-019", "Optimize USB Selective Suspend Delay",
      "Reduces the delay before USB devices enter selective suspend.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB",
           "USBSelectiveSuspendDelay", 5, "DWORD"),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\USB",
           "USBSelectiveSuspendDelay", 30, "DWORD"),
      ],
      why="A shorter selective suspend delay means USB devices enter low-power states "
          "sooner when idle, freeing resources for active devices.",
      changes="Sets USBSelectiveSuspendDelay to 5 seconds (default 30).",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["usb", "selective", "suspend", "power"],
      sub_category="USB & Peripherals"),
])
