"""Category: Repair — system repair and recovery tools."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Repair", win_default="7,8,10,11")
CATEGORY = "Repair"

TWEAKS = validate_module("repair", [
    T("rep-001", "Restore System Health (DISM)",
      "Runs DISM to restore the system image.",
      actions=[("cmd", "DISM /Online /Cleanup-Image /RestoreHealth")],
      revert=[("guidance", "No change to revert.")],
      why="Repairs corrupted component store files that break updates and drivers.",
      changes="Runs DISM RestoreHealth (may take 10+ minutes).",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["dism", "system", "repair"]),
    T("rep-002", "Run System File Checker",
      "Runs SFC to verify system files.",
      actions=[("cmd", "sfc /scannow")],
      revert=[("guidance", "No change to revert.")],
      why="Replaces corrupted protected system files.",
      changes="Runs sfc /scannow (may take several minutes).",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["sfc", "scannow", "repair"]),
    T("rep-003", "Scan Disk for Errors",
      "Scans the system drive for disk errors.",
      actions=[("cmd", "chkdsk /scan")],
      revert=[("guidance", "No change to revert.")],
      why="Finds file-system and bad-sector issues that cause freezes.",
      changes="Runs chkdsk in scan mode.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["chkdsk", "disk", "scan"]),
    T("rep-004", "Clean Up Component Store",
      "Trims the WinSxS component store.",
      actions=[("cmd", "DISM /Online /Cleanup-Image /StartComponentCleanup")],
      revert=[("guidance", "No change to revert.")],
      why="Frees disk space from superseded update components.",
      changes="Runs component cleanup.",
      risk="safe", impact="very low", recommended="recommended", admin=True,
      tags=["dism", "winsxs", "cleanup"]),
    T("rep-005", "Reset Windows Update Components",
      "Stops the update service, renames the SoftwareDistribution cache, and restarts it.",
      actions=[("cmd", r'powershell -NoProfile -Command "Stop-Service wuauserv -Force; Rename-Item C:\Windows\SoftwareDistribution SoftwareDistribution.bak -ErrorAction SilentlyContinue; Start-Service wuauserv"')],
      revert=[("cmd", r'powershell -NoProfile -Command "Stop-Service wuauserv -Force; if (Test-Path C:\Windows\SoftwareDistribution.bak) { Remove-Item C:\Windows\SoftwareDistribution -Recurse -Force -ErrorAction SilentlyContinue; Rename-Item C:\Windows\SoftwareDistribution.bak SoftwareDistribution }; Start-Service wuauserv"')],
      why="A corrupted update cache blocks new updates and fixes.",
      changes="Resets the Windows Update SoftwareDistribution cache.",
      risk="safe", impact="low", recommended="recommended", admin=True,
      tags=["update", "reset", "softwaredistribution"]),
    T("rep-007", "Reset Microsoft Store",
      "Resets the Microsoft Store cache.",
      actions=[("cmd", "wsreset.exe")],
      revert=[("guidance", "No change to revert.")],
      why="Clears the store cache that blocks app updates.",
      changes="Runs wsreset.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["store", "reset", "cache"]),
    T("rep-008", "Create Restore Point",
      "Creates a system restore point.",
      actions=[("cmd", "powershell -NoProfile -Command Checkpoint-Computer -Description MaximumTweaks -RestorePointType MODIFY_SETTINGS")],
      revert=[("guidance", "No change to revert.")],
      why="A restore point lets you undo batch tweaks safely.",
      changes="Creates a restore point.",
      risk="safe", impact="very low", recommended="recommended", admin=True,
      tags=["restore", "point", "backup"]),
    T("rep-009", "Verify Driver Signatures",
      "Runs the file signature verification tool.",
      actions=[("cmd", "sigverif")],
      revert=[("guidance", "Close the window.")],
      why="Finds unsigned drivers that can crash the kernel.",
      changes="Opens sigverif.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["sigverif", "drivers", "signature"]),
    T("rep-013", "Memory Diagnostic",
      "Launches the Windows Memory Diagnostic.",
      actions=[("cmd", "start mdsched")],
      revert=[("guidance", "Cancel the diagnostic.")],
      why="Detects faulty RAM that manifests as random crashes and stutter.",
      changes="Opens the Memory Diagnostic.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["memory", "ram", "diagnostic"]),
    T("rep-014", "Disk Check on Next Boot",
      "Schedules a full chkdsk on reboot.",
      actions=[("cmd", "chkdsk C: /f")],
      revert=[("guidance", "Cancel the scheduled check with chkdsk /f at a clean state.")],
      why="Fixes file-system errors that a scan-only pass cannot.",
      changes="Schedules a disk check for the next boot.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["chkdsk", "disk", "fix"]),
    T("rep-015", "CPU Optimization Repair",
      "Detect-first cleaner for bad scheduling values left behind by old "
      "MaximumTweaks builds, REG packs, BAT packs or other optimizers.",
      actions=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "Win32PrioritySeparation", 26, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "SystemResponsiveness", 10, "DWORD"),
          ("cmd", r"""powershell -NoProfile -Command "$e = & bcdedit /enum {current} 2>$null | Out-String; foreach ($n in @('useplatformclock','disabledynamictick','tscsyncpolicy')) { if ($e -match [regex]::Escape($n)) { & bcdedit /deletevalue $n *> $null } }" """),
          ("guidance", "Process-level repairs (explicit CPU Set restrictions and "
                        "low game memory priority) run from the Game Process "
                        "category while the game is running."),
      ],
      revert=[
          ("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl",
           "Win32PrioritySeparation", 2, "DWORD"),
          ("reg", "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
           "SystemResponsiveness", 20, "DWORD"),
          ("guidance", "The registry reverts use Windows' documented defaults "
                       "when no snapshot exists; with a snapshot the app "
                       "restores the exact previous values. Forced BCD timer "
                       "values are NOT re-created: the cleaner deletes them on "
                       "purpose and Windows restores its own defaults."),
      ],
      why="Scheduling values and BCD timer overrides stuck around by old "
          "optimizers can force CPU/MMCSS behavior that hurts responsiveness. "
          "This repairs only what is actually set: Win32PrioritySeparation is "
          "reset to 26 decimal, MMCSS SystemResponsiveness to 10, and any "
          "explicit HPET/dynamic-tick/tsc overrides are deleted (never "
          "replaced with the opposite forced value).",
      changes="Resets Win32PrioritySeparation to 26, SystemResponsiveness to "
              "10, and deletes detected BCD timer overrides.",
      risk="low", impact="moderate", recommended="recommended", admin=True,
      added="2026-09-07",
      tags=["cpu", "priorities", "repair", "bcd", "mmcss", "cleanup"]),
])
