"""Smart Debloater engine — orchestrates scan, backup, apply, verify, rollback."""

from __future__ import annotations

import time
from typing import Callable, Optional

from engine.debloat.types import (
    DebloatCategory, DebloatItem, DebloatResult, OSInfo, RiskLevel,
)
from engine.debloat.scanner import (
    scan_os, scan_appx_packages, scan_third_party_apps,
    scan_oem_apps, scan_optional_services, scan_scheduled_tasks,
    scan_startup_entries,
)
from engine.debloat.dependencies import (
    DependencyMap, scan_dependencies, is_protected,
)
from engine.debloat.protected import (
    PROTECTED_OEM, PROTECTED_APPX,
    EXCLUDED_SERVICES, KNOWN_DEPENDENCIES,
)
from engine.debloat.backup import BackupManager
from rexlog import logger


def _apply_protection(
    items: list[DebloatItem], dep_map: DependencyMap
) -> list[DebloatItem]:
    """Apply protection rules to all items.

    1. Check if service is protected by dependency map
    2. Check if AppX is in protected list
    3. Check if OEM is in protected list
    4. Check if gaming software depends on this
    5. Filter out protected items
    6. Assign display groups
    """
    result: list[DebloatItem] = []

    for item in items:
        protected = False
        reason = ""
        required_by: list[str] = []

        # Check service protection via dependency map
        if item.source == "Service":
            svc_name = item.detail_service or item.id.replace("svc_", "")
            is_prot, prot_reason = is_protected(svc_name, dep_map)
            if is_prot:
                protected = True
                reason = prot_reason
                if svc_name in dep_map.services_needed:
                    required_by = sorted(dep_map.services_needed[svc_name])

        # Check AppX protection
        elif item.source == "Microsoft Store App":
            pkg_name = item.id.replace("appx_", "")
            if pkg_name in PROTECTED_APPX:
                protected = True
                reason = "Core Windows component"

        # Check OEM protection
        elif item.source == "OEM Software":
            for pattern in PROTECTED_OEM:
                if pattern.lower() in item.name.lower():
                    protected = True
                    reason = "Driver-related or hardware control software"
                    break

        # Check if gaming software depends on this service
        if not protected and item.source in ("Service", "Xbox Service"):
            svc_name = item.detail_service or item.id.replace("svc_", "")
            for sw in dep_map.gaming_software:
                for dep_pattern, deps in KNOWN_DEPENDENCIES.items():
                    if dep_pattern.lower() in sw.name.lower():
                        if svc_name in deps.get("required_services", set()):
                            protected = True
                            reason = f"Required by gaming software: {sw.name}"
                            required_by = [sw.name]
                            item.is_gaming_related = True
                            break
                if protected:
                    break

        # Also check if item is in the excluded services list
        if not protected:
            svc_name = item.detail_service or item.id.replace("svc_", "")
            if svc_name in EXCLUDED_SERVICES:
                protected = True
                reason = "Core Windows service"

        # Skip protected items
        if protected:
            item.is_protected = True
            item.protected_reason = reason
            item.required_by = required_by
            continue

        # Assign group
        item.group = _assign_group(item)
        result.append(item)

    return result


def _assign_group(item: DebloatItem) -> str:
    """Assign a display group for categorization."""
    name_lower = item.name.lower()

    if item.category == DebloatCategory.MICROSOFT_STORE:
        return "Microsoft Store Apps"

    if item.category == DebloatCategory.THIRD_PARTY:
        return "Third-Party Apps"

    if item.category == DebloatCategory.OEM:
        return "OEM Apps"

    if item.category == DebloatCategory.OPTIONAL_SERVICES:
        if "xbox" in name_lower or "game" in name_lower:
            return "Xbox Services"
        if any(x in name_lower for x in ["phone", "telephony"]):
            return "Phone & Telephony"
        if any(x in name_lower for x in ["nfc", "payment"]):
            return "NFC & Payments"
        if any(x in name_lower for x in ["map", "geoloc", "location"]):
            return "Location & Maps"
        if any(x in name_lower for x in ["retail", "demo", "insider"]):
            return "Special Modes"
        if any(x in name_lower for x in ["media", "sharing"]):
            return "Media & Sharing"
        return "Optional Services"

    if item.category == DebloatCategory.SCHEDULED_TASKS:
        return "Scheduled Tasks"

    if item.category == DebloatCategory.STARTUP:
        return "Startup Programs"

    return "Other"


class DebloatEngine:
    """Main engine for Smart Debloater operations."""

    def __init__(self):
        self.backup = BackupManager()
        self.result: Optional[DebloatResult] = None

    def scan(self, progress_callback: Optional[Callable[[str, int], None]] = None) -> DebloatResult:
        """Run full system scan."""
        start = time.time()

        def _cb(msg, pct):
            if progress_callback:
                progress_callback(msg, pct)

        _cb("Detecting Windows installation...", 5)
        os_info = scan_os()

        _cb("Scanning Microsoft Store apps...", 15)
        items: list[DebloatItem] = scan_appx_packages()

        _cb("Scanning third-party applications...", 30)
        items.extend(scan_third_party_apps())

        _cb("Scanning OEM software...", 45)
        items.extend(scan_oem_apps())

        _cb("Scanning optional services...", 60)
        items.extend(scan_optional_services())

        _cb("Scanning scheduled tasks...", 72)
        items.extend(scan_scheduled_tasks())

        _cb("Scanning startup entries...", 80)
        items.extend(scan_startup_entries())

        _cb("Detecting installed software and dependencies...", 88)
        dep_map = scan_dependencies()

        _cb("Applying protection rules...", 94)
        total_before = len(items)
        filtered = _apply_protection(items, dep_map)
        total_protected = total_before - len(filtered)

        _cb("Organizing results...", 98)

        # Deduplicate
        seen: set[str] = set()
        unique: list[DebloatItem] = []
        for item in filtered:
            if item.id not in seen:
                seen.add(item.id)
                unique.append(item)

        result = DebloatResult(
            os_info=os_info,
            items=unique,
            scan_time=time.time() - start,
            dep_map=dep_map,
            is_gaming_pc=dep_map.is_gaming_pc,
            gaming_software=[sw.name for sw in dep_map.gaming_software],
            total_protected=total_protected,
            total_debloatable=len(unique),
        )
        result.organize()
        self.result = result

        _cb("Scan complete", 100)

        logger.info(
            f"Debloat scan: {len(unique)} debloatable, {total_protected} protected, "
            f"{len(result.categories)} categories in {result.scan_time:.1f}s"
        )
        return result

    def apply(self, items: list[DebloatItem], os_info: dict,
              progress_callback: Optional[Callable[[str, int], None]] = None) -> tuple[bool, list[str]]:
        """Backup, apply, and verify selected items."""
        if progress_callback:
            progress_callback("Creating backup...", 5)

        session = self.backup.capture_state(items, os_info)

        if progress_callback:
            progress_callback(f"Applying {len(items)} changes...", 30)

        apply_ok, apply_errors = self.backup.apply_items(items)

        if progress_callback:
            progress_callback("Verifying changes...", 70)

        verify_ok, verify_errors = self.backup.verify_items(items)

        all_errors = apply_errors + verify_errors
        success = apply_ok and verify_ok

        if not success and all_errors:
            if progress_callback:
                progress_callback("Verification failed — rolling back...", 85)
            rollback_ok, rollback_errors = self.backup.rollback()
            all_errors.extend(rollback_errors)
            if progress_callback:
                progress_callback("Rollback complete", 95)
        else:
            if progress_callback:
                progress_callback("Changes applied successfully", 95)

        if progress_callback:
            progress_callback("Done", 100)

        return success, all_errors

    def rollback(self, session_id: Optional[str] = None) -> tuple[bool, list[str]]:
        """Rollback a previous session."""
        return self.backup.rollback(session_id)

    def get_safe_items(self) -> list[DebloatItem]:
        if not self.result:
            return []
        return [i for i in self.result.items if i.risk == RiskLevel.SAFE]

    def get_all_removable(self) -> list[DebloatItem]:
        if not self.result:
            return []
        return [i for i in self.result.items if i.risk != RiskLevel.PROTECTED]
