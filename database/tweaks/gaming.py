"""Category: Gaming — general gaming quality-of-life and performance."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Gaming", win_default="7,8,10,11")
CATEGORY = "Gaming"

TWEAKS = validate_module("gaming", [
    T("game-001", "Enable Game Mode",
      "Turns on Windows Game Mode.",
      actions=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameBar", "AutoGameModeEnabled", 1, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameBar", "AllowAutoGameMode", 1, "DWORD"),
      ],
      revert=[
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameBar", "AutoGameModeEnabled", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameBar", "AllowAutoGameMode", 0, "DWORD"),
      ],
      why="Game Mode allocates scheduling priority and GPU budget to the game.",
      changes="Enables Game Mode.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["gamemode", "priority", "gaming"]),
    T("game-003", "Disable Game DVR / Game Bar / Background Capture",
      "Single owner for the Game DVR and Game Bar capture pipeline: disables background recording, the Game Bar widget/overlay hook, and the policy-level capture switches.",
      actions=[
          ("reg", "HKCU", r"System\GameConfigStore",
           "GameDVR_Enabled", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
           "AppCaptureEnabled", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
           "BackgroundRecordingEnabled", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameBar",
           "UseNexusForGameBarEnabled", 0, "DWORD"),
          ("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
           "VKMToggleGameBar", 0, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
           "AllowGameDVR", 0, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameBar",
           "AllowGameBar", 0, "DWORD"),
      ],
      revert=[
          ("regdel", "HKCU", r"System\GameConfigStore", "GameDVR_Enabled"),
          ("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
           "AppCaptureEnabled"),
          ("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
           "BackgroundRecordingEnabled"),
          ("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameBar",
           "UseNexusForGameBarEnabled"),
          ("regdel", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR",
           "VKMToggleGameBar"),
          ("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameDVR",
           "AllowGameDVR"),
          ("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\GameBar",
           "AllowGameBar"),
      ],
      why="Game DVR silently records gameplay in the background and the Game Bar "
          "overlay hooks every game frame. One owner disables the whole "
          "capture/overlay stack to free GPU encode and hook overhead.",
      changes="Disables Game DVR background recording and the Game Bar overlay hook.",
      risk="safe", impact="moderate", recommended="recommended",
      admin=True, confirm=True,
      updated="2026-09-27",
      tags=["dvr", "gamebar", "capture", "recording", "overlay"]),
])
