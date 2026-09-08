"""Shared Network Latency Manager (latency v4 spec, network items).

NIC-level latency/power operations that run against whichever active
*physical* network adapters exist right now.  Every op is detect-first and
revert-safe: a property is only touched when the adapter actually exposes it,
only ever with a value the driver reports as valid, and never on absent or
unsupported adapters (skipped with a reason, also never forced).

Implemented ops (each restores the exact captured original via engine.state
``netadp_backups`` keyed by tweak id):

  interrupt_moderation  disable the adapter's Interrupt Moderation property
  rss                   restore Receive-Side Scaling (global + adapter RSS)
  nicpower              disable NIC power-saving advanced properties
                        (Energy Efficient Ethernet, Green Ethernet, Power
                        Saving Mode, Gigabit Lite, Ultra Low Power Mode, ...)
"""
from __future__ import annotations

import json
import re
import subprocess

from engine.state import (
    get_netadp_backups,
    save_netadp_backups,
    clear_netadp_backups,
)
from maxlog import logger

# Advanced-property DisplayName substrings whose low-power states add
# per-packet latency (matched case-insensitively).
POWER_PROPS = (
    "energy efficient ethernet",
    "green ethernet",
    "power saving mode",
    "gigabit lite",
    "ultra low power mode",
)

# DisplayValue tokens that mean "power saving / moderation disabled".
_DISABLED_TOKENS = ("disabled", "disable", "off", "0", "none", "no")

# base op -> human label (executor reports)
OP_NAMES = {
    "interrupt_moderation": "Disable NIC Interrupt Moderation",
    "interrupt_moderation_revert": "Restore prior Interrupt Moderation",
    "rss": "Restore Receive-Side Scaling",
    "rss_revert": "Restore prior Receive-Side Scaling",
    "nicpower": "Disable NIC Power Saving",
    "nicpower_revert": "Restore prior NIC power saving",
}


# ── command helpers ────────────────────────────────────────────────────────

def _run(cmd: str, timeout: int = 20) -> tuple[bool, str]:
    """Run a shell command; returns (ok, output). No console window opens."""
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            creationflags=0x08000000,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "command timed out"
    except OSError as exc:
        return False, str(exc)


def _ps(script: str, timeout: int = 45) -> tuple[bool, str]:
    """Run a PowerShell script (single-quoted PS strings only)."""
    return _run(f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{script}"',
                timeout=timeout)


def _parse_rows(text: str) -> list[dict]:
    """Parse ConvertTo-Json output (single object, array, or empty)."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    return []


# ── read-only queries (shared with engine.state_checker) ──────────────────

def adapter_names() -> list[str]:
    """Names of currently-Up physical network adapters."""
    ok, out = _ps(
        "Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' } "
        "| Select-Object -ExpandProperty Name")
    if not ok:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def advanced_props(adapter: str) -> list[dict]:
    """Advanced-property dicts (DisplayName/DisplayValue/RegistryKeyword/
    ValidDisplayValues) for one adapter. Empty when the query fails."""
    ok, out = _ps(
        f"Get-NetAdapterAdvancedProperty -Name '{adapter}' "
        "-ErrorAction SilentlyContinue "
        "| Select-Object DisplayName,DisplayValue,RegistryKeyword,ValidDisplayValues "
        "| ConvertTo-Json -Compress")
    return _parse_rows(out) if ok else []


def rss_state() -> list[dict]:
    """[{adapter, enabled}] for RSS-capable active adapters only."""
    ok, out = _ps(
        "Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { "
        "$a = $_.Name; $r = Get-NetAdapterRss -Name $a -ErrorAction SilentlyContinue; "
        "if ($r) { [PSCustomObject]@{ Adapter = $a; Enabled = ($r.Enabled -eq $true) } } "
        "} | ConvertTo-Json -Compress")
    return _parse_rows(out) if ok else []


def netsh_rss() -> str | None:
    """Global TCP RSS state: 'enabled' | 'disabled' | None (unreadable)."""
    ok, out = _run("netsh int tcp show global")
    if not ok:
        return None
    for line in out.splitlines():
        m = re.match(r"^\s*Receive-Side Scaling State\s*:\s*(\S+)", line)
        if m:
            return m.group(1).strip().lower()
    return None


# ── property classification helpers ────────────────────────────────────────

def is_interrupt_moderation(display: str, keyword: str) -> bool:
    d = (display or "").strip().lower()
    k = (keyword or "").strip().lower().replace(" ", "")
    return "interrupt moderation" in d or "interruptmoderation" in k


def is_power_prop(display: str, keyword: str) -> bool:
    d = (display or "").strip().lower()
    k = (keyword or "").strip().lower().replace(" ", "")
    for name in POWER_PROPS:
        if name in d or name.replace(" ", "") in k:
            return True
    return False


def is_disabled_value(value: str) -> bool:
    return (value or "").strip().lower() in _DISABLED_TOKENS


def _disable_token(valid: list) -> str | None:
    """Pick the valid DisplayValue token that disables the feature."""
    vals = [str(v) for v in valid]
    low = [v.lower() for v in vals]
    for cand in _DISABLED_TOKENS:
        if cand in low:
            return vals[low.index(cand)]
    return None


# ── low-level writers ──────────────────────────────────────────────────────

def _set_prop(adapter: str, display_name: str, value: str) -> tuple[bool, str]:
    ok, out = _ps(
        f"Set-NetAdapterAdvancedProperty -Name '{adapter}' "
        f"-DisplayName '{display_name}' -DisplayValue '{value}' -ErrorAction Stop")
    return ok, out


def _netsh_set_rss(enabled: bool) -> tuple[bool, str]:
    ok, out = _run(f"netsh int tcp set global rss={'enabled' if enabled else 'disabled'}")
    return ok, out or "Compatible"


# ── operations (apply) ─────────────────────────────────────────────────────

def _no_adapter() -> tuple[bool, str, list]:
    return False, "no active physical network adapter found", [
        "No active physical network adapter - connect to a network, then re-apply."]


def _apply_interrupt_moderation(tid: str) -> tuple[bool, str, list]:
    adapters = adapter_names()
    if not adapters:
        return _no_adapter()
    entries = []
    notes = []
    for a in adapters:
        props = [p for p in advanced_props(a)
                 if is_interrupt_moderation(p.get("DisplayName"), p.get("RegistryKeyword"))]
        if not props:
            notes.append(f"{a}: Interrupt Moderation not exposed - skipped")
            continue
        props.sort(key=lambda p: len(str(p.get("DisplayName") or "")))
        p = props[0]
        entries.append({
            "kind": "prop", "adapter": a,
            "prop": str(p.get("DisplayName") or "Interrupt Moderation"),
            "prev_value": str(p.get("DisplayValue") or "").strip(),
            "valid": [str(v) for v in (p.get("ValidDisplayValues") or [])],
        })
    if not entries:
        return True, "interrupt moderation not exposed on any adapter", notes
    save_netadp_backups(tid, {"op": "interrupt_moderation", "entries": entries})
    results = []
    ok_all = True
    for e in entries:
        if is_disabled_value(e["prev_value"]):
            results.append(f"{e['adapter']}: Interrupt Moderation already disabled")
            continue
        token = _disable_token(e["valid"])
        if token is None:
            results.append(
                f"{e['adapter']}: no disabled-compatible value exposed "
                f"(valid: {', '.join(e['valid']) or 'none'}) - skipped")
            continue
        ok, err = _set_prop(e["adapter"], e["prop"], token)
        ok_all = ok_all and ok
        results.append(f"{e['adapter']}: Interrupt Moderation -> {token}" if ok
                       else f"{e['adapter']}: {err}")
    results.extend(notes)
    return ok_all, ("all done" if ok_all else "some targets unavailable/denied"), results


def _apply_nicpower(tid: str) -> tuple[bool, str, list]:
    adapters = adapter_names()
    if not adapters:
        return _no_adapter()
    entries = []
    notes = []
    for a in adapters:
        props = [p for p in advanced_props(a)
                 if is_power_prop(p.get("DisplayName"), p.get("RegistryKeyword"))]
        if not props:
            notes.append(f"{a}: no NIC power-saving property exposed - skipped")
            continue
        for p in props:
            entries.append({
                "kind": "prop", "adapter": a,
                "prop": str(p.get("DisplayName") or "").strip(),
                "prev_value": str(p.get("DisplayValue") or "").strip(),
                "valid": [str(v) for v in (p.get("ValidDisplayValues") or [])],
            })
    if not entries:
        return True, "no NIC power-saving property exposed on any adapter", notes
    save_netadp_backups(tid, {"op": "nicpower", "entries": entries})
    results = []
    ok_all = True
    for e in entries:
        if is_disabled_value(e["prev_value"]):
            results.append(f"{e['adapter']}: {e['prop']} already disabled")
            continue
        token = _disable_token(e["valid"])
        if token is None:
            results.append(
                f"{e['adapter']}: {e['prop']} has no disabled-compatible value "
                f"(valid: {', '.join(e['valid']) or 'none'}) - skipped")
            continue
        ok, err = _set_prop(e["adapter"], e["prop"], token)
        ok_all = ok_all and ok
        results.append(f"{e['adapter']}: {e['prop']} -> {token}" if ok
                       else f"{e['adapter']}: {err}")
    results.extend(notes)
    return ok_all, ("all done" if ok_all else "some targets unavailable/denied"), results


def _apply_rss(tid: str) -> tuple[bool, str, list]:
    adapters = adapter_names()
    if not adapters:
        return _no_adapter()
    global_prev = netsh_rss()
    rows = rss_state()
    entries = []
    if global_prev is not None:
        entries.append({"kind": "rss_global", "prev": global_prev})
    for r in rows:
        entries.append({
            "kind": "rss_adapter",
            "adapter": str(r.get("adapter") or "").strip(),
            "prev": "enabled" if r.get("enabled") else "disabled",
            "supported": True,
        })
    if not entries:
        return True, "RSS not exposed (global state unreadable, no adapter reports RSS)", [
            "RSS state unavailable - nothing restored"]
    save_netadp_backups(tid, {"op": "rss", "entries": entries})
    results = []
    ok_all = True
    if global_prev is not None:
        if global_prev == "enabled":
            results.append("global RSS already enabled")
        else:
            ok, err = _netsh_set_rss(True)
            ok_all = ok_all and ok
            results.append("global RSS -> enabled" if ok else f"global RSS: {err}")
    for e in entries:
        if e["kind"] != "rss_adapter":
            continue
        if e["prev"] == "enabled":
            results.append(f"{e['adapter']}: adapter RSS already enabled")
            continue
        ok, err = _ps(f"Enable-NetAdapterRss -Name '{e['adapter']}' -ErrorAction Stop")
        ok_all = ok_all and ok
        results.append(f"{e['adapter']}: adapter RSS -> enabled" if ok
                       else f"{e['adapter']}: {err}")
    return ok_all, ("all done" if ok_all else "some targets unavailable/denied"), results


# ── revert ─────────────────────────────────────────────────────────────────

def _restore_entry(e: dict) -> tuple[bool, str]:
    kind = e.get("kind")
    adapter = str(e.get("adapter") or "").strip()
    if kind == "prop":
        prop = str(e.get("prop") or "").strip()
        prev = str(e.get("prev_value") or "").strip()
        if not prop:
            return True, "(incomplete NIC snapshot record - nothing to restore)"
        ok, err = _set_prop(adapter, prop, prev)
        return ok, (f"{adapter}: {prop} restored -> {prev}" if ok
                    else f"{adapter}: {err}")
    if kind == "rss_global":
        want = e.get("prev") != "disabled"
        ok, err = _netsh_set_rss(want)
        return ok, (f"global RSS restored -> {'enabled' if want else 'disabled'}" if ok
                    else f"global RSS: {err}")
    if kind == "rss_adapter":
        if not e.get("supported"):
            return True, f"{adapter}: no RSS support - nothing to restore"
        want = e.get("prev") != "disabled"
        cmd = "Enable-NetAdapterRss" if want else "Disable-NetAdapterRss"
        ok, err = _ps(f"{cmd} -Name '{adapter}' -ErrorAction Stop")
        return ok, (f"{adapter}: adapter RSS restored -> {'enabled' if want else 'disabled'}"
                    if ok else f"{adapter}: {err}")
    return True, f"unknown NIC backup record {kind!r} - nothing to restore"


def _do_revert(base: str, tid: str) -> tuple[bool, str, list]:
    payload = get_netadp_backups(tid) or {}
    entries = payload.get("entries") or []
    if not entries:
        return True, "no prior NIC snapshot - nothing to restore", [
            "No prior NIC snapshot for this tweak - nothing to restore"]
    results = []
    ok_all = True
    for e in entries:
        ok, detail = _restore_entry(e)
        ok_all = ok_all and ok
        results.append(detail)
    if ok_all:
        clear_netadp_backups(tid)
    logger.info(f"netadp: reverted {base} for {tid} (ok={ok_all})")
    return ok_all, ("all done" if ok_all else "some targets unavailable/denied"), results


# ── public entry (used by the executor) ────────────────────────────────────

_OPS = {
    "interrupt_moderation": _apply_interrupt_moderation,
    "rss": _apply_rss,
    "nicpower": _apply_nicpower,
}


def run_op(op: str, tweak_id: str | None = None) -> tuple[bool, str, list]:
    """Run a NIC op from the executor (apply or revert).

    Returns (ok, summary, detail lines).
    """
    tid = tweak_id or "netadp"
    revert = op.endswith("_revert")
    base = op[: -len("_revert")] if revert else op
    if base not in _OPS:
        return False, f"unknown netadp op {op!r}", []
    try:
        if revert:
            return _do_revert(base, tid)
        return _OPS[base](tid)
    except Exception as exc:  # noqa: BLE001 - report and continue
        return False, f"{type(exc).__name__}: {exc}", []