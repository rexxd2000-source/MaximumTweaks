"""Backup and rollback system for Delay Destroyer.

Every modification follows: BACKUP -> APPLY -> VERIFY
Rollback persists across restarts via JSON state file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from rexlog import logger


BACKUP_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "MaximumTweaks" / "dd_backups"


@dataclass
class BackupEntry:
    fix_id: str
    action_desc: str
    kind: str
    path: str = ""
    name: str = ""
    original_value: str = ""
    original_type: str = "REG_DWORD"
    timestamp: float = 0.0


@dataclass
class BackupSession:
    session_id: str = ""
    created_at: float = 0.0
    entries: list[BackupEntry] = field(default_factory=list)
    applied_fixes: list[str] = field(default_factory=list)
    rolled_back: bool = False


def _reg_read(path: str, name: str) -> tuple[str, str]:
    try:
        cmd = f'reg query "{path}" /v "{name}"'
        out = subprocess.check_output(
            cmd, shell=True, text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if name.lower() in line.lower():
                parts = line.split()
                if len(parts) >= 3:
                    rtype = parts[1] if len(parts) >= 4 else "REG_DWORD"
                    value = " ".join(parts[2:])
                    return value, rtype
    except Exception:
        pass
    return "", ""


def _reg_write(path: str, name: str, value: str, rtype: str = "REG_DWORD"):
    cmd = f'reg add "{path}" /v "{name}" /t {rtype} /d "{value}" /f'
    try:
        subprocess.run(cmd, shell=True, timeout=10, capture_output=True,
                       creationflags=0x08000000)
    except Exception as exc:
        logger.warn(f"DD backup: reg write failed: {exc}")


def _reg_delete(path: str, name: str):
    cmd = f'reg delete "{path}" /v "{name}" /f'
    try:
        subprocess.run(cmd, shell=True, timeout=10, capture_output=True,
                       creationflags=0x08000000)
    except Exception:
        pass


def _svc_state(name: str) -> str | None:
    try:
        out = subprocess.check_output(
            f'sc qc "{name}"', shell=True, text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL)
        m = re.search(r"START_TYPE\s+:\s+\w+\s+(\w+)", out)
        return m.group(1).lower() if m else None
    except Exception:
        return None


class BackupManager:
    def __init__(self):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def _session_path(self, sid: str) -> Path:
        return BACKUP_DIR / f"{sid}.json"

    def _rollback_path(self) -> Path:
        return BACKUP_DIR / "pending_rollback.json"

    def create_session(self, session_id: str) -> BackupSession:
        return BackupSession(session_id=session_id, created_at=time.time())

    def backup_fix(self, session: BackupSession, fix_id: str,
                   actions: list) -> list[BackupEntry]:
        entries = []
        for action in actions:
            entry = BackupEntry(
                fix_id=fix_id,
                action_desc=getattr(action, "description", ""),
                kind="unknown",
                timestamp=time.time())
            cmd = getattr(action, "cmd", "")
            verify = getattr(action, "verify_cmd", "")
            if "reg add" in cmd or ("reg query" in verify and verify):
                entry.kind = "registry"
                entry.path, entry.name = self._extract_reg(cmd, verify)
                if entry.path and entry.name:
                    val, rtype = _reg_read(entry.path, entry.name)
                    entry.original_value = val
                    entry.original_type = rtype
            elif "powercfg" in cmd:
                entry.kind = "powercfg"
                entry.path = cmd
                entry.original_value = self._capture_powercfg(cmd)
            elif "sc config" in cmd or "sc stop" in cmd:
                entry.kind = "service"
                entry.path = self._extract_svc(cmd)
                entry.original_value = _svc_state(entry.path) or "unknown"
            else:
                entry.kind = "cmd"
                entry.path = cmd
                if verify:
                    try:
                        out = subprocess.check_output(
                            verify, shell=True, text=True, timeout=10,
                            creationflags=0x08000000, stderr=subprocess.DEVNULL)
                        entry.original_value = out.strip()
                    except Exception:
                        pass
            entries.append(entry)
            session.entries.append(entry)
        return entries

    def rollback_session(self, session: BackupSession) -> tuple[int, int]:
        ok, fail = 0, 0
        for entry in reversed(session.entries):
            try:
                self._rollback_entry(entry)
                ok += 1
            except Exception as exc:
                logger.warn(f"DD rollback failed: {entry.fix_id}: {exc}")
                fail += 1
        session.rolled_back = True
        self.save_session(session)
        return ok, fail

    def _rollback_entry(self, entry: BackupEntry):
        if entry.kind == "registry":
            if entry.original_value:
                _reg_write(entry.path, entry.name,
                           entry.original_value, entry.original_type)
            else:
                _reg_delete(entry.path, entry.name)
        elif entry.kind == "powercfg":
            if entry.original_value:
                subprocess.run(
                    f"powercfg /setactive {entry.original_value}",
                    shell=True, timeout=10, capture_output=True,
                    creationflags=0x08000000)
        elif entry.kind == "service":
            if entry.original_value and entry.original_value != "unknown":
                subprocess.run(
                    f"sc config \"{entry.path}\" start= {entry.original_value}",
                    shell=True, timeout=10, capture_output=True,
                    creationflags=0x08000000)

    def save_session(self, session: BackupSession):
        try:
            data = {
                "session_id": session.session_id,
                "created_at": session.created_at,
                "rolled_back": session.rolled_back,
                "applied_fixes": session.applied_fixes,
                "entries": [
                    {
                        "fix_id": e.fix_id,
                        "action_desc": e.action_desc,
                        "kind": e.kind,
                        "path": e.path,
                        "name": e.name,
                        "original_value": e.original_value,
                        "original_type": e.original_type,
                        "timestamp": e.timestamp,
                    }
                    for e in session.entries
                ],
            }
            self._session_path(session.session_id).write_text(
                json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warn(f"DD backup save failed: {exc}")

    def load_session(self, session_id: str) -> BackupSession | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            session = BackupSession(
                session_id=data["session_id"],
                created_at=data["created_at"],
                rolled_back=data.get("rolled_back", False),
                applied_fixes=data.get("applied_fixes", []))
            for e in data.get("entries", []):
                session.entries.append(BackupEntry(**e))
            return session
        except Exception as exc:
            logger.warn(f"DD backup load failed: {exc}")
            return None

    def has_pending_rollback(self) -> bool:
        return self._rollback_path().exists()

    def save_pending_rollback(self, session_id: str, fixes: list[str]):
        try:
            self._rollback_path().write_text(
                json.dumps({"session_id": session_id, "fixes": fixes}),
                encoding="utf-8")
        except Exception:
            pass

    def clear_pending_rollback(self):
        try:
            p = self._rollback_path()
            if p.exists():
                p.unlink()
        except Exception:
            pass

    def list_sessions(self) -> list[str]:
        try:
            return [f.stem for f in BACKUP_DIR.glob("*.json")
                    if f.stem != "pending_rollback"]
        except Exception:
            return []

    @staticmethod
    def _extract_reg(cmd: str, verify: str) -> tuple[str, str]:
        path, name = "", ""
        m = re.search(r'reg (?:add|query)\s+"([^"]+)"', cmd or verify)
        if m:
            path = m.group(1)
        m = re.search(r'/v\s+"([^"]+)"', cmd or verify)
        if m:
            name = m.group(1)
        return path, name

    @staticmethod
    def _capture_powercfg(cmd: str) -> str:
        out = subprocess.check_output(
            "powercfg /getactivescheme", shell=True, text=True, timeout=10,
            creationflags=0x08000000, stderr=subprocess.DEVNULL)
        parts = out.strip().split()
        return parts[3] if len(parts) >= 4 else ""

    @staticmethod
    def _extract_svc(cmd: str) -> str:
        m = re.search(r'sc (?:config|stop)\s+"([^"]+)"', cmd)
        return m.group(1) if m else ""
