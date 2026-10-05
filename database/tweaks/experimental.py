"""Category: Experimental — experimental and niche tweaks."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Experimental", win_default="10,11")
CATEGORY = "Experimental"

TWEAKS = validate_module("experimental", [
    T("exp-001", "Enable Dev Mode",
      "Enables Developer Mode features.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock", "AllowDevelopmentWithoutDevLicense", 1, "DWORD")],
      revert=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock", "AllowDevelopmentWithoutDevLicense", 0, "DWORD")],
      why="Lets sideloaded tools and apps run without store restrictions.",
      changes="Enables Developer Mode.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["devmode", "sideload", "developer"]),
    T("exp-002", "Enable Windows Subsystem for Linux",
      "Enables WSL support.",
      actions=[("cmd", "powershell -NoProfile -Command \"Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart\"")],
      revert=[("cmd", "powershell -NoProfile -Command \"Disable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart\"")],
      why="WSL is useful for scripting tools, not for games — enable only if you use Linux tools.",
      changes="Enables WSL.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["wsl", "linux", "subsystem"]),
    T("exp-003", "Disable Hypervisor via BCDEdit",
      "Disables the hypervisor at boot.",
      actions=[("cmd", "bcdedit /set hypervisorlaunchtype off")],
      revert=[("cmd", "bcdedit /set hypervisorlaunchtype auto")],
      why="Removes hypervisor overhead from the boot stack on some machines.",
      changes="Disables the hypervisor.",
      risk="safe", impact="moderate", recommended="optional", admin=True,
      tags=["hypervisor", "bcdedit", "boot"]),
    T("exp-004", "Enable Test Mode",
      "Enables test signing mode.",
      actions=[("cmd", "bcdedit /set testsigning on")],
      revert=[("cmd", "bcdedit /set testsigning off")],
      why="Allows unsigned driver testing — for developers only.",
      changes="Enables test signing.",
      risk="safe", impact="very low", recommended="optional", admin=True,
      tags=["testsigning", "drivers", "dev"]),
    T("exp-005", "Disable Core Isolation",
      "Disables memory integrity.",
      actions=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity", "Enabled", 0, "DWORD")],
      revert=[("reg", "HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity", "Enabled", 1, "DWORD")],
      why="Removes the virtualization overhead of Hypervisor-enforced code integrity.",
      changes="Disables Core Isolation.",
      risk="safe", impact="moderate", recommended="optional", admin=True,
      tags=["coreisolation", "memoryintegrity", "security"]),
])
