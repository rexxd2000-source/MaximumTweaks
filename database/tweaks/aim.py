"""Category: Aim — input-path registry/network tweaks.

These are real registry/powercfg tweaks behind the Pointer & Input section's four mechanisms:

  * Server-Side Rewind        -> Nagle removal, TCP delayed-ACK (aim-001)
  * Input & Output Path       -> USB selective suspend (aim-004)
  * Latency Concealment       -> QoS reservation removal (aim-002)
  * Scheduler Consistency     -> core-parking policy (aim-003)

Fullscreen-optimizations and Game Mode settings were duplicates of the
canonical tweaks in Windows / Gaming (win-004, game-001) and were removed.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Aim", win_default="7,8,10,11")
CATEGORY = "Aim"

_INTERFACES = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

TWEAKS = validate_module("aim", [
    T("aim-001", "Disable Nagle's Algorithm",
      "Sends TCP packets immediately instead of batching small ones (TCPNoDelay=1, TcpAckFrequency=1 on every network interface).",
      actions=[
          ("regall", "HKLM", _INTERFACES, "TCPNoDelay", 1, "DWORD"),
          ("regall", "HKLM", _INTERFACES, "TcpAckFrequency", 1, "DWORD"),
      ],
      revert=[
          ("regdelall", "HKLM", _INTERFACES, "TCPNoDelay"),
          ("regdelall", "HKLM", _INTERFACES, "TcpAckFrequency"),
      ],
      why="Nagle's algorithm buffers tiny packets up to ~200ms to batch them, and delayed ACK holds acknowledgements back. "
          "Competitive input/state packets are small, so this delay eats directly into effective input responsiveness.",
      changes="Disables Nagle batching and delayed ACK on all network interfaces.",
      risk="low", impact="high", recommended="recommended", admin=True,
      tags=["nagle", "tcp", "ack", "packet", "input"]),
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
    T("aim-003", "Disable Core Parking (Group Policy)",
      "Prevents Windows from parking CPU cores so every core stays ready for the scheduler.",
      actions=[
          ("reg", "HKLM",
           r"SOFTWARE\Policies\Microsoft\Windows\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\0cc5b4c1-d36e-4dc5-9e1c-4d5f56b6a8a6",
           "ACSettingIndex", 0, "DWORD"),
          ("reg", "HKLM",
           r"SOFTWARE\Policies\Microsoft\Windows\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\0cc5b4c1-d36e-4dc5-9e1c-4d5f56b6a8a6",
           "DCSettingIndex", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM",
           r"SOFTWARE\Policies\Microsoft\Windows\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\0cc5b4c1-d36e-4dc5-9e1c-4d5f56b6a8a6",
           "ACSettingIndex"),
          ("regdel", "HKLM",
           r"SOFTWARE\Policies\Microsoft\Windows\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\0cc5b4c1-d36e-4dc5-9e1c-4d5f56b6a8a6",
           "DCSettingIndex"),
      ],
      why="Parked cores wake with a multi-millisecond delay. Unparked cores keep shot, peek and "
          "trace timing consistent by removing scheduler wake-up delay.",
      changes="Disables core parking via group policy.",
      risk="low", impact="moderate", recommended="recommended", admin=True,
      tags=["parking", "core", "scheduler", "cpu"]),
    T("aim-004", "Disable USB Selective Suspend",
      "Stops Windows from suspending USB ports, keeping mouse and keyboard input always live.",
      actions=[("power", "usb_selective", 0)],
      revert=[("power", "usb_selective", 1)],
      why="USB selective suspend can briefly power down a hub; during that window input polls can drop, "
          "adding small jitter to the input path.",
      changes="Disables USB selective suspend on AC power.",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["usb", "suspend", "polling", "input"]),
])
