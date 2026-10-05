"""Live support detection for hardware-dependent tweaks.

Some tweak targets only exist on certain hardware: an Ethernet adapter, an
NVIDIA GPU with nvidia-smi, a specific driver service, a USB hub. A tweak
carries a small ``support`` block declaring which probes must pass on THIS PC
before it may be applied. ``preflight`` evaluates them at the safety gate, so
an unsupported tweak reports ``not_supported`` (the UI renders "Not
Compatible"/"Not supported on this PC") instead of a generic apply failure —
and is never recorded as applied.

Probe kinds (all listed probes must pass):

  {"cmd": "command line", ...}      command exits 0 AND prints output
  {"service": "name", ...}          the Windows service is installed
  {"adapter": "Ethernet*", ...}     >=1 physical network adapter matches the glob
  {"registry": (hive, path, name)}  registry VALUE exists (name = "" -> key)

Every probe accepts an optional ``label`` for the human "missing" reason;
otherwise a default reason is generated.

Probe results are cached per process so a large batch never re-runs the same
command/service/registry read twice. ``invalidate_cache`` clears the cache
after an apply/revert batch (the live system may have changed).
"""
from __future__ import annotations

import fnmatch
import subprocess
import threading

from . import state_checker
from maxlog import logger

_LOCK = threading.Lock()
_CACHE: dict[tuple, bool] = {}


def invalidate_cache() -> None:
    """Drop cached probe answers (call after apply/revert batches)."""
    with _LOCK:
        _CACHE.clear()


def _cached(key: tuple, probe) -> bool:
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        value = probe()
        _CACHE[key] = value
        return value


def _run(command: str, timeout: int = 15) -> tuple[bool, str]:
    """Run a shell command; returns (ok, combined output)."""
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except OSError as exc:
        return False, str(exc)


def _ps(script: str, timeout: int = 30) -> tuple[bool, str]:
    """Run a PowerShell script (single-quoted PS strings only)."""
    return _run(
        f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"',
        timeout=timeout)


# ── probe primitives ────────────────────────────────────────────────────────

def _cmd_probe(command: str) -> bool:
    ok, out = _run(command)
    return ok and bool(out.strip())


def _service_probe(name: str) -> bool:
    return state_checker._svc_start_type(name) is not None


def _physical_adapters() -> list[str]:
    """Names of physical network adapters (Up or not)."""
    ok, out = _ps("Get-NetAdapter -Physical | Select-Object -ExpandProperty Name")
    if not ok:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def _adapter_probe(pattern: str) -> bool:
    names = _physical_adapters()
    low = [n.lower() for n in names]
    return any(fnmatch.fnmatchcase(n, pattern.lower()) for n in low)


def _reg_value_probe(hive: str, path: str, name: str) -> bool:
    return state_checker._reg_data(hive, path, name) is not None


def _reg_key_probe(hive: str, path: str) -> bool:
    ok, _ = _run(f'reg query "{hive}\\{path}"')
    return ok


# ── spec dispatch ───────────────────────────────────────────────────────────

def _run_spec(spec: dict) -> tuple[bool, str]:
    """Run one probe spec; returns (passed, human "missing" reason)."""
    if "cmd" in spec:
        command = spec["cmd"]
        ok = _cached(("cmd", command), lambda: _cmd_probe(command))
        return ok, spec.get("label") or f"Required check did not match: {command}"
    if "service" in spec:
        name = spec["service"]
        ok = _cached(("service", name.strip().lower()),
                     lambda: _service_probe(name))
        return ok, spec.get("label") or f"Required service not installed: {name}"
    if "adapter" in spec:
        pattern = spec["adapter"]
        ok = _cached(("adapter", pattern.lower()),
                     lambda: _adapter_probe(pattern))
        return ok, spec.get("label") or f"No {pattern} adapter detected"
    if "registry" in spec:
        hive, path, name = spec["registry"]
        if name:
            ok = _cached(("reg_value", hive.upper(), path, name.lower()),
                         lambda: _reg_value_probe(hive, path, name))
            return ok, spec.get("label") or f"Registry value not found: {hive}\\{path} [{name}]"
        ok = _cached(("reg_key", hive.upper(), path),
                     lambda: _reg_key_probe(hive, path))
        return ok, spec.get("label") or f"Registry key not found: {hive}\\{path}"
    logger.warn("probe: unknown support probe spec ignored %r", spec)
    return True, ""


def evaluate_support(tweak: dict) -> tuple[bool, list[str]]:
    """Evaluate a tweak's ``support`` probes against the live PC.

    Returns (supported, [missing-reasons]). A tweak with no ``support`` block
    is always supported.
    """
    probes = tweak.get("support") or []
    if not probes:
        return True, []
    reasons = []
    for spec in probes:
        ok, text = _run_spec(spec)
        if not ok:
            reasons.append(text)
    return (not reasons), reasons