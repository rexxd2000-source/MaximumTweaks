"""Category: NVIDIA — GeForce driver and NVIDIA Control Panel guidance."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("NVIDIA", win_default="7,8,10,11")
CATEGORY = "NVIDIA"

TWEAKS = validate_module("nvidia", [
    T("nv-001", "Enable Persistence Mode",
      "Keeps the NVIDIA driver resident to lower launch stalls.",
      actions=[("cmd", "nvidia-smi -pm 1")],
      revert=[("cmd", "nvidia-smi -pm 0")],
      why="Persistence mode avoids reloading driver state between applications.",
      changes="Sets GPU persistence mode on.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      when={"gpu": ["nvidia"]},
      tags=["persistence", "driver", "nvidia"]),
    T("nv-002", "Reset Auto Boost Defaults",
      "Returns GPU boost clocks to driver defaults.",
      actions=[("cmd", "nvidia-smi --auto-boost-default=0")],
      revert=[("cmd", "nvidia-smi --auto-boost-default=1")],
      why="Clears custom boost state so the GPU boost algorithm runs normally.",
      changes="Resets auto-boost settings.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      when={"gpu": ["nvidia"]},
      tags=["boost", "clock", "nvidia"]),



    T("nv-018", "Disable NVIDIA Logging Services",
      "Stops and disables the NVIDIA logging and monitoring services.",
      actions=[("svc", "NvTmMon", "disabled"), ("svc", "NvTmRep", "disabled"), ("svc", "NvVapI", "disabled"), ("svc", "NVDisplay.Container", "disabled")],
      revert=[("svc", "NvTmMon", "manual"), ("svc", "NvTmRep", "manual"), ("svc", "NvVapI", "manual"), ("svc", "NVDisplay.Container", "manual")],
      why="NVIDIA background services poll GPU state and write logs; disabling them removes periodic wake-ups and disk writes.",
      changes="Disables NVIDIA logging and display container services.",
      risk="safe", impact="low", recommended="optional", admin=True,
      when={"gpu": ["nvidia"]},
      tags=["services", "logging", "background"]),


])
