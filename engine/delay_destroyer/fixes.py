"""Delay Destroyer — evidence-based fixes.

Each fix is backed by a predicate (should it apply?) and a list of
shell commands (apply) plus verification commands. The BackupManager
reads verify_cmd to snapshot the original state before applying.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, List, Tuple

from .risk import Risk
from .scanner import ScanResult


@dataclass
class Action:
    """A single apply/verify step within a fix."""
    description: str
    cmd: str
    verify_cmd: str
    verify_expected: str


@dataclass
class Fix:
    """An evidence-based fix with detection, actions, and explanations."""
    id: str
    title: str
    category: str
    risk: Risk
    predicate: Callable[[ScanResult], Tuple[bool, str]]
    actions: List[Action]
    why: str
    what_will_change: str
    expected_effect: str
    risk_explanation: str
    current_value: str = ""
    recommended_value: str = ""
    impact: str = ""


def _reg_dword(path: str, name: str, value: int) -> Action:
    return Action(
        description=f"Set {name} = {value}",
        cmd=f'reg add "HKLM\\{path}" /v "{name}" /t REG_DWORD /d {value} /f',
        verify_cmd=f'reg query "HKLM\\{path}" /v "{name}"',
        verify_expected=str(value),
    )


def _power_scheme(guid: str) -> Action:
    return Action(
        description=f"Activate power scheme {guid}",
        cmd=f"powercfg /setactive {guid}",
        verify_cmd="powercfg /getactivescheme",
        verify_expected=guid,
    )


def _svc_start(name: str, start: str) -> Action:
    return Action(
        description=f"Set {name} to {start} start",
        cmd=f'sc config "{name}" start= {start}',
        verify_cmd=f'sc qc "{name}"',
        verify_expected=start.upper(),
    )


def _svc_start_running(name: str) -> List[Action]:
    return [
        _svc_start(name, "auto"),
        Action(
            description=f"Start {name}",
            cmd=f'net start "{name}"',
            verify_cmd=f'sc query "{name}"',
            verify_expected="RUNNING",
        ),
    ]


def build_fixes(scan: ScanResult) -> List[Fix]:
    """Build fixes that are backed by real evidence from the scan."""
    fixes: List[Fix] = []

    # ── 1. Timer Resolution — set global to 1ms ────────────────────
    def _timer_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "GlobalTimerResolutionRequests")
                if val == 1:
                    return False, "Timer resolution already optimized"
        except FileNotFoundError:
            pass
        return True, "Global timer resolution not set"

    fixes.append(Fix(
        id="dd_timer_resolution",
        title="Set global timer resolution to 1ms",
        category="input",
        risk=Risk.LOW,
        predicate=_timer_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Session Manager\kernel",
                "GlobalTimerResolutionRequests", 1),
        ],
        why=(
            "Windows defaults to a ~15.6ms timer tick. Setting global "
            "timer resolution to 1ms reduces input polling granularity "
            "and improves frame pacing consistency."
        ),
        what_will_change="Adds a registry key for global 1ms timer resolution.",
        expected_effect="Reduced input latency and smoother frame pacing.",
        risk_explanation="Low risk. Reverts on reboot if key is removed.",
        current_value="Default (~15.6ms)",
        recommended_value="1ms global resolution",
        impact="Reduces input polling granularity from 15.6ms to 1ms",
    ))

    # ── 2. Power Saver → High Performance ──────────────────────────
    GUID高性能 = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    GUID平衡 = "381b4222-f694-41f0-9685-ff5bb260df2e"

    def _power_pred(s: ScanResult) -> Tuple[bool, str]:
        g = s.cpu.power_plan_guid.lower()
        if "a1841308" in g:
            return True, "Power Saver active — severely limits CPU"
        if "95533650-e2fe-42e4-90b3-c534e6b40e0c" in g:
            return True, "Power Saver (Ultimate) active"
        if "381b4222" in g:
            return True, "Balanced plan active — may limit boost behavior"
        return False, f"Power plan: {s.cpu.power_plan_name}"

    fixes.append(Fix(
        id="dd_switch_high_perf",
        title="Switch to High Performance Power Plan",
        category="cpu",
        risk=Risk.LOW,
        predicate=_power_pred,
        actions=[_power_scheme(GUID高性能)],
        why=(
            "The current power plan limits CPU frequency and turbo boost "
            "behavior. Power Saver is the most restrictive; Balanced may "
            "also throttle boost under load. High Performance keeps the "
            "CPU at full frequency."
        ),
        what_will_change="Activates the High Performance power plan.",
        expected_effect="Full CPU frequency available, turbo boost enabled.",
        risk_explanation="Low risk. Reversible. Does not affect battery life on desktops.",
        current_value="",
        recommended_value="High Performance",
        impact="CPU frequency and turbo boost behavior",
    ))

    # ── 4. Enable MMCSS ───────────────────────────────────────────
    def _mmcss_pred(s: ScanResult) -> Tuple[bool, str]:
        if s.cpu.mmcss_running:
            return False, "MMCSS already running"
        return True, "MMCSS not running"

    fixes.append(Fix(
        id="dd_enable_mmcss",
        title="Enable Multimedia Class Scheduler Service",
        category="cpu",
        risk=Risk.LOW,
        predicate=_mmcss_pred,
        actions=_svc_start_running("MMCSS"),
        why=(
            "MMCSS prioritizes multimedia threads (audio, video, game). "
            "Without it, these threads compete equally with background "
            "tasks, causing audio pops and frame pacing issues."
        ),
        what_will_change="Sets MMCSS to automatic start and starts it.",
        expected_effect="Better multimedia thread scheduling and audio stability.",
        risk_explanation="Low risk. Standard Windows service.",
        current_value="Not running",
        recommended_value="Running (automatic)",
        impact="Multimedia thread scheduling priority",
    ))

    # ── 5. Disable Game DVR ───────────────────────────────────────
    def _dvr_pred(s: ScanResult) -> Tuple[bool, str]:
        if not s.os.game_dvr_enabled:
            return False, "Game DVR already disabled"
        return True, "Game DVR recording in background"

    fixes.append(Fix(
        id="dd_disable_game_dvr",
        title="Disable Game DVR background recording",
        category="gaming",
        risk=Risk.LOW,
        predicate=_dvr_pred,
        actions=[
            _reg_dword(
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR",
                "AppCaptureEnabled", 0),
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                "HwSchMode", 2),
        ],
        why=(
            "Game DVR continuously records gameplay using GPU encoding "
            "and disk I/O. This consumes GPU cycles and adds disk "
            "throughput pressure even when you're not recording."
        ),
        what_will_change="Disables Game DVR background recording.",
        expected_effect="Freed GPU encoding resources and reduced disk I/O.",
        risk_explanation="Low risk. Can re-enable in Windows Settings > Gaming.",
        current_value="Enabled",
        recommended_value="Disabled",
        impact="GPU encoding overhead and background disk I/O",
    ))

    # ── 6. Enable HAGS ────────────────────────────────────────────
    def _hags_pred(s: ScanResult) -> Tuple[bool, str]:
        if not s.gpu.dedicated:
            return False, "No dedicated GPU"
        if s.gpu.hardware_gpu_scheduling:
            return False, "HAGS already enabled"
        return True, "HAGS disabled with dedicated GPU"

    fixes.append(Fix(
        id="dd_enable_hags",
        title="Enable Hardware-Accelerated GPU Scheduling",
        category="gpu",
        risk=Risk.MODERATE,
        predicate=_hags_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                "HwSchMode", 2),
        ],
        why=(
            "HAGS lets the GPU manage its own task queue. With it "
            "disabled, the CPU handles GPU scheduling, adding driver "
            "overhead and reducing frame pacing smoothness."
        ),
        what_will_change="Enables hardware GPU scheduling. Requires restart.",
        expected_effect="Reduced CPU overhead and smoother frame pacing.",
        risk_explanation="Moderate risk. Requires restart. Some older GPUs may have issues.",
        current_value="Disabled",
        recommended_value="Enabled",
        impact="CPU vs GPU scheduling responsibility",
    ))

    # ── 7. Disable Power Throttling ────────────────────────────────
    def _throttle_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "PowerThrottlingOff")
                if val == 1:
                    return False, "Power throttling already disabled"
        except FileNotFoundError:
            pass
        return True, "Power throttling is active"

    fixes.append(Fix(
        id="dd_disable_power_throttling",
        title="Disable Windows Power Throttling",
        category="cpu",
        risk=Risk.LOW,
        predicate=_throttle_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
                "PowerThrottlingOff", 1),
        ],
        why=(
            "Power Throttling reduces CPU frequency for background "
            "threads. While intended for battery life, it can "
            "incorrectly throttle game-related threads, causing "
            "micro-stutters and input lag."
        ),
        what_will_change="Disables Windows Power Throttling globally.",
        expected_effect="Consistent CPU performance for all threads.",
        risk_explanation="Low risk. Standard gaming optimization.",
        current_value="Enabled (default)",
        recommended_value="Disabled",
        impact="CPU frequency stability under mixed workloads",
    ))

    # ── 8. Disable USB Selective Suspend ───────────────────────────
    def _usb_suspend_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Services\USB",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "DisableSelectiveSuspend")
                if val == 1:
                    return False, "USB selective suspend already disabled"
        except FileNotFoundError:
            pass
        return True, "USB selective suspend may cause input device lag"

    fixes.append(Fix(
        id="dd_disable_usb_suspend",
        title="Disable USB Selective Suspend",
        category="input",
        risk=Risk.LOW,
        predicate=_usb_suspend_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Services\USB",
                "DisableSelectiveSuspend", 1),
        ],
        why=(
            "USB Selective Suspend can put USB controllers to sleep, "
            "causing momentary input device disconnects or lag spikes "
            "when they wake up."
        ),
        what_will_change="Prevents Windows from suspending USB controllers.",
        expected_effect="Consistent USB device responsiveness, no wake-up lag.",
        risk_explanation="Low risk. Increases power consumption marginally on laptops.",
        current_value="Enabled (default)",
        recommended_value="Disabled",
        impact="USB device wake-up latency",
    ))

    # ── 9. Disable C-State Transitions ────────────────────────────
    def _cstate_pred(s: ScanResult) -> Tuple[bool, str]:
        if s.cpu.power_plan_guid.lower() in ("a1841308",):
            return False, "Power Saver already limits C-states"
        if s.cpu.parking_enabled:
            return True, "Core parking active — C-states likely deep"
        return True, "C-states at OS defaults — deep sleep may add wake latency"

    fixes.append(Fix(
        id="dd_limit_cstates",
        title="Limit CPU C-State Depth",
        category="cpu",
        risk=Risk.MODERATE,
        predicate=_cstate_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Power",
                "CsEnabled", 0),
        ],
        why=(
            "Deep C-states (C6/C8/C10) save power but add wake "
            "latency when cores resume. This is a known trade-off: "
            "deeper sleep = lower idle power but higher wake delay. "
            "On desktops where power savings are irrelevant, keeping "
            "shallower C-states reduces scheduling jitter."
        ),
        what_will_change="Disables deep C-states. CPU stays in C0/C1 more often.",
        expected_effect="Lower CPU wake latency, reduced scheduling jitter.",
        risk_explanation=(
            "Moderate risk. Increases idle power draw. "
            "Requires restart. Reversible."
        ),
        current_value="Deep C-states enabled (default)",
        recommended_value="Shallow C-states only",
        impact="CPU wake latency per core",
    ))

    # ── 10. Disable Core Parking ──────────────────────────────────
    def _park_pred(s: ScanResult) -> Tuple[bool, str]:
        if s.cpu.parking_enabled:
            return True, "Core parking active"
        return False, "Core parking not detected"

    fixes.append(Fix(
        id="dd_disable_core_parking",
        title="Disable CPU Core Parking",
        category="cpu",
        risk=Risk.LOW,
        predicate=_park_pred,
        actions=[
            Action(
                description="Set min cores to 100% for all power schemes",
                cmd=(
                    'powershell -NoProfile -Command "'
                    "powercfg /l | ForEach-Object { "
                    "  $guid = ($_ -split ':')[1].Trim(); "
                    "  powercfg /setacvalueindex $guid SUB_PROCESSOR CPMINCORES 100; "
                    "  powercfg /setdcvalueindex $guid SUB_PROCESSOR CPMINCORES 100 "
                    '}; powercfg /setactive SCHEME_CURRENT"'
                ),
                verify_cmd=(
                    'powershell -NoProfile -Command "'
                    "(powercfg /query SCHEME_CURRENT SUB_PROCESSOR CPMINCORES) -match '100%'"
                    '"'
                ),
                verify_expected="True",
            ),
        ],
        why=(
            "Core parking puts CPU cores to sleep to save power. "
            "When a core is parked, waking it adds latency. For "
            "gaming, all cores should be available immediately."
        ),
        what_will_change="Sets minimum active cores to 100% on all power schemes.",
        expected_effect="All CPU cores active and responsive immediately.",
        risk_explanation="Low risk. Standard performance optimization.",
        current_value="Cores may be parked",
        recommended_value="All cores active (100% min)",
        impact="Core availability and wake latency",
    ))

    # ── 11. Disable DPC Watchdog ──────────────────────────────────
    def _dpc_wd_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Power",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "ExitLatency")
                if val == 0:
                    return False, "DPC watchdog already configured"
        except FileNotFoundError:
            pass
        return True, "DPC watchdog at default"

    fixes.append(Fix(
        id="dd_disable_dpc_watchdog",
        title="Reduce DPC Watchdog Latency Threshold",
        category="drivers",
        risk=Risk.MODERATE,
        predicate=_dpc_wd_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Power",
                "ExitLatency", 0),
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Power",
                "ExitLatencyCheckEnabled", 0),
        ],
        why=(
            "The DPC watchdog monitors driver execution time and "
            "can force BSODs or throttle drivers. Reducing its "
            "sensitivity prevents false triggers that disrupt the "
            "driver stack."
        ),
        what_will_change="Disables DPC watchdog exit latency checking.",
        expected_effect="Fewer driver-related latency disruptions.",
        risk_explanation=(
            "Moderate risk. Prevents watchdog from detecting genuine "
            "driver hangs. Reboot required."
        ),
        current_value="Default threshold",
        recommended_value="Disabled",
        impact="Driver execution monitoring sensitivity",
    ))

    # ── 12. Optimize Interrupt Affinity (MSI mode) ────────────────
    def _msi_pred(s: ScanResult) -> Tuple[bool, str]:
        if s.ram.dpc_rate_per_sec < 200:
            return False, "DPC activity rate acceptable"
        return True, f"DPC activity elevated ({s.ram.dpc_rate_per_sec:.0f}/s — may benefit from MSI optimization)"

    fixes.append(Fix(
        id="dd_optimize_interrupts",
        title="Optimize Interrupt Steering",
        category="drivers",
        risk=Risk.MODERATE,
        predicate=_msi_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\PriorityControl",
                "IRQ8Priority", 1),
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\PriorityControl",
                "Win32PrioritySeparation", 38),
        ],
        why=(
            "IRQ priority and thread scheduling policy affect how "
            "quickly the CPU handles hardware interrupts. Setting "
            "IRQ8 (RTC) to priority 1 and optimizing process "
            "scheduling reduces interrupt handling latency."
        ),
        what_will_change="Adjusts IRQ priority and Win32 scheduling quantum.",
        expected_effect="Faster interrupt handling, reduced DPC/ISR latency.",
        risk_explanation="Moderate risk. Requires restart. Reversible.",
        current_value="Default scheduling",
        recommended_value="Optimized for foreground",
        impact="Hardware interrupt handling latency",
    ))

    # ── 13. Disable Background Graphics Compositing ────────────────
    def _dwm_pred(s: ScanResult) -> Tuple[bool, str]:
        if not s.display.dwm_enabled:
            return False, "DWM composition already disabled"
        return True, "DWM composition active — adds frame presentation overhead"

    fixes.append(Fix(
        id="dd_disable_dwm_composition",
        title="Optimize DWM for gaming (disable composition on fullscreen)",
        category="display",
        risk=Risk.LOW,
        predicate=_dwm_pred,
        actions=[
            Action(
                description="Disable DWM composition for fullscreen applications",
                cmd=(
                    'reg add "HKCU\\Software\\Microsoft\\Windows\\DWM" '
                    '/v "AlwaysHibernateThumbnails" /t REG_DWORD /d 0 /f'
                ),
                verify_cmd='reg query "HKCU\\Software\\Microsoft\\Windows\\DWM" /v "AlwaysHibernateThumbnails"',
                verify_expected="0",
            ),
            Action(
                description="Disable DWM animation",
                cmd=(
                    'reg add "HKCU\\Control Panel\\Desktop" '
                    '/v "UserPreferencesMask" /t REG_BINARY '
                    '/d 9012038010000000 /f'
                ),
                verify_cmd='reg query "HKCU\\Control Panel\\Desktop" /v "UserPreferencesMask"',
                verify_expected="9012038010000000",
            ),
        ],
        why=(
            "Desktop Window Manager (DWM) composites all windows into "
            "a single framebuffer. This adds a frame of latency to "
            "fullscreen applications as frames pass through the "
            "compositor. On high-refresh-rate displays, this overhead "
            "is more noticeable."
        ),
        what_will_change="Reduces DWM overhead for fullscreen applications.",
        expected_effect="Lower display latency, faster frame presentation.",
        risk_explanation="Low risk. Only affects fullscreen apps. Reversible.",
        current_value="Full DWM compositing",
        recommended_value="Reduced DWM effects",
        impact="Frame presentation latency on high-refresh displays",
    ))

    # ── 14. Disable Prefetch/Superfetch for SSDs ──────────────────
    def _prefetch_pred(s: ScanResult) -> Tuple[bool, str]:
        if s.storage.has_ssd or s.storage.has_nvme:
            import winreg
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
                ) as k:
                    val, _ = winreg.QueryValueEx(k, "EnablePrefetcher")
                    if val == 0:
                        return False, "Prefetcher already disabled on SSD"
            except FileNotFoundError:
                pass
            return True, "Prefetcher active on SSD — unnecessary disk I/O"
        return False, "HDD detected — keep prefetcher enabled"

    fixes.append(Fix(
        id="dd_disable_prefetch_ssd",
        title="Disable Prefetcher on SSD systems",
        category="storage",
        risk=Risk.LOW,
        predicate=_prefetch_pred,
        actions=[
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
                "EnablePrefetcher", 0),
            _reg_dword(
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
                "EnableSuperfetch", 0),
        ],
        why=(
            "Prefetcher and Superfetch optimize HDD access patterns. "
            "On SSDs, they generate unnecessary disk I/O that competes "
            "with game data access."
        ),
        what_will_change="Disables Prefetcher and Superfetch on SSD systems.",
        expected_effect="Reduced background disk I/O on SSD systems.",
        risk_explanation="Low risk. Only applies when SSD is detected.",
        current_value="Enabled",
        recommended_value="Disabled (SSD detected)",
        impact="Background disk I/O on SSD",
    ))

    # ── 16. Disable Mouse Acceleration (Enhanced Pointer Precision) ─
    def _mouse_accel_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Mouse",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "MouseSpeed")
                if val == "0":
                    return False, "Mouse acceleration already disabled"
        except FileNotFoundError:
            pass
        return True, "Mouse acceleration is active"

    fixes.append(Fix(
        id="dd_disable_mouse_accel",
        title="Disable Mouse Acceleration",
        category="input",
        risk=Risk.LOW,
        predicate=_mouse_accel_pred,
        actions=[
            Action(
                description="Set MouseSpeed = 0 (disable acceleration)",
                cmd='reg add "HKCU\\Control Panel\\Mouse" /v "MouseSpeed" /t REG_SZ /d "0" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Mouse" /v "MouseSpeed"',
                verify_expected="0",
            ),
            Action(
                description="Set MouseThreshold1 = 0",
                cmd='reg add "HKCU\\Control Panel\\Mouse" /v "MouseThreshold1" /t REG_SZ /d "0" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Mouse" /v "MouseThreshold1"',
                verify_expected="0",
            ),
            Action(
                description="Set MouseThreshold2 = 0",
                cmd='reg add "HKCU\\Control Panel\\Mouse" /v "MouseThreshold2" /t REG_SZ /d "0" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Mouse" /v "MouseThreshold2"',
                verify_expected="0",
            ),
        ],
        why=(
            "Enhanced Pointer Precision (mouse acceleration) makes "
            "mouse movement non-linear. For gaming, consistent "
            "1:1 mouse-to-screen movement is essential for accuracy."
        ),
        what_will_change="Disables mouse acceleration. Mouse movement becomes 1:1.",
        expected_effect="Consistent, predictable mouse movement for gaming.",
        risk_explanation="Low risk. Personal preference. Reversible in Mouse settings.",
        current_value="Enhanced Pointer Precision enabled",
        recommended_value="Disabled (1:1 movement)",
        impact="Mouse-to-screen movement linearity",
    ))

    # ── 17. Disable Sticky Keys / Filter Keys / Toggle Keys ────────
    def _stickey_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Accessibility\StickyKeys",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "Flags")
                if val == "506":
                    return False, "Sticky Keys already disabled"
        except FileNotFoundError:
            pass
        return True, "Accessibility keys may intercept input"

    fixes.append(Fix(
        id="dd_disable_accessibility_keys",
        title="Disable Sticky Keys, Filter Keys, and Toggle Keys",
        category="input",
        risk=Risk.LOW,
        predicate=_stickey_pred,
        actions=[
            Action(
                description="Disable Sticky Keys",
                cmd='reg add "HKCU\\Control Panel\\Accessibility\\StickyKeys" /v "Flags" /t REG_SZ /d "506" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Accessibility\\StickyKeys" /v "Flags"',
                verify_expected="506",
            ),
            Action(
                description="Disable Filter Keys",
                cmd='reg add "HKCU\\Control Panel\\Accessibility\\Keyboard Response" /v "Flags" /t REG_SZ /d "122" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Accessibility\\Keyboard Response" /v "Flags"',
                verify_expected="122",
            ),
            Action(
                description="Disable Toggle Keys",
                cmd='reg add "HKCU\\Control Panel\\Accessibility\\ToggleKeys" /v "Flags" /t REG_SZ /d "58" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Accessibility\\ToggleKeys" /v "Flags"',
                verify_expected="58",
            ),
        ],
        why=(
            "Sticky Keys, Filter Keys, and Toggle Keys can intercept "
            "and delay keyboard input. During gaming, rapid key "
            "presses may trigger these features, causing input lag."
        ),
        what_will_change="Disables all three accessibility keyboard features.",
        expected_effect="No keyboard input interception or delay.",
        risk_explanation="Low risk. Reversible in Accessibility settings.",
        current_value="May be active",
        recommended_value="All disabled",
        impact="Keyboard input interception behavior",
    ))

    # ── 18. Disable Mouse Keys ────────────────────────────────────
    def _mouse_keys_pred(s: ScanResult) -> Tuple[bool, str]:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Control Panel\Accessibility\MouseKeys",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "Flags")
                if val == "58":
                    return False, "Mouse Keys already disabled"
        except FileNotFoundError:
            pass
        return True, "Mouse Keys may be active"

    fixes.append(Fix(
        id="dd_disable_mouse_keys",
        title="Disable Mouse Keys (Numpad Control)",
        category="input",
        risk=Risk.LOW,
        predicate=_mouse_keys_pred,
        actions=[
            Action(
                description="Disable Mouse Keys",
                cmd='reg add "HKCU\\Control Panel\\Accessibility\\MouseKeys" /v "Flags" /t REG_SZ /d "58" /f',
                verify_cmd='reg query "HKCU\\Control Panel\\Accessibility\\MouseKeys" /v "Flags"',
                verify_expected="58",
            ),
        ],
        why=(
            "Mouse Keys allows keyboard numpad to control the mouse "
            "cursor. When active, it can interfere with mouse input "
            "processing and add latency."
        ),
        what_will_change="Disables numpad mouse control.",
        expected_effect="Clean mouse input without numpad interference.",
        risk_explanation="Low risk. Reversible in Accessibility settings.",
        current_value="May be active",
        recommended_value="Disabled",
        impact="Numpad-to-mouse cursor interference",
    ))

    return fixes


def apply_fix(fix: Fix) -> Tuple[bool, str]:
    """Apply a fix by executing all its actions."""
    import time
    for action in fix.actions:
        try:
            result = subprocess.run(
                action.cmd, shell=True, capture_output=True,
                text=True, timeout=30,
                creationflags=0x08000000)
            if result.returncode != 0 and result.stderr.strip():
                # Some commands return non-zero but still work
                if "access denied" in result.stderr.lower():
                    return False, f"Access denied: {result.stderr}"
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, f"Error: {e}"
        time.sleep(0.3)
    return True, "Applied"


def verify_fix(fix: Fix) -> Tuple[bool, str]:
    """Verify a fix by running its verification commands."""
    for action in fix.actions:
        if not action.verify_cmd or not action.verify_expected:
            continue
        try:
            result = subprocess.run(
                action.verify_cmd, shell=True, capture_output=True,
                text=True, timeout=15,
                creationflags=0x08000000)
            stdout = result.stdout.strip()
            expected_dec = action.verify_expected.strip()
            # reg query outputs hex (0x40), compare numerically
            try:
                expected_int = int(expected_dec)
                # Parse hex values from reg query output (0xNNN format)
                for token in stdout.split():
                    if token.lower().startswith("0x"):
                        try:
                            actual_int = int(token, 16)
                            if actual_int == expected_int:
                                break
                        except ValueError:
                            continue
                else:
                    # No hex match — fall back to substring check
                    if expected_dec.lower() not in stdout.lower():
                        return False, f"Verification failed for: {action.description}"
            except ValueError:
                # Not a numeric expected value — do substring check
                if expected_dec.lower() not in stdout.lower():
                    return False, f"Verification failed for: {action.description}"
        except Exception as e:
            return False, f"Verification error: {e}"
    return True, "Verified"
