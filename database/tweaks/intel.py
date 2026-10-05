"""Category: Intel — Intel Graphics driver and control panel guidance."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Intel", win_default="7,8,10,11")
CATEGORY = "Intel"

TWEAKS = validate_module("intel", [
    T("int-003", "Disable Intel VSync",
      "Disables driver-enforced VSync via the Intel graphics registry.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver", "KMD_EnableVSync", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*\Curver", "KMD_EnableVSync", 1, "DWORD")],
      why="Driver-enforced VSync caps effective rate and adds input lag. Disabling it lets the game or VRR handle sync.",
      changes="Disables Intel driver-level VSync.",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      when={"gpu": ["intel"]},
      tags=["vsync", "latency", "sync"]),
    T("int-009", "Opt Out of Intel Telemetry",
      "Disables Intel driver telemetry via registry keys.",
      actions=[
          ("reg", "HKLM", r"SOFTWARE\Intel\DTEm", "TelemetryEnabled", 0, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Policies\Intel\TeleClient", "DisableTelemetry", 1, "DWORD"),
      ],
      revert=[
          ("regdel", "HKLM", r"SOFTWARE\Intel\DTEm", "TelemetryEnabled"),
          ("regdel", "HKLM", r"SOFTWARE\Policies\Intel\TeleClient", "DisableTelemetry"),
      ],
      why="Telemetry services add occasional background wake-ups. Disabling them removes a background data collector.",
      changes="Disables Intel driver telemetry.",
      risk="safe", impact="very low", recommended="optional", admin=True,
      when={"gpu": ["intel"]},
      tags=["telemetry", "privacy", "background"]),
    T("int-013", "Enable Intel Speed Shift",
      "Enables Intel Speed Shift Technology for faster CPU frequency transitions.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power", "IntelSpeedShiftEnabled", 1, "DWORD")],
      revert=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\Power", "IntelSpeedShiftEnabled")],
      why="Speed Shift lets the hardware choose CPU frequency in microseconds instead of milliseconds, reducing latency spikes.",
      changes="Enables Intel Speed Shift Technology.",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["speedshift", "cpu", "power"]),
    T("int-014", "Enable Intel Turbo Boost Max 3.0",
      "Ensures Intel Turbo Boost Max 3.0 is active for best single-core performance.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Processor", "IntelTurboBoostMax30Disable", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\Processor", "IntelTurboBoostMax30Disable")],
      why="Turbo Boost Max 3.0 boosts the fastest core further; disabling it (or leaving it enabled) keeps single-threaded game performance up.",
      changes="Sets IntelTurboBoostMax30Disable to 0 (enabled).",
      risk="safe", impact="moderate", recommended="recommended", admin=True,
      tags=["turbo", "boost", "clock"]),

])
