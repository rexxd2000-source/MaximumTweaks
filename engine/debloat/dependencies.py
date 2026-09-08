"""Dependency detection — maps installed software to system requirements.

Scans the user's actual PC to determine:
- What software is installed
- What services/features each application requires
- Whether gaming software depends on specific components
- What hardware is present (Xbox controller, NFC, etc.)

Powers the "Protected — Required by X" logic.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from engine.debloat.protected import (
    KNOWN_DEPENDENCIES, GAMING_SOFTWARE_PATTERNS,
)


@dataclass
class InstalledSoftware:
    name: str
    publisher: str = ""
    version: str = ""
    install_date: str = ""
    is_gaming: bool = False
    gaming_label: str = ""


@dataclass
class HardwareInfo:
    has_xbox_controller: bool = False
    has_nfc: bool = False
    has_bluetooth: bool = False
    has_touchscreen: bool = False
    has_printer: bool = False


@dataclass
class DependencyMap:
    """Maps system components to the software that depends on them."""
    installed_software: list[InstalledSoftware] = field(default_factory=list)
    gaming_software: list[InstalledSoftware] = field(default_factory=list)
    services_needed: dict[str, set[str]] = field(default_factory=dict)
    hardware: HardwareInfo = field(default_factory=HardwareInfo)
    is_gaming_pc: bool = False


def _run_ps(command: str, timeout: int = 30) -> str:
    """Run a PowerShell command and return stdout."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _run_ps_json(command: str, timeout: int = 30) -> list[dict]:
    """Run PowerShell, parse JSON output."""
    raw = _run_ps(f"({command}) | ConvertTo-Json -Depth 3 -Compress", timeout)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def _scan_installed_software() -> list[InstalledSoftware]:
    """Scan all installed software from registry."""
    software: list[InstalledSoftware] = []
    seen: set[str] = set()

    paths = [
        r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    ]

    for reg_path in paths:
        progs = _run_ps_json(
            f"Get-ItemProperty '{reg_path}' -ErrorAction SilentlyContinue | "
            f"Where-Object {{$_.DisplayName -and $_.Publisher}} | "
            f"Select-Object DisplayName,Publisher,DisplayVersion,InstallDate | "
            f"ConvertTo-Json -Depth 3 -Compress"
        )

        for prog in progs:
            name = prog.get("DisplayName", "")
            if not name or name in seen:
                continue
            seen.add(name)

            publisher = prog.get("Publisher", "")
            version = prog.get("DisplayVersion", "")
            install_date = prog.get("InstallDate", "")

            sw = InstalledSoftware(
                name=name,
                publisher=publisher,
                version=version,
                install_date=install_date,
            )

            for pattern, label in GAMING_SOFTWARE_PATTERNS:
                if pattern.lower() in name.lower():
                    sw.is_gaming = True
                    sw.gaming_label = label
                    break

            software.append(sw)

    return software


def _match_software_to_dependencies(software: list[InstalledSoftware]) -> DependencyMap:
    """Match installed software to known dependencies."""
    dep_map = DependencyMap(installed_software=software)

    for sw in software:
        if sw.is_gaming:
            dep_map.gaming_software.append(sw)

        for pattern, deps in KNOWN_DEPENDENCIES.items():
            if pattern.lower() in sw.name.lower():
                for svc in deps.get("required_services", set()):
                    if svc not in dep_map.services_needed:
                        dep_map.services_needed[svc] = set()
                    dep_map.services_needed[svc].add(sw.name)

    gaming_count = len(dep_map.gaming_software)
    dep_map.is_gaming_pc = gaming_count >= 2

    return dep_map


def _detect_hardware() -> HardwareInfo:
    """Detect present hardware that affects service recommendations."""
    hw = HardwareInfo()

    # Xbox controllers
    raw = _run_ps(
        "Get-PnpDevice -Class 'XboxPeripherals' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 Status"
    )
    if raw and "OK" in raw:
        hw.has_xbox_controller = True

    # Fallback: check for Xbox controller via HID
    if not hw.has_xbox_controller:
        raw = _run_ps(
            "Get-PnpDevice -Class 'HIDClass' -ErrorAction SilentlyContinue | "
            "Where-Object {$_.FriendlyName -like '*Xbox*' -or $_.FriendlyName -like '*Controller*'} | "
            "Select-Object -First 1 Status"
        )
        if raw and "OK" in raw:
            hw.has_xbox_controller = True

    # NFC
    raw = _run_ps(
        "Get-PnpDevice -Class 'Nfc' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 Status"
    )
    if raw and "OK" in raw:
        hw.has_nfc = True

    # Bluetooth
    raw = _run_ps(
        "Get-PnpDevice -Class 'Bluetooth' -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 Status"
    )
    if raw and "OK" in raw:
        hw.has_bluetooth = True

    # Touchscreen
    raw = _run_ps(
        "Get-PnpDevice -Class 'HIDClass' -ErrorAction SilentlyContinue | "
        "Where-Object {$_.FriendlyName -like '*Touch*'} | "
        "Select-Object -First 1 Status"
    )
    if raw and "OK" in raw:
        hw.has_touchscreen = True

    # Printer
    raw = _run_ps(
        "Get-Printer -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 Name"
    )
    if raw:
        hw.has_printer = True

    return hw


def scan_dependencies() -> DependencyMap:
    """Run full dependency and hardware scan."""
    software = _scan_installed_software()
    dep_map = _match_software_to_dependencies(software)
    dep_map.hardware = _detect_hardware()
    return dep_map


def is_protected(service_name: str, dep_map: Optional[DependencyMap] = None) -> tuple[bool, str]:
    """Check if a service is protected and why."""
    if dep_map and service_name in dep_map.services_needed:
        users = dep_map.services_needed[service_name]
        user_list = ", ".join(sorted(users)[:3])
        if len(users) > 3:
            user_list += f" and {len(users) - 3} more"
        return True, f"Required by: {user_list}"
    return False, ""
