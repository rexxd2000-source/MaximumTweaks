"""Category: Advanced — advanced and low-level tweaks."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Advanced", win_default="7,8,10,11")
CATEGORY = "Advanced"

TWEAKS = validate_module("advanced", [

    T("adv-003", "Disable Insecure Guest Fallback",
      "Disables SMB guest fallback.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters", "AllowInsecureGuestAuth", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters", "AllowInsecureGuestAuth", 1, "DWORD")],
      why="Blocks insecure guest SMB fallback and its negotiation overhead.",
      changes="Disables SMB guest fallback.",
      risk="safe", impact="very low", recommended="recommended", admin=True,
      tags=["smb", "guest", "security"]),

    T("adv-006", "Set Processor Scheduling to Programs",
      "Prioritizes programs over background services.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", 26, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", 2, "DWORD")],
      why="Keeps foreground programs above background services in the scheduler.",
      changes="Sets Win32PrioritySeparation to 26.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["priority", "scheduler", "programs"]),
    T("adv-007", "Disable Credential Manager",
      "Disables the credential manager service.",
      actions=[("sc", "disable", "VaultSvc")],
      revert=[("sc", "enable", "VaultSvc")],
      why="Stops credential vault polling for users who rely on apps storing secrets elsewhere.",
      changes="Disables the Credential Manager service.",
      risk="safe", impact="very low", recommended="optional", admin=True,
      tags=["credentials", "vault", "service"]),
    T("adv-008", "Disable Print Job History",
      "Disables print job history tracking via registry.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\Print", "PrintJobLogging", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SYSTEM\CurrentControlSet\Control\Print", "PrintJobLogging")],
      why="Reduces printer subsystem auditing overhead.",
      changes="Disables print job logging.",
      risk="safe", impact="very low", recommended="optional", admin=True,
      tags=["print", "history", "audit"]),
    T("adv-009", "Disable Font Cache Service",
      "Disables the font cache service.",
      actions=[("sc", "disable", "FontCache")],
      revert=[("sc", "enable", "FontCache")],
      why="Saves a small resident service, but font rendering will re-cache.",
      changes="Disables FontCache.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["font", "cache", "service"]),

    T("adv-015", "Optimize BCD Boot Settings",
      "Sets the boot menu policy to standard for faster boots.",
      actions=[("cmd", "bcdedit /set bootmenupolicy standard")],
      revert=[("cmd", "bcdedit /set bootmenupolicy recovery")],
      why="Standard boot policy skips the advanced boot options menu unless a failure occurs, shortening boot time.",
      changes="Sets boot menu policy to standard.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["boot", "bcd", "startup"]),

])
