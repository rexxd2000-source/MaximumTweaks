"""Category: Precision Tweaks — preset precision tweaks under Pointer & Input.

Each preset is a curated bundle of real, revert-safe registry/power settings that
map to the described mechanism (frame timing, packet flow, click-to-shot path,
controller input, etc.). Every card shows a "Crafted for..." tag via the
`crafted_for` field.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Precision Tweaks", win_default="7,8,10,11")
CATEGORY = "Precision Tweaks"

_MMCSS = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
_TCPIP = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"
_PSCHED = r"SOFTWARE\Policies\Microsoft\Windows\Psched"
_CPARK = (r"SOFTWARE\Policies\Microsoft\Windows\Power\PowerSettings"
          r"\54533251-82be-4824-96c1-47b60b740d00"
          r"\0cc5b4c1-d36e-4dc5-9e1c-4d5f56b6a8a6")

TWEAKS = validate_module("precision", [
    T("pre-001", "Trajectory Timing",
      "Tweaks frame timing & send intervals.",
      actions=[
          ("reg", "HKLM", _MMCSS, "SystemResponsiveness", 10, "DWORD"),
          ("reg", "HKLM", _TCPIP, "InitialRTO", 1000, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _MMCSS, "SystemResponsiveness"),
          ("regdel", "HKLM", _TCPIP, "InitialRTO"),
      ],
      why="Reserves a small CPU margin for background input handling and shortens "
          "the packet send window so long-range inputs register cleanly.",
      changes="Sets MMCSS responsiveness to 10 and cuts the TCP retransmit timer to 1s.",
      risk="low", impact="high", recommended="recommended", admin=True,
      tags=["mmcss", "tcp", "frame", "precision"]),

    T("pre-002", "Fire Timing",
      "Normalizes animation state and shot calculation timing.",
      actions=[
          ("reg", "HKLM", _MMCSS, "SystemResponsiveness", 10, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _MMCSS, "SystemResponsiveness"),
      ],
      why="Consistent CPU scheduling with a small background margin keeps "
          "animation state and shot-calculation timing uniform each spray.",
      changes="Sets MMCSS responsiveness to 10 for steadier scheduling.",
      risk="low", impact="moderate", recommended="optional", admin=True,
      tags=["mmcss", "cpu", "precision"]),

    T("pre-003", "Packet Flow",
      "Packet flow optimization for stable network timing.",
      actions=[
          ("reg", "HKLM", _MMCSS, "NetworkThrottlingIndex", 0xFFFFFFFF, "DWORD"),
          ("reg", "HKLM", _PSCHED, "NonBestEffortLimit", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _MMCSS, "NetworkThrottlingIndex"),
          ("regdel", "HKLM", _PSCHED, "NonBestEffortLimit"),
      ],
      why="Removes deliberate packet throttling and bandwidth reservation so "
          "shot packets leave immediately, reducing delayed hits.",
      changes="Disables network throttling and the QoS bandwidth reservation.",
      risk="low", impact="high", recommended="recommended", admin=True,
      tags=["mmcss", "qos", "packet", "precision"]),

    T("pre-004", "Tick Sync",
      "Server timing tick alignment.",
      actions=[
          ("reg", "HKLM", _TCPIP, "InitialRTO", 1000, "DWORD"),
          ("reg", "HKLM", _TCPIP, "Tcp1323Opts", 3, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _TCPIP, "InitialRTO"),
          ("regdel", "HKLM", _TCPIP, "Tcp1323Opts"),
      ],
      why="Faster retransmit and packet timestamps keep shot data arriving on "
          "the server's tick boundary instead of one tick late.",
      changes="Shortens the retransmit timer and enables RFC 1323 timestamps.",
      risk="safe", impact="moderate", recommended="optional", admin=True,
      tags=["tcp", "timestamps", "tick", "precision"]),

    T("pre-005", "Latency Consistency",
      "Latency spike reduction & response consistency.",
      actions=[
          ("reg", "HKLM", _MMCSS, "NetworkThrottlingIndex", 0xFFFFFFFF, "DWORD"),
          ("power", "usb_selective", 0),
      ],
      revert=[
          ("regdel", "HKLM", _MMCSS, "NetworkThrottlingIndex"),
          ("power", "usb_selective", 1),
      ],
      why="Stops latency spikes from network throttling and USB hub power-downs "
          "so shots register in the same frame.",
      changes="Disables network throttling and USB selective suspend.",
      risk="safe", impact="moderate", recommended="optional", admin=True,
      tags=["mmcss", "usb", "polling", "precision"]),

    T("pre-006", "Click Timing",
      "Click-to-shot timing tightness.",
      actions=[
          ("reg", "HKLM", _MMCSS, "SystemResponsiveness", 10, "DWORD"),
          ("reg", "HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _MMCSS, "SystemResponsiveness"),
          ("reg", "HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", 0, "DWORD"),
      ],
      why="Keeps a small CPU margin for input handling and removes the "
          "fullscreen-optimization compositor hop so the click reaches the game in the same frame.",
      changes="Sets MMCSS responsiveness to 10 and disables fullscreen optimizations.",
      risk="low", impact="high", recommended="recommended", admin=True,
      win="10,11",
      tags=["mmcss", "fso", "click", "precision"]),

    T("pre-007", "Packet Timing",
      "Network jitter & micro-loss mitigation.",
      actions=[
          ("reg", "HKLM", _PSCHED, "NonBestEffortLimit", 0, "DWORD"),
          ("reg", "HKLM", _TCPIP, "Tcp1323Opts", 3, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _PSCHED, "NonBestEffortLimit"),
          ("regdel", "HKLM", _TCPIP, "Tcp1323Opts"),
      ],
      why="Uncapped bandwidth plus timestamps smooth out micro-jitter and hide "
          "tiny packet loss so tracking stays consistent.",
      changes="Removes the QoS reservation and enables RFC 1323 timestamps.",
      risk="safe", impact="moderate", recommended="optional", admin=True,
      tags=["qos", "tcp", "jitter", "precision"]),

    T("pre-008", "Stick Sync",
      "Controller polling rate & analog deadzone sync.",
      actions=[
          ("guidance", "Set your controller to its highest polling rate in the "
                       "controller/elite app, lower the analog stick deadzone to "
                       "~0-5%, and use Steam Input for consistent input mapping."),
      ],
      revert=[
          ("guidance", "Restore your controller's previous polling rate and deadzone settings."),
      ],
      why="A high polling rate with a minimal deadzone keeps stick input and "
          "correction samples aligned with the game's input read.",
      changes="Guide: controller polling rate and analog deadzone setup.",
      risk="safe", impact="low", recommended="optional",
      tags=["controller", "polling", "deadzone", "precision"]),

    T("pre-009", "Taste Tester",
      "Preset mix of lighter tweaks across all categories.",
      actions=[
          ("reg", "HKLM", _MMCSS, "SystemResponsiveness", 10, "DWORD"),
          ("reg", "HKLM", _TCPIP, "Tcp1323Opts", 3, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", _MMCSS, "SystemResponsiveness"),
          ("regdel", "HKLM", _TCPIP, "Tcp1323Opts"),
      ],
      why="A gentle baseline mix of frame-path and network-timing tweaks that "
          "most systems handle with zero side effects.",
      changes="Applies light MMCSS + TCP timestamp tuning.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["mmcss", "tcp", "baseline", "precision"]),
])
