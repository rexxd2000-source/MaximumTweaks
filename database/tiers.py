"""Tier classification and verification, derived from actual tweak implementations.

This module never reads ``name`` or ``desc`` to decide a tier. A tweak's
tier is inferred from what it *does*: the registry hives and values it writes,
the executables and PowerShell cmdlets it invokes, the services and scheduled
tasks it changes, the power settings it alters, and its hardware gates. Text is
marketing; ``actions`` is fact.

Why not ``risk``? Because in this database ``risk`` does not describe risk.
All 16 NVIDIA, all 17 AMD, all 14 Intel, all 10 experimental and all 15
delay-destroyer tweaks are recorded ``risk="safe"``. Only 35 of 863 tweaks are
``moderate``/``advanced``. Tying tiers to that field would put driver and boot
changes in the free tier. So ``risk`` is reported as metadata and the tier comes
from the implementation signature instead.

Two independent judgements are produced for every tweak:

``tier``
    The lowest subscription tier that unlocks it. Foundation is the default
    because it must stay compatible and broad; anything that reaches outside
    generic Windows is pushed up.

``verified``
    Whether the implementation was actually inspected and cleared. This is
    deliberately strict and deliberately separate from the tier: an
    unverified tweak keeps its tier but is never presented as a verified
    optimization, and is never force-applied.

Classification is a pure function of the loaded database, so it is
reproducible and cannot drift out of sync with the tweaks it describes.
"""
from __future__ import annotations

import re
from collections import Counter

from config.plans import FOUNDATION, MAXIMUM, PERFORMANCE, normalize_tier

__all__ = [
    "VERIFIED", "UNVERIFIED", "UNSUPPORTED", "BROKEN", "OBSOLETE",
    "DUPLICATE", "DANGEROUS", "EXPERIMENTAL",
    "KNOWN_EXECUTABLES", "extract_implementation", "classify_tier",
    "assess_verification", "audit_tweak", "summarize",
]

# Dispositions, most severe first. A tweak can only hold one.
VERIFIED = "VERIFIED"
UNVERIFIED = "UNVERIFIED"
UNSUPPORTED = "UNSUPPORTED"
BROKEN = "BROKEN"
OBSOLETE = "OBSOLETE"
DUPLICATE = "DUPLICATE"
DANGEROUS = "DANGEROUS"
EXPERIMENTAL = "EXPERIMENTAL"

DISPOSITIONS = (
    UNSUPPORTED, BROKEN, OBSOLETE, DUPLICATE, DANGEROUS, EXPERIMENTAL,
    VERIFIED, UNVERIFIED,
)

#: Real Windows executables the database is allowed to invoke. Anything outside
#: this set is treated as an unknown external dependency and blocks
#: verification - a tweak that runs a binary nobody has vouched for is not one
#: we can call verified.
KNOWN_EXECUTABLES = frozenset({
    "powershell.exe", "cmd.exe", "powercfg.exe", "netsh.exe", "bcdedit.exe",
    "fsutil.exe", "reg.exe", "wmic.exe", "dism.exe", "chkdsk.exe",
    "pnputil.exe", "dxdiag.exe", "nvidia-smi.exe", "ipconfig.exe",
    "wevtutil.exe", "ping.exe", "rundll32.exe", "control.exe", "taskkill.exe",
    "tasklist.exe", "schtasks.exe", "sc.exe", "sfc.exe", "defrag.exe",
    "cleanmgr.exe", "mdsched.exe", "ver.exe", "cleanmgr", "cmd",
    "nvidia-smi", "regedit", "taskkill", "schtasks", "ver", "msinfo32",
    "msinfo32.exe", "dxdiag", "tasklist", "mdsched", "wmic", "reg", "fsutil",
    "ipconfig", "ping", "wevtutil", "rundll32", "control", "sfc", "dism",
    "chkdsk", "defrag", "netsh", "powercfg", "bcdedit", "taskkill.exe",
    "sigverif", "sigverif.exe", "taskmgr", "msconfig", "resmon",
    "pnputil", "wsreset.exe",
})

#: Action kinds that change system state. ``guidance`` is a no-op and does not
#: count as mutating. ``restart`` is excluded deliberately: restarting Explorer
#: or DWM is a transient refresh that leaves no persisted configuration behind,
#: so there is nothing for a revert action to undo.
MUTATING_KINDS = frozenset({
    "reg", "regall", "regkeydel", "regdel", "regdelall", "svc", "sc",
    "svcstart", "svcstop", "cmd", "file", "ini", "inidel", "power",
    "powerscheme", "sched", "appx", "process", "netadp", "mkdir",
})

#: PowerShell verbs that only read state. A command built solely from these
#: cannot change the system, so demanding a revert path for it is wrong - that
#: mistake would have labelled every diagnostic card BROKEN.
READ_ONLY_VERBS = frozenset({
    "Get", "Select", "Show", "Format", "Measure", "Test", "Compare", "Sort",
    "ConvertTo", "ConvertFrom", "Out", "Write", "Group", "Where", "ForEach",
    "Resolve", "Split", "Join", "Measure-Object",
})

#: PowerShell verbs that change state. Any of these makes a command mutating
#: even when the rest of the pipeline only reads, e.g.
#: ``Get-AppxPackage *x* | Remove-AppxPackage`` is a removal.
MUTATING_VERBS = frozenset({
    "Set", "New", "Remove", "Add", "Enable", "Disable", "Start", "Stop",
    "Install", "Uninstall", "Update", "Clear", "Reset", "Rename", "Move",
    "Copy", "Repair", "Optimize", "Import", "Export", "Save", "Suspend",
    "Resume", "Restart", "Register", "Unregister", "Mount", "Dismount",
})

#: Exes that only read when invoked bare, and the GUI launchers and consoles.
_READ_ONLY_BARE = frozenset({
    "ver.exe", "ver", "ping.exe", "ping", "ipconfig.exe", "ipconfig",
    "dxdiag.exe", "dxdiag", "wmic.exe", "wmic", "cleanmgr", "cleanmgr.exe",
    "msinfo32", "msinfo32.exe", "taskmgr", "msconfig", "resmon", "regedit",
    "sigverif", "netsh", "netsh.exe",
})

#: Substrings that make an otherwise read-only command mutating.
_MUTATING_TOKENS = (
    "/set", "set-", "add ", "delete ", "remove", "-remove", "new-",
    "-enable", "-disable", "reg add", "reg delete",
    "powercfg /change", "powercfg /set", "bcdedit", "format ", "del ",
)

# Tools whose subcommands carry their own verbs. These are matched as
# ``<tool> <verb>`` on a word boundary, because a bare token list missed real
# mutations and let them pass as read-only:
#   * ``netsh int tcp set ...``  - the token list only had "netsh interface
#     set", so every other interface word looked informational.
#   * ``wmic pagefileset ... delete`` - "delete " has a trailing space, so a
#     command ending in the verb did not match.
#   * ``wmic computersystem set ...`` - "set" alone is not in the token list at
#     all, since PowerShell's ``Set-*`` is covered by MUTATING_VERBS instead.
_MUTATING_TOOL_VERBS = {
    "netsh": {"set", "add", "delete", "reset", "firewall", "advfirewall"},
    "wmic": {"set", "delete", "create", "modify", "call"},
    "netsh.exe": {"set", "add", "delete", "reset", "firewall", "advfirewall"},
    "wmic.exe": {"set", "delete", "create", "modify", "call"},
}

#: Action kinds that only surface information.
INFO_KINDS = frozenset({"guidance"})

# Implementation signals that are too aggressive to ship in the free tier.
# Each entry is (test, tier, reason) and is evaluated against the facts.
_MAXIMUM_SIGNALS = (
    ("gpu_vendor_specific", "GPU vendor-specific tuning (NVIDIA/AMD/Intel) detected in the implementation."),
    ("boot_config", "Boot configuration changed via bcdedit (boot loader, hypervisor or memory settings)."),
    ("driver_control", "Direct driver or device control (pnputil / nvidia-smi / PnP device writes)."),
    ("custom_power_scheme", "Creates or modifies a named power scheme rather than a built-in setting."),
    ("filesystem_servicing", "Runs a filesystem or component-servicing tool (chkdsk/defrag/sfc/dism) with elevated rights."),
    ("confirmed_risky", "Flagged confirm=True: alters low-level CPU boost or scheduling behaviour."),
    ("mmcss_scheduler", "Multimedia class scheduler / GPU scheduling priority registry changes."),
    ("gaming_cheat_adjacent", "Input-translation or aim-assist style behaviour; not a safe system optimization."),
    ("memory_tuning", "Direct memory/AGP/aperture or large-page tuning."),
    ("deep_hardware_tier", "Hardware-specific tuning gated on CPU family or memory topology."),
)

_PERFORMANCE_SIGNALS = (
    ("hardware_gate", "Hardware-gated: only valid on specific GPU, CPU, storage or audio hardware."),
    ("service_change", "Modifies Windows service start types or runtime state."),
    ("scheduled_task_change", "Modifies a Windows scheduled task."),
    ("network_stack", "Changes the TCP/IP or network-adapter stack."),
    ("appx_removal", "Removes or re-registers an AppX package."),
    ("power_setting", "Alters a Windows power setting."),
    ("app_config_write", "Writes a game or application configuration file."),
    ("cross_hive_write", "Writes to multiple registry hives, so it affects machine-wide state."),
    ("process_control", "Controls game processes at runtime."),
)

# ``when`` keys that gate on real hardware. A tweak carrying any of these is
# ineligible for Foundation, which is defined as broadly compatible.
_HARDWARE_GATE_KEYS = frozenset({
    "gpu", "gpu_type", "cpu_vendor", "cpu_family", "intel_cpu", "amd_cpu",
    "hdd", "ssd", "nvme", "ram_gb", "ram_channels", "audio_realtek",
    "audio_bluetooth", "ntfs",
})

#: Cmdlets / exe names that mean "touch the graphics driver".
_VENDOR_GPU_EXE = frozenset({"nvidia-smi.exe", "nvidia-smi", "amd-*.exe"})
_VENDOR_GPU_REGISTRY = (
    r"\\NVIDIA Corporation\\", r"\\NVIDIA\\", r"SYSTEM\\CurrentControlSet\\Control\\Video",
    r"\\AMD\\", r"\\ATI Technologies\\", r"AMDPP\\",
)
_MMCSS_MARKERS = (
    "Multimedia", "MmcssGameTasks", "SchedulingCategory",
    "GPUPriority", "SystemResponsiveness", "SFIO Priority",
)
_BOOT_EXES = frozenset({"bcdedit.exe", "bcdedit"})
_FILESYSTEM_EXES = frozenset({
    "chkdsk.exe", "defrag.exe", "sfc.exe", "dism.exe", "chkdsk", "defrag",
})
_SERVICING_EXES = frozenset({"dism.exe", "sfc.exe", "chkdsk.exe", "defrag.exe"})
_DRIVER_EXES = frozenset({"pnputil.exe", "nvidia-smi.exe", "dxdiag.exe", "nvidia-smi", "dxdiag"})
_NETWORK_EXES = frozenset({"netsh.exe", "netsh"})
_APPX_MARKERS = ("Appx", "WindowsApps")

_CMD_FIRST_TOKEN = re.compile(
    r'^\s*(?:start\s+)?"?([A-Za-z0-9_.\\-]+)"?(?=\s|$)', re.I)
# PowerShell Verb-Noun cmdlets, e.g. Disable-MMAgent, Get-NetAdapter.
_PS_CMDLET = re.compile(r'\b([A-Z][a-z]+-[A-Z][A-Za-z0-9]+)\b')
_DRIVE_LETTER = re.compile(r'\b[A-Za-z]:\\')

#: cmd.exe builtins that dispatch other programs (or nothing) rather than
#: being binaries themselves: they must never read as an external executable.
_SHELL_BUILTINS = frozenset({
    "start", "if", "exist", "del", "rd", "cd", "dir", "copy", "move",
    "ren", "rename", "mkdir", "echo", "set", "call", "type", "find",
    "findstr", "assoc", "ftype", "title", "exit", "cls", "pause",
})


#: One-shot, self-healing or maintenance commands. They do change process/OS
#: state momentarily, but the change is not a persisted configuration: the tool
#: itself is the repair (sfc/DISM/defrag/chkdsk), the state regenerates on its
#: own (wsreset, temp files, DNS/DHCP), the component restarts itself
#: (Restart-NetAdapter, taskkill dwm), or the snapshot/restore point is
#: inherently additive (Checkpoint-Computer). Demanding a revert action for
#: these would have mislabelled every maintenance card BROKEN.
_TRANSIENT_TOKENS = (
    r"\bsfc\b", r"\bdism\b", r"\bdefrag\b", r"\bchkdsk\b[^\n]*\s/[fr]\b",
    r"\bwsreset(?:\.exe)?\b", r"checkpoint-computer", r"restart-netadapter",
    r"netsh\s+winsock\s+reset", r"netsh\s+int(?:ernal)?\s+ip\s+reset",
    r"taskkill\b[^\n]*\s/im\s+dwm\.exe", r"\bdel\b[^\n]*%temp%",
    r"bcdedit\b[^\n]*deletevalue",
)
_TRANSIENT_PATTERNS = tuple(re.compile(p, re.I) for p in _TRANSIENT_TOKENS)

#: PowerShell ``-Command "<script>"`` wrapper. We classify the inner script,
#: not the ``powershell.exe`` wrapper, so ``netsh wlan show interfaces`` and
#: ``Get-NetAdapter | Format-Table`` read as read-only while any mutating
#: cmdlet inside still wins.
_PS_COMMAND_INNER = re.compile(
    r'-Command\s*["\'](?P<inner>.*?)["\']\s*$', re.I | re.S)

#: Maintenance/repair tools that make a *transient* change rather than a
#: persistent one. A bash-style whitelist is safer than a blacklist: nothing
#: outside this set is ever excused from having a revert path.
def is_transient_command(command: str) -> bool:
    """True when a ``cmd`` action performs a self-healing or one-shot repair.

    Maintenance commands (``sfc /scannow``, DISM image cleanup, ``defrag``,
    ``chkdsk /f``), cache resets (``wsreset``, ``del %TEMP%``), network-stack
    resets (``netsh winsock reset``) and restore-point/restart operations
    (``Checkpoint-Computer``, ``Restart-NetAdapter``, ``taskkill dwm.exe``)
    change state without persisting a configuration, so they cannot be
    "undone" by a revert action - Windows regenerates or re-runs them.
    """
    low = command.strip().lower()
    return any(p.search(low) for p in _TRANSIENT_PATTERNS)


def _cmd_executable(command: str) -> str:
    """First real executable in a command string, lowercased.

    A bare ``Disable-MMAgent`` is a PowerShell cmdlet, not
    ``disable-mmagent.exe``, so Verb-Noun tokens are never reported as
    binaries. The ``powershell`` wrapper itself is not a claim either - the
    inner script governs - and cmd.exe builtins / GUI control surfaces
    (``.msc``/``.cpl``) dispatch other programs rather than being one.

    Everything else - a token reaching ``.exe`` (including a path form) or
    any other extension-less invocation - is returned verbatim so the caller
    audits it against ``KNOWN_EXECUTABLES``. That is the whole point: an
    unknown executable must surface as a claim, not vanish into an empty
    string.
    """
    stripped = command.strip()
    m = _CMD_FIRST_TOKEN.match(stripped)
    if not m:
        return ""
    raw = m.group(1)
    if _PS_CMDLET.fullmatch(raw):
        return ""
    token = raw.lower()
    if token in _SHELL_BUILTINS or token == "powershell":
        return ""
    if token.endswith((".msc", ".cpl")):
        return ""
    return token


def _cmdlets(command: str) -> set[str]:
    """PowerShell Verb-Noun cmdlets referenced by a command string."""
    return set(_PS_CMDLET.findall(command))


def _inner_command(command: str) -> str:
    """Unwrap a ``powershell ... -Command "<script>"`` into its inner script.

    The classification of ``powershell -Command "X"`` must reflect what ``X``
    does, not the fact that powershell.exe launched it. When there is no
    wrapper the command is returned unchanged.
    """
    m = _PS_COMMAND_INNER.search(command)
    if m:
        inner = m.group("inner").strip()
        if inner:
            return inner
    return command


def is_read_only_command(command: str) -> bool:
    """True when a ``cmd`` action cannot change system state.

    Diagnostic cards (``Get-CimInstance Win32_Processor``, ``start msinfo32``,
    ``ver``, ``wevtutil qe``) are not reversible because they have nothing to
    reverse. Treating them as un-reversible would have mislabelled dozens of
    read-only cards BROKEN, so they are excluded from the reversibility test.

    A mutating verb anywhere in the pipeline wins, so
    ``Get-AppxPackage | Remove-AppxPackage`` is correctly *not* read-only.
    ``powershell -Command "<script>"`` wrappers are classified by their inner
    script so pure diagnostics launched through PowerShell stay read-only.
    """
    cmd = command.strip()
    low = _inner_command(cmd).lower()

    verbs = {v for v in _cmdlets(cmd)} | {v for v in _cmdlets(_inner_command(cmd))}
    if any(v.split("-")[0] in MUTATING_VERBS for v in verbs):
        return False
    if any(tok in low for tok in _MUTATING_TOKENS):
        return False

    # Tool-scoped verbs, e.g. "wmic pagefileset where ... delete".
    for tool, tool_verbs in _MUTATING_TOOL_VERBS.items():
        # The verb can appear inside a quoted powershell -Command pipeline,
        # so scan the whole string rather than only the leading word.
        # Up to six trailing words: WMI queries can carry a long ``where``
        # clause before the verb, e.g.
        # ``wmic pagefileset where name="D:\\pagefile.sys" delete``.
        for m in re.finditer(rf"\b{re.escape(tool)}\b((?:\s+\S+){{0,6}})", low):
            words = (w.strip("\"'&|") for w in m.group(1).split())
            if any(w in tool_verbs for w in words):
                return False

    # GUI launchers change no persistent state.
    if low.startswith("start ") or low in {"cleanmgr", "cleanmgr.exe"}:
        return True
    if low.startswith("control "):
        return True
    # MMC consoles (.msc) and Control Panel applets (.cpl) are GUI launchers.
    if re.search(r"\.(?:msc|cpl)\s*$", low):
        return True
    if "wevtutil qe" in low or "wevtutil el" in low:
        return True
    # pnputil enumeration and rescan report or re-enumerate devices; neither
    # rewrites a configuration. Only /remove-device and /add-driver mutate.
    if low.startswith("pnputil") and not any(
        t in low for t in ("/remove-device", "/add-driver", "/delete-driver",
                           "/disable-device", "/enable-device", "/import-device")
    ):
        return True
    # rundll32 refreshing user parameters, and dxdiag writing a report file,
    # change no persisted system configuration.
    if low.startswith("rundll32") or low.startswith("dxdiag"):
        return True
    # Report-only invocations of otherwise-mutating tools.
    if low.startswith("powercfg /batteryreport") or low == "mdsched":
        return True
    if low.startswith("chkdsk") and "/scan" in low:
        return True

    exe = _cmd_executable(_inner_command(cmd))
    if verbs and all(v.split("-")[0] in READ_ONLY_VERBS for v in verbs):
        return True
    if exe and exe in _READ_ONLY_BARE:
        return True
    return False


def _registry_paths(actions) -> list[tuple[str, str]]:
    """(hive, path) for every registry action in ``actions``."""
    out = []
    for action in actions:
        kind = action[0]
        if kind in ("reg", "regdel", "regkeydel") and len(action) >= 3:
            out.append((str(action[1]).upper(), str(action[2])))
        elif kind in ("regall", "regdelall") and len(action) >= 3:
            out.append((str(action[1]).upper(), str(action[2])))
    return out


def extract_implementation(tweak: dict) -> dict:
    """Structural facts about what ``tweak`` actually does.

    Pure introspection over ``actions``/``revert``/``when``; no name matching.
    """
    actions = list(tweak.get("actions") or [])
    reverts = list(tweak.get("revert") or [])
    kinds = [a[0] for a in actions]

    # Reviewer-verified declarations: some encoded PowerShell diagnostics are
    # genuinely read-only/transient but are passed as -EncodedCommand blobs
    # that a heuristic would have to decode to prove. Instead of guessing, the
    # owning human marks those cards explicitly and the audit accepts the
    # declaration with its reason.
    declared_readonly = bool(tweak.get("read_only")) and bool(tweak.get("read_only_reason"))
    declared_transient = bool(tweak.get("transient")) and bool(tweak.get("transient_reason"))

    read_only_cmds = [
        a for a in actions
        if a[0] == "cmd" and len(a) >= 2
        and (is_read_only_command(str(a[1])) or declared_readonly)
    ]
    # A command is "transient" only when it is not also read-only: a
    # maintenance command changes state, an observation does not.
    transient_cmds = [
        a for a in actions
        if a[0] == "cmd" and len(a) >= 2
        and a not in read_only_cmds
        and (is_transient_command(str(a[1])) or declared_transient)
    ]
    _ro = set(read_only_cmds)
    _tr = set(transient_cmds)
    # An action is "state changing" when it can actually alter the machine.
    # Guidance does nothing; a read-only command only observes; a transient
    # command repairs or regenerates state that Windows rebuilds on its own.
    state_changing = [
        a for a in actions
        if a[0] in MUTATING_KINDS
        and a not in _ro
        and a not in _tr
    ]
    mutating = state_changing
    guidance_only = bool(actions) and all(k == "guidance" for k in kinds)
    read_only = bool(actions) and not state_changing and not transient_cmds and not guidance_only
    transient_only = (
        bool(actions) and bool(transient_cmds) and not state_changing
        and not read_only and not guidance_only
    )

    exes, cmdlets = set(), set()
    cmd_strings = []
    mutating_cmds = []
    for action in actions:
        if action[0] == "cmd" and len(action) >= 2:
            cmd = str(action[1])
            cmd_strings.append(cmd)
            if not (is_read_only_command(cmd) or is_transient_command(cmd)
                    or declared_readonly or declared_transient):
                mutating_cmds.append(cmd)
            exe = _cmd_executable(cmd)
            if exe:
                exes.add(exe)
            cmdlets |= _cmdlets(cmd)

    reg_pairs = _registry_paths(actions)
    hives = {h for h, _ in reg_pairs}
    reg_paths = {p for _, p in reg_pairs}

    services = sorted({
        str(a[1]) for a in actions
        if a[0] in ("svc", "svcstart", "svcstop") and len(a) >= 2
    } | {
        str(a[2]) for a in actions
        if a[0] == "sc" and len(a) >= 3
    })
    tasks = sorted({
        str(a[2]) for a in actions
        if a[0] == "sched" and len(a) >= 3
    })
    appx = sorted({
        str(a[2]) for a in actions
        if a[0] == "appx" and len(a) >= 3
    })
    if any(v in cmdlets for v in ("Remove-AppxPackage", "Add-AppxPackage",
                                  "Register-AppxPackage")):
        appx.append("<powershell AppxPackage cmdlet>")
    power_ops = sorted({
        str(a[1]) for a in actions
        if a[0] == "power" and len(a) >= 2
    })
    scheme_ops = [
        a for a in actions if a[0] == "powerscheme"
    ]
    ini_paths = sorted({
        str(a[1]) for a in actions
        if a[0] == "ini" and len(a) >= 2
    })
    net_ops = sorted({
        str(a[1]) for a in actions
        if a[0] == "netadp" and len(a) >= 2
    })
    process_ops = sorted({
        str(a[1]) for a in actions
        if a[0] == "process" and len(a) >= 2
    })

    when = tweak.get("when") or {}
    hw_gates = sorted(k for k in when if k in _HARDWARE_GATE_KEYS)

    tags = {str(x).lower() for x in (tweak.get("tags") or [])}
    # Hardware signals must be derived from commands that actually change
    # state. Reading the device list (`Get-PnpDevice`, `pnputil /enum-devices`,
    # `dxdiag`) touches no driver, so counting it as driver control would push
    # read-only diagnostics into the top tier.
    mut_text = " ".join(mutating_cmds).lower()
    all_text = " ".join(
        [str(tweak.get("name") or ""), str(tweak.get("desc") or "")]
        + cmd_strings
        + [p for _, p in reg_pairs]
        + services + tasks + appx + list(cmdlets)
    ).lower()

    # --- derived implementation signals ---
    mut_exes = {_cmd_executable(c) for c in mutating_cmds} - {""}

    vendor_gpu = any(
        re.search(p, all_text, re.I) for p in _VENDOR_GPU_REGISTRY
    ) or bool(mut_exes & _VENDOR_GPU_EXE) or (
        "gpu" in hw_gates and any(
            v in all_text for v in ("nvidia", "amd", "radeon", "geforce", "intel")
        )
    )

    driver_control = bool(mut_exes & _DRIVER_EXES) or any(
        c in cmdlets for c in ("Set-PnpDevice", "Disable-PnpDevice",
                               "Enable-PnpDevice", "Remove-PnpDevice")
    ) or any(t in mut_text for t in ("/remove-device", "/add-driver",
                                     "/delete-driver", "/disable-device"))

    boot_config = bool(mut_exes & _BOOT_EXES)

    filesystem_servicing = bool(mut_exes & _FILESYSTEM_EXES)

    custom_power_scheme = bool(scheme_ops) or any(
        s in str(scheme_ops) for s in ("duplicate", "create", "delete")
    )

    mmcss = any(m in all_text for m in _MMCSS_MARKERS)

    gaming_cheat_adjacent = (
        tweak.get("module") in ("aim", "delay_destroyer")
        or "aimbot" in all_text or "inputtranslator" in all_text
    )

    memory_tuning = any(
        k in all_text for k in (
            "agp", "aperture", "largepages", "large page", "toplock",
            "first/second level data cache",
        )
    ) or "ram_gb" in hw_gates or "ram_channels" in hw_gates

    deep_hardware_tier = any(k in hw_gates for k in ("cpu_family", "intel_cpu", "ram_channels"))

    network_stack = bool(exes & _NETWORK_EXES) or bool(net_ops) or any(
        c in cmdlets for c in ("New-NetTCPSetting", "Set-NetAdapterAdvancedProperty",
                               "Get-NetAdapterAdvancedProperty", "New-NetFirewallRule")
    )

    reboot = "reboot" in tags or bool(exes & _BOOT_EXES) or any(
        k in all_text for k in ("hibernate", "requires reboot", "restart required")
    )

    hardcoded_drive = bool(_DRIVE_LETTER.search(" ".join(cmd_strings) + " " + " ".join(ini_paths)))

    return {
        "actions": actions,
        "reverts": reverts,
        "state_changing": state_changing,
        "read_only": read_only,
        "transient": bool(transient_cmds),
        "transient_only": transient_only,
        "kinds": kinds,
        "kind_set": set(kinds),
        "mutating_count": len(mutating),
        "guidance_only": guidance_only,
        "exes": exes,
        "cmdlets": cmdlets,
        "cmd_strings": cmd_strings,
        "hives": hives,
        "reg_paths": reg_paths,
        "reg_pairs": reg_pairs,
        "services": services,
        "tasks": tasks,
        "appx": appx,
        "power_ops": power_ops,
        "scheme_ops": scheme_ops,
        "ini_paths": ini_paths,
        "net_ops": net_ops,
        "process_ops": process_ops,
        "hw_gates": hw_gates,
        "when": when,
        "reboot": reboot,
        "hardcoded_drive": hardcoded_drive,
        "cross_hive_write": len(hives) > 1,
        "unknown_exes": sorted(
            e for e in exes
            if e.replace("/", "\\").rsplit("\\", 1)[-1] not in KNOWN_EXECUTABLES
            and not e.startswith("amd-")
        ),
        "flags": {
            "gpu_vendor_specific": vendor_gpu,
            "boot_config": boot_config,
            "driver_control": driver_control,
            "custom_power_scheme": custom_power_scheme,
            "filesystem_servicing": filesystem_servicing,
            "confirmed_risky": bool(tweak.get("confirm")),
            "mmcss_scheduler": mmcss,
            "gaming_cheat_adjacent": gaming_cheat_adjacent,
            "memory_tuning": memory_tuning,
            "deep_hardware_tier": deep_hardware_tier,
            "hardware_gate": bool(hw_gates),
            "service_change": bool(services),
            "scheduled_task_change": bool(tasks),
            "network_stack": network_stack,
            "appx_removal": bool(appx),
            "power_setting": bool(power_ops),
            "app_config_write": bool(ini_paths),
            "cross_hive_write": len(hives) > 1,
            "process_control": bool(process_ops),
        },
    }


def _signal_reason(facts: dict, key: str) -> str:
    for name, reason in _MAXIMUM_SIGNALS + _PERFORMANCE_SIGNALS:
        if name == key:
            return reason
    return key


def classify_tier(facts: dict, tweak: dict | None = None) -> tuple[str, str]:
    """Lowest tier that unlocks the tweak, and why.

    Foundation is the default and must stay broad: it is the tier that ships
    on unknown hardware. Anything reaching a specific GPU vendor, the boot
    loader, a driver, a custom power scheme or a gaming-cheat-adjacent
    transformation is pushed to Maximum; anything hardware-gated, touching
    services, the network stack or AppX is pushed to Performance.
    """
    flags = facts["flags"]

    for key, reason in _MAXIMUM_SIGNALS:
        if flags.get(key):
            return MAXIMUM, reason

    for key, reason in _PERFORMANCE_SIGNALS:
        if flags.get(key):
            return PERFORMANCE, reason

    return FOUNDATION, (
        "Generic, broadly compatible Windows change: "
        f"{facts['mutating_count']} reversible action(s), no vendor, driver or boot dependency."
    )


def _revert_coverage(facts: dict) -> tuple[int, int]:
    """(covered, total) mutating apply actions matched by a revert action.

    Mirrors the executor's own target matching closely enough to measure
    reversibility without duplicating its full logic.
    """
    reverts = facts["reverts"]
    if not reverts:
        return 0, facts["mutating_count"]

    r_reg_paths = {(str(a[1]).upper(), str(a[2])) for a in reverts
                   if a[0] in ("reg", "regdel", "regkeydel", "regall", "regdelall")
                   and len(a) >= 3}
    r_reg_values = {(str(a[1]).upper(), str(a[2]), str(a[3]).lower()) for a in reverts
                    if a[0] in ("reg", "regdel", "regall") and len(a) >= 4}
    r_services = set()
    for a in reverts:
        if a[0] in ("svc", "svcstart", "svcstop") and len(a) >= 2:
            r_services.add(str(a[1]).lower())
        elif a[0] == "sc" and len(a) >= 3:
            r_services.add(str(a[2]).lower())
    r_power = {str(a[1]) for a in reverts if a[0] == "power" and len(a) >= 2}
    r_ini = {(str(a[1]).lower(), str(a[2]).lower(), str(a[3]).lower()) for a in reverts
             if a[0] in ("ini", "inidel") and len(a) >= 4}
    r_tasks = {str(a[2]) for a in reverts if a[0] == "sched" and len(a) >= 3}
    r_scheme = {a for a in reverts if a[0] == "powerscheme"}
    # A tweak that creates its own named scheme reverts by switching away and
    # deleting that scheme, so per-setting revert actions are unnecessary: the
    # whole plan disappears. Requiring them would have flagged every custom
    # power plan as unreversible.
    deletes_own_scheme = any(
        len(a) >= 2 and str(a[1]).lower() in ("delete", "create", "duplicate")
        for a in reverts if a[0] == "powerscheme"
    )
    creates_scheme = any(
        a[0] == "powerscheme" and len(a) >= 2
        and str(a[1]).lower() in ("create", "duplicate")
        for a in facts["actions"]
    )
    has_any_cmd_revert = any(a[0] == "cmd" for a in reverts)
    r_appx = {str(a[2]) for a in reverts if a[0] == "appx" and len(a) >= 3}
    r_file = {(str(a[2]).lower()) for a in reverts
              if a[0] == "file" and len(a) >= 3}
    has_netadp_revert = any(a[0] == "netadp" for a in reverts)
    has_process_revert = any(a[0] == "process" for a in reverts)
    has_restart_revert = any(a[0] == "restart" for a in reverts)

    covered = 0
    for action in facts["state_changing"]:
        kind = action[0]
        if kind in INFO_KINDS:
            continue
        if kind in ("reg", "regall"):
            pair = (str(action[1]).upper(), str(action[2]))
            value = (str(action[1]).upper(), str(action[2]),
                     str(action[3]).lower()) if len(action) >= 4 else None
            if value in r_reg_values or pair in r_reg_paths:
                covered += 1
        elif kind == "regkeydel":
            if (str(action[1]).upper(), str(action[2])) in r_reg_paths:
                covered += 1
        elif kind in ("regdel", "regdelall", "inidel"):
            covered += 1
        elif kind in ("svc", "svcstart", "svcstop"):
            if str(action[1]).lower() in r_services:
                covered += 1
        elif kind == "sc":
            if len(action) >= 3 and str(action[2]).lower() in r_services:
                covered += 1
        elif kind == "power":
            if str(action[1]) in r_power or (creates_scheme and deletes_own_scheme):
                covered += 1
        elif kind == "powerscheme":
            if r_scheme:
                covered += 1
        elif kind == "ini":
            key = (str(action[1]).lower(), str(action[2]).lower(), str(action[3]).lower())
            if key in r_ini:
                covered += 1
        elif kind == "file":
            if str(action[2]).lower() in r_file:
                covered += 1
        elif kind == "sched":
            if len(action) >= 3 and str(action[2]) in r_tasks:
                covered += 1
        elif kind == "appx":
            if len(action) >= 3 and str(action[2]) in r_appx:
                covered += 1
        elif kind == "cmd":
            if has_any_cmd_revert:
                covered += 1
        elif kind == "netadp":
            if has_netadp_revert:
                covered += 1
        elif kind == "process":
            if has_process_revert:
                covered += 1
        elif kind == "restart":
            if has_restart_revert:
                covered += 1
        elif kind == "mkdir":
            covered += 1  # directory creation is inherently additive/harmless
    return covered, facts["mutating_count"]


def assess_verification(facts: dict, tweak: dict) -> tuple[bool, str]:
    """Whether the implementation was actually inspected and cleared.

    Strict on purpose. A tweak is only ``VERIFIED`` when every one of these
    holds; each failure names the specific reason, so an unverified tweak is
    actionable rather than a shrug. Unverified is not a verdict on the tweak -
    it means this audit could not prove it safe, which is different.
    """
    if facts["guidance_only"]:
        return True, "Informational only: no system state is modified."
    if facts["read_only"]:
        return True, str(tweak.get("read_only_reason") or (
            "Read-only diagnostic: observes system state and cannot change it, "
            "so no revert path is required."
        ))
    if facts["transient_only"]:
        return True, str(tweak.get("transient_reason") or (
            "Transient / self-healing operation: the effect is not a persisted "
            "configuration (a maintenance tool, a restart, or state Windows "
            "regenerates itself), so no revert path is required."
        ))

    status = str(tweak.get("status") or "")
    if status == "INVALID":
        return False, "Marked INVALID in the validation database."
    if status == "OUTDATED":
        return False, "Marked OUTDATED in the validation database."
    if status == "PLACEBO":
        return False, "Marked PLACEBO: no measurable effect."
    if status == "DUPLICATE":
        return False, "Marked DUPLICATE of another tweak."
    if status == "CONFLICTING" or (tweak.get("conflicts") or []):
        conflicts = tweak.get("conflicts") or []
        withs = ", ".join(sorted({str(c.get("with")) for c in conflicts if c.get("with")}))
        return False, (
            f"Conflicts with {withs or 'another tweak'} writing the same target; "
            "applying both would fight over one value."
        )

    covered, total = _revert_coverage(facts)
    if total and covered < total:
        return False, (
            f"Not fully reversible: {covered}/{total} mutating action(s) have no revert path."
        )

    unknown = facts["unknown_exes"]
    if unknown:
        return False, (
            "Invokes an executable outside the audited set: "
            + ", ".join(unknown) + "."
        )

    evidence = str(tweak.get("evidence") or "UNKNOWN").upper()
    if evidence == "UNKNOWN":
        return False, (
            "No evidence recorded: no verification note, benchmark or vendor "
            "documentation backs this implementation."
        )
    if evidence == "LOW":
        return False, "Evidence strength recorded as LOW: weakly substantiated benefit."

    if facts["hardcoded_drive"] and facts["flags"].get("filesystem_servicing"):
        return False, (
            "Filesystem tool targets a hard-coded drive letter, which is wrong "
            "on a multi-partition system."
        )

    if facts["flags"].get("gaming_cheat_adjacent"):
        return False, (
            "Input-translation/aim-assist behaviour; deliberately excluded from "
            "every paid tier."
        )

    return True, (
        f"Implementation inspected: {total} mutating action(s) fully reversible, "
        f"hives={sorted(facts['hives']) or ['none']}, evidence={evidence}."
    )


def audit_tweak(tweak: dict) -> dict:
    """Full audit record for one tweak."""
    facts = extract_implementation(tweak)
    tier, tier_reason = classify_tier(facts, tweak)
    verified, verify_reason = assess_verification(facts, tweak)
    covered, total = _revert_coverage(facts)

    status = str(tweak.get("status") or "UNKNOWN")
    risk = str(tweak.get("risk") or "unknown")
    module = str(tweak.get("module") or "")

    # Disposition: severe conditions win over the verified/unverified split.
    # DANGEROUS is reserved for danger visible in the implementation, not for a
    # high `risk` label: in this database `risk` reads "safe" on all 16 NVIDIA,
    # 17 AMD and 15 delay-destroyer tweaks, so it cannot carry that judgement.
    # The `risk` level is reported as its own column instead.
    if status == "PLACEBO":
        disposition = UNSUPPORTED
    elif status == "INVALID":
        disposition = UNSUPPORTED
    elif facts["unknown_exes"]:
        disposition = UNSUPPORTED
    elif status == "OUTDATED":
        disposition = OBSOLETE
    elif status == "DUPLICATE":
        disposition = DUPLICATE
    elif facts["flags"].get("gaming_cheat_adjacent"):
        disposition = DANGEROUS
    elif facts["hardcoded_drive"] and facts["flags"].get("filesystem_servicing"):
        disposition = DANGEROUS
    elif total and covered < total:
        # Applies a change it cannot undo.
        disposition = BROKEN
    elif str(tweak.get("recommended") or "") == "experimental" or module == "experimental":
        disposition = EXPERIMENTAL
    elif verified:
        disposition = VERIFIED
    else:
        disposition = UNVERIFIED

    hw = []
    when = facts["when"]
    if "gpu" in when:
        hw.append("GPU:" + "/".join(str(x) for x in when["gpu"]))
    for key in ("gpu_type", "cpu_vendor", "cpu_family", "intel_cpu", "hdd", "ssd",
                "nvme", "ram_gb", "ram_channels", "audio_realtek",
                "audio_bluetooth", "laptop"):
        if key in when:
            hw.append(f"{key}:{when[key]}")
    if facts["flags"].get("gpu_vendor_specific") and not hw:
        hw.append("vendor-specific GPU")
    if not hw:
        hw.append("Any compatible PC")

    return {
        "id": tweak.get("id"),
        "name": tweak.get("name"),
        "category": tweak.get("category"),
        "module": module,
        "tier": tier,
        "tier_reason": tier_reason,
        "verified": verified,
        "disposition": disposition,
        "verify_reason": verify_reason,
        "hardware": "; ".join(hw),
        "windows": str(tweak.get("win") or ""),
        "risk": risk,
        "admin": bool(tweak.get("admin")),
        "confirm": bool(tweak.get("confirm")),
        "reboot": facts["reboot"],
        "reversible": bool(total) and covered >= total,
        "revert_coverage": f"{covered}/{total}",
        "evidence": str(tweak.get("evidence") or "UNKNOWN"),
        "status": status,
        "kinds": sorted(facts["kind_set"]),
        "exes": sorted(facts["exes"]),
        "services": facts["services"],
        "guidance_only": facts["guidance_only"],
        "transient_only": facts["transient_only"],
        "hw_gates": facts["hw_gates"],
    }


def summarize(records: list[dict]) -> dict:
    """Aggregate counts for the audit report. Counts are reported as found."""
    tier_counts = Counter(r["tier"] for r in records)
    disp_counts = Counter(r["disposition"] for r in records)

    # Verified-only view per tier: what a subscriber can actually trust.
    verified_by_tier = Counter(
        r["tier"] for r in records if r["disposition"] == VERIFIED
    )
    return {
        "total": len(records),
        "by_tier": {t: tier_counts.get(t, 0) for t in (FOUNDATION, PERFORMANCE, MAXIMUM)},
        "by_disposition": {d: disp_counts.get(d, 0) for d in DISPOSITIONS},
        "verified_by_tier": {
            t: verified_by_tier.get(t, 0) for t in (FOUNDATION, PERFORMANCE, MAXIMUM)
        },
        "reversible": sum(1 for r in records if r["reversible"]),
        "requires_admin": sum(1 for r in records if r["admin"]),
        "requires_reboot": sum(1 for r in records if r["reboot"]),
        "guidance_only": sum(1 for r in records if r["guidance_only"]),
    }
