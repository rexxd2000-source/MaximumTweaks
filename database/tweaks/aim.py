"""Category: Aim — input-path registry/network tweaks.

These are real registry/powercfg tweaks behind the Pointer & Input section's mechanisms:

  * Server-Side Rewind        -> Nagle removal, TCP delayed-ACK (aim-001)
  * Latency Concealment       -> QoS reservation removal (aim-002)
  * Scheduler Consistency     -> core-parking policy (aim-003)

Fullscreen-optimizations and Game Mode settings were duplicates of the
canonical tweaks in Windows / Gaming (win-004, game-001) and were removed.
USB selective suspend (aim-004) was a duplicate of the canonical usb-001 in
the USB category and was removed; the mechanism is still reachable there.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Aim", win_default="7,8,10,11")
CATEGORY = "Aim"

TWEAKS = validate_module("aim", [

    T("aim-002", "Remove QoS Bandwidth Reservation",
      "Sets the QoS NonBestEffortLimit to 0 so Windows stops reserving ~20% of network bandwidth.",
      actions=[("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\Psched",
                "NonBestEffortLimit", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\Psched",
               "NonBestEffortLimit")],
      why="The default QoS policy reserves up to 20% of your link for best-effort traffic. "
          "Removing the cap keeps game traffic unthrottled so shots and state land on time.",
      changes="Disables the QoS bandwidth reservation.",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["qos", "bandwidth", "throttle", "input"]),
    ])
