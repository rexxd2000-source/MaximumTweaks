"""Category: BIOS — firmware diagnostic tools."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("BIOS", win_default="7,8,10,11")
CATEGORY = "BIOS"

TWEAKS = validate_module("bios", [
    T("bios-001", "Check BIOS Version",
      "Shows the current BIOS version.",
      actions=[("cmd", 'powershell -NoProfile -Command "Get-CimInstance Win32_BIOS | Select-Object SMBIOSBIOSVersion,ReleaseDate,Manufacturer"')],
      revert=[],
      why="Confirms the firmware level before updating.",
      changes="Reports the BIOS version.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["bios", "version", "firmware"]),
])
