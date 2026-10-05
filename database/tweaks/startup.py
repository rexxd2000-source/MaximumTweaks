"""Category: Startup — launch-time and boot behaviour."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Startup", win_default="7,8,10,11")
CATEGORY = "Startup"

TWEAKS = validate_module("startup", [
    T("start-001", "Check Startup Impact",
      "Lists startup apps with their launch impact.",
      actions=[("cmd", "start ms-settings:startupapps")],
      revert=[("guidance", "No change to revert.")],
      why="Startup apps stretch boot time and fight the game for resources.",
      changes="Opens the Startup Apps settings page.",
      risk="safe", impact="low", recommended="recommended",
      tags=["startup", "impact", "apps"]),
    T("start-005", "Enable Multi-Core Boot",
      "Uses all CPU cores while booting Windows.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters", "EnableBootAndPrefetch", 3, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters", "EnableBootAndPrefetch", 2, "DWORD")],
      why="Boot prefetch and superfetch modes speed cold-boot times on HDDs.",
      changes="Enables boot prefetching on all cores.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["boot", "cores", "prefetch"]),
    T("start-012", "Disable Automatic Sign-in Animations",
      "Disables the Windows logon background image and sign-in animation.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "DisableLogonBackgroundImage", 1, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon", "DisableLogonBackgroundImage", 0, "DWORD")],
      why="The sign-in animation delays usable desktop time.",
      changes="Disables the logon background image and sign-in animation.",
      risk="safe", impact="very low", recommended="optional", admin=True,
      tags=["signin", "animation", "boot"]),

    T("start-016", "Disable Maintenance Tasks",
      "Disables the automatic Windows Maintenance scheduler.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\Maintenance", "MaintenanceDisabled", 1, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\Maintenance", "MaintenanceDisabled", 0, "DWORD")],
      why="Automatic maintenance runs defrag, updates, and scans at idle, causing unexpected disk and CPU usage.",
      changes="Sets MaintenanceDisabled to 1 to stop scheduled maintenance.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["maintenance", "scheduler", "idle"]),
])
