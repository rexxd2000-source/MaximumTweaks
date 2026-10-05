"""Category: Monitor — display hardware behaviour optimizations."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Monitor", win_default="7,8,10,11")
CATEGORY = "Monitor"

TWEAKS = validate_module("monitor", [
    T("mon-001", "Disable Monitor Auto-Detect Sleep",
      "Prevents the display from entering power save during long play sessions.",
      actions=[("power", "display_timeout", 0)],
      revert=[("power", "display_timeout", 600)],
      why="A monitor that sleeps mid-session causes a disruptive black screen and reconnect delay.",
      changes="Sets the display turn-off timeout to 'never' on AC.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["monitor", "sleep", "display"]),
    T("mon-003", "Native Refresh Rate Check",
      "Reports the detected display resolution and refresh rate.",
      actions=[("cmd", "powershell -NoProfile -Command \"Get-CimInstance Win32_VideoController | Format-Table Name,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate -AutoSize\"")],
      revert=[("guidance", "Read-only report.")],
      why="Confirms the monitor is running at its rated refresh rate.",
      changes="Shows the display mode report.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["refresh", "resolution", "report"]),
    T("mon-006", "Disable Adaptive Brightness",
      "Turns off display adaptive brightness in the power plan.",
      actions=[("power", "adaptive_brightness", 0, "AC"), ("power", "adaptive_brightness", 0, "DC")],
      revert=[("power", "adaptive_brightness", 1, "AC"), ("power", "adaptive_brightness", 1, "DC")],
      why="Ambient-light brightness adjustments cause visible brightness dips during dark scenes.",
      changes="Disables adaptive brightness on AC.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["brightness", "ambient", "display"]),
    T("mon-014", "Display Topology Report",
      "Lists connected display adapters and monitors.",
      actions=[("cmd", "powershell -NoProfile -Command \"Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorBasicDisplayParams | Format-Table InstanceName -AutoSize; Get-CimInstance Win32_DesktopMonitor | Format-Table Name,ScreenWidth,ScreenHeight -AutoSize\"")],
      revert=[("guidance", "Read-only report.")],
      why="Confirms which monitors Windows sees and their current modes.",
      changes="Shows the display topology report.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["monitors", "topology", "report"]),
])
