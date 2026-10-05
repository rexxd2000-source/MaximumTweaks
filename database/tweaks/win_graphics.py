"""Category: Windows Graphics — graphics stack and presentation settings."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Windows Graphics", win_default="10,11")
CATEGORY = "Windows Graphics"
_ALL_GPU = {"gpu": ["nvidia", "amd", "intel"]}

TWEAKS = validate_module("win_graphics", [
    T("wgr-003", "Disable Auto HDR",
      "Disables Windows Auto HDR via policy registry key.",
      actions=[("reg", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\Display", "DisableAutoHDR", 1, "DWORD")],
      revert=[("regdel", "HKLM", r"SOFTWARE\Policies\Microsoft\Windows\Display", "DisableAutoHDR")],
      why="Auto HDR conversion adds a compute pass that can cost FPS on mid-range GPUs.",
      changes="Sets DisableAutoHDR to 1.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      when=_ALL_GPU,
      tags=["hdr", "auto", "overhead"]),
    T("wgr-006", "Restore MPO Composition",
      "Re-enables Multiplane Overlay (undo of the MPO disable tweak).",
      actions=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "OverlayTestMode")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "OverlayTestMode", 5, "DWORD")],
      why="If your display had no MPO issues, restoring it returns to the hardware composition path.",
      changes="Removes the MPO override.",
      risk="safe", impact="low", recommended="optional", admin=True,
      when=_ALL_GPU,
      tags=["mpo", "overlay", "restore"]),
    T("wgr-012", "Reset Graphics Settings",
      "Deletes Windows' per-app DirectX GPU preference blob (stale per-app "
      "assignments and performance flags are removed at once).",
      actions=[("regdel", "HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences",
                "DirectXUserGlobalSettings")],
      revert=[("reg", "HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences",
               "DirectXUserGlobalSettings",
               "SwapEffectUpgradeEnable=0;VRROptimizeEnable=0;"
               "DisableFeatureSetCreation=0;DisableFullscreenOptimizations=0;",
               "STRING")],
      why="Stale per-app graphics entries and leftover performance flags cause "
          "wrong-GPU launches; deleting the blob returns Windows to its default "
          "graphics-preference behaviour.",
      changes="Deletes the DirectXUserGlobalSettings graphics-preferences value.",
      risk="low", impact="low", recommended="recommended",
      when=_ALL_GPU,
      tags=["reset", "graphics", "settings"]),
    T("wgr-013", "DirectX Graphics Flags",
      "Sets all four DirectXUserGlobalSettings performance flags in one write "
      "(replaces the old four separate cards that fought over one value).",
      actions=[("reg", "HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences",
                "DirectXUserGlobalSettings",
                "SwapEffectUpgradeEnable=1;VRROptimizeEnable=1;"
                "DisableFeatureSetCreation=1;DisableFullscreenOptimizations=1;",
                "STRING")],
      revert=[("reg", "HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences",
               "DirectXUserGlobalSettings",
               "SwapEffectUpgradeEnable=0;VRROptimizeEnable=0;"
               "DisableFeatureSetCreation=0;DisableFullscreenOptimizations=0;",
               "STRING")],
      why="These flags live in a single string value, so each one previously "
          "overwrote the others. The merged card writes them together: swap "
          "effect upgrade, VRR optimize, no feature-set creation and no "
          "fullscreen optimizations.",
      changes="Writes all four DirectXUserGlobalSettings flags at once.",
      risk="low", impact="moderate", recommended="recommended",
      when=_ALL_GPU,
      tags=["swap", "vrr", "fse", "directx", "windowed"]),
])
