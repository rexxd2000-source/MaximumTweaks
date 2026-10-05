"""Category: Background — background apps and idle processing."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Background", win_default="10,11")
CATEGORY = "Background"

TWEAKS = validate_module("background", [
    T("bg-005", "Exclude Game Folders from Defender",
      "Adds common game folders to the Defender exclusion list.",
      actions=[("cmd", r'powershell -NoProfile -Command "Add-MpPreference -ExclusionPath @(\'C:\Games\',\'D:\Games\',\'E:\Games\') -ErrorAction SilentlyContinue"')],
      revert=[("cmd", r'powershell -NoProfile -Command "Remove-MpPreference -ExclusionPath @(\'C:\Games\',\'D:\Games\',\'E:\Games\') -ErrorAction SilentlyContinue"')],
      why="Real-time antivirus scanning of large game folders hits disk and CPU.",
      changes="Adds C:\\Games, D:\\Games, E:\\Games to Defender exclusion paths.",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["defender", "exclusion", "disk"]),
    T("bg-008", "Disable Settings Sync",
      "Disables settings sync via Group Policy.",
      actions=[("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\SettingSync", "DisableSettingSync", 1, "DWORD")],
      revert=[("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\SettingSync", "DisableSettingSync")],
      why="Settings sync polls the cloud at sign-in and periodically.",
      changes="Disables settings sync via registry policy.",
      risk="safe", impact="very low", recommended="optional", admin=True,
      tags=["sync", "backup", "settings"]),
    T("bg-009", "Disable Tips and Suggestions",
      "Disables Windows tips background suggestions.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SoftLandingEnabled", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SoftLandingEnabled", 1, "DWORD")],
      why="Removes the background tip/suggestion polling.",
      changes="Disables tips and suggestions.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["tips", "suggestions", "background"]),
    T("bg-010", "Set Active Hours",
      "Sets Windows Update active hours to cover a typical gaming session.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursStart", 8, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursEnd", 22, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursStart"),
          ("regdel", "HKLM", r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings", "ActiveHoursEnd"),
      ],
      why="An auto-reboot mid-match loses progress and settings.",
      changes="Sets active hours to 08:00 - 22:00.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["reboot", "update", "activehours"]),
])
