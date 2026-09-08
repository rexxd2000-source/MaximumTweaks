"""Backup and rollback system for Smart Debloater.

Captures the state of each item before applying changes,
then provides restore capability if something goes wrong.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config.app_config import DIRS
from rexlog import logger


BACKUP_DIR = DIRS["backups"] / "debloat"


@dataclass
class BackupEntry:
    item_id: str
    item_name: str
    item_source: str
    original_state: str
    timestamp: float
    verified: bool = False


@dataclass
class BackupSession:
    session_id: str
    timestamp: float
    os_info: dict
    entries: list[BackupEntry] = field(default_factory=list)
    applied: bool = False
    verified: bool = False
    rolled_back: bool = False


def _run_ps(command: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        return result.stdout.strip()
    except Exception:
        return ""


class BackupManager:
    """Manages backup, apply, verify, and rollback for debloat operations."""

    def __init__(self):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        self.current_session: Optional[BackupSession] = None

    def _session_path(self, session_id: str) -> Path:
        return BACKUP_DIR / f"{session_id}.json"

    def _save_session(self, session: BackupSession):
        data = {
            "session_id": session.session_id,
            "timestamp": session.timestamp,
            "os_info": session.os_info,
            "applied": session.applied,
            "verified": session.verified,
            "rolled_back": session.rolled_back,
            "entries": [
                {
                    "item_id": e.item_id,
                    "item_name": e.item_name,
                    "item_source": e.item_source,
                    "original_state": e.original_state,
                    "timestamp": e.timestamp,
                    "verified": e.verified,
                }
                for e in session.entries
            ],
        }
        path = self._session_path(session.session_id)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_session(self, session_id: str) -> Optional[BackupSession]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = [
                BackupEntry(
                    item_id=e["item_id"],
                    item_name=e["item_name"],
                    item_source=e.get("item_source", ""),
                    original_state=e["original_state"],
                    timestamp=e["timestamp"],
                    verified=e.get("verified", False),
                )
                for e in data.get("entries", [])
            ]
            return BackupSession(
                session_id=data["session_id"],
                timestamp=data["timestamp"],
                os_info=data.get("os_info", {}),
                entries=entries,
                applied=data.get("applied", False),
                verified=data.get("verified", False),
                rolled_back=data.get("rolled_back", False),
            )
        except Exception as exc:
            logger.error(f"Failed to load backup session {session_id}: {exc}")
            return None

    def capture_state(self, items: list, os_info: dict) -> BackupSession:
        """Capture current state of all items before applying changes."""
        session_id = f"debloat_{int(time.time())}_{os.getpid()}"
        session = BackupSession(
            session_id=session_id,
            timestamp=time.time(),
            os_info=os_info,
        )

        for item in items:
            if not hasattr(item, "detected") or not item.detected:
                continue
            original = self._get_current_state(item)
            session.entries.append(BackupEntry(
                item_id=item.id,
                item_name=item.name,
                item_source=getattr(item, "source", ""),
                original_state=original,
                timestamp=time.time(),
            ))

        self._save_session(session)
        self.current_session = session
        logger.info(f"Backup session {session_id} created with {len(session.entries)} entries")
        return session

    def _get_current_state(self, item) -> str:
        """Capture the current state of a debloat item."""
        if hasattr(item, "verify_command") and item.verify_command:
            result = _run_ps(item.verify_command)
            if result:
                return result

        item_id = item.id

        if item_id.startswith("svc_"):
            svc_name = item_id.replace("svc_", "")
            result = _run_ps(f"(Get-Service -Name '{svc_name}' -ErrorAction SilentlyContinue).StartType")
            return result or "Unknown"

        if item_id.startswith("task_"):
            task_name = item_id.replace("task_", "")
            result = _run_ps(f"(Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue).State")
            return result or "Unknown"

        if item_id.startswith("appx_"):
            pkg_name = item_id.replace("appx_", "")
            result = _run_ps(f"(Get-AppxPackage -Name '{pkg_name}' -ErrorAction SilentlyContinue).Status")
            return result or "NotInstalled"

        if item_id.startswith("startup_"):
            return "StartupEntry"

        if item_id.startswith("3p_") or item_id.startswith("oem_"):
            return "Installed"

        return "captured"

    def apply_items(self, items: list) -> tuple[bool, list[str]]:
        """Apply all selected debloat items."""
        errors: list[str] = []

        for item in items:
            if not hasattr(item, "detected") or not item.detected:
                continue
            if not hasattr(item, "remove_command") or not item.remove_command:
                continue

            try:
                _run_ps(item.remove_command, timeout=60)
                logger.info(f"Applied: {item.name} ({item.id})")
            except Exception as exc:
                errors.append(f"{item.name}: {exc}")
                logger.error(f"Failed to apply {item.id}: {exc}")

        if self.current_session:
            self.current_session.applied = True
            self._save_session(self.current_session)

        return len(errors) == 0, errors

    def verify_items(self, items: list) -> tuple[bool, list[str]]:
        """Verify that applied changes took effect."""
        errors: list[str] = []

        for item in items:
            if not hasattr(item, "detected") or not item.detected:
                continue
            if not hasattr(item, "verify_command") or not item.verify_command:
                continue

            try:
                result = _run_ps(item.verify_command, timeout=15)

                if item.id.startswith("svc_"):
                    # For services, check it's disabled
                    if "Disabled" not in result:
                        errors.append(f"{item.name}: still enabled ({result})")
                elif item.id.startswith("task_"):
                    # For tasks, check it's disabled
                    if "Disabled" not in result:
                        errors.append(f"{item.name}: still enabled ({result})")
                elif item.id.startswith("appx_"):
                    # For AppX, check it's gone
                    if result and "NotInstalled" not in result:
                        errors.append(f"{item.name}: still installed ({result})")

            except Exception as exc:
                errors.append(f"{item.name}: verification error ({exc})")

        if self.current_session:
            self.current_session.verified = len(errors) == 0
            self._save_session(self.current_session)

        return len(errors) == 0, errors

    def rollback(self, session_id: Optional[str] = None) -> tuple[bool, list[str]]:
        """Rollback a previous backup session."""
        sid = session_id or (self.current_session.session_id if self.current_session else None)
        if not sid:
            return False, ["No backup session to rollback"]

        session = self._load_session(sid)
        if not session:
            return False, [f"Backup session {sid} not found"]

        errors: list[str] = []
        for entry in session.entries:
            try:
                self._restore_entry(entry)
            except Exception as exc:
                errors.append(f"{entry.item_name}: {exc}")
                logger.error(f"Rollback failed for {entry.item_id}: {exc}")

        session.rolled_back = True
        self._save_session(session)

        logger.info(f"Rollback completed for session {sid} ({len(errors)} errors)")
        return len(errors) == 0, errors

    def _restore_entry(self, entry: BackupEntry):
        """Restore a single backup entry to its original state."""
        item_id = entry.item_id
        original = entry.original_state

        if item_id.startswith("svc_"):
            svc_name = item_id.replace("svc_", "")
            if original == "Manual":
                _run_ps(f"Set-Service -Name '{svc_name}' -StartupType Manual")
            elif original == "Automatic":
                _run_ps(f"Set-Service -Name '{svc_name}' -StartupType Automatic")
            elif original == "Disabled":
                # Was already disabled, leave it
                pass

        elif item_id.startswith("task_"):
            task_name = item_id.replace("task_", "")
            if original in ("Ready", "Running"):
                _run_ps(f"Enable-ScheduledTask -TaskName '{task_name}'")

        elif item_id.startswith("appx_"):
            pkg_name = item_id.replace("appx_", "")
            if original == "NotInstalled":
                _run_ps(
                    f"Get-AppxProvisionedPackage -Online | "
                    f"Where-Object {{$_.DisplayName -eq '{pkg_name}'}} | "
                    f"Add-AppxProvisionedPackage -Online -SkipLicense"
                )

        elif item_id.startswith("startup_"):
            # Startup entries are harder to restore — note this in the log
            logger.warning(f"Startup entry {entry.item_name} was removed; manual restoration may be needed")

        elif item_id.startswith("3p_") or item_id.startswith("oem_"):
            # Third-party/OEM apps: if we have an uninstall string, we can't easily reinstall
            logger.warning(f"Application {entry.item_name} was uninstalled; manual reinstallation may be needed")

    def list_sessions(self) -> list[dict]:
        """List all backup sessions."""
        sessions = []
        for path in BACKUP_DIR.glob("debloat_*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data["session_id"],
                    "timestamp": data["timestamp"],
                    "applied": data.get("applied", False),
                    "verified": data.get("verified", False),
                    "rolled_back": data.get("rolled_back", False),
                    "entries_count": len(data.get("entries", [])),
                })
            except Exception:
                continue
        return sorted(sessions, key=lambda x: x["timestamp"], reverse=True)

    def has_rollback(self) -> bool:
        """Check if there's a rollbackable session."""
        sessions = self.list_sessions()
        return any(
            s["applied"] and not s["rolled_back"]
            for s in sessions
        )
