"""Main orchestrator — runs the full Delay Destroyer pipeline.

20-stage delay investigation:
  01. Initializing Diagnostic Engine
  02. Building Performance Baseline
  03. CPU Power & Responsiveness
  04. Memory Pressure & Swap Impact
  05. DPC/ISR Latency Sources
  06. Driver Latency & Stability
  07. Input & USB/HID Stack
  08. Storage Latency & Queue Depth
  09. Graphics Pipeline & DWM
  10. Audio Stack Latency
  11. Network Stack Latency
  12. Real-time Network Probing
  13. Gaming Environment Analysis
  14. Background Process Contention
  15. Windows Power & Responsiveness
  16. Cross-Referencing Delay Sources
  17. Identifying Delay Bottlenecks
  18. Verifying Delay Fixes
  19. Calculating Health Scores
  20. Generating Delay Diagnosis
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from rexlog import logger
from engine.delay_destroyer.scanner import SystemScanner, ScanResult, _is_admin
from engine.delay_destroyer.baseline import (
    Baseline, measure_baseline, capture_snapshot,
    capture_network_snapshot, capture_dpc_snapshot,
)
from engine.delay_destroyer.diagnoser import Diagnoser, Finding
from engine.delay_destroyer.correlator import Correlator, CorrelatedFinding
from engine.delay_destroyer.fixes import Fix, build_fixes
from engine.delay_destroyer.executor import Executor, ExecutionPlan
from engine.delay_destroyer.reporter import Reporter, Report
from engine.delay_destroyer.risk import Risk
from engine.delay_destroyer.backup import BackupManager, BackupSession
from engine.delay_destroyer.network_measure import NetworkMeasurement, measure_network
from engine.delay_destroyer.gaming import GamingAnalysis, analyze_gaming_environment
from engine.delay_destroyer.scoring import DelayScores, calculate_scores


SCAN_STAGES = [
    {"id": "init",        "num": "01", "name": "INITIALIZING DIAGNOSTIC ENGINE", "component": None},
    {"id": "baseline",    "num": "02", "name": "BUILDING PERFORMANCE BASELINE",  "component": None},
    {"id": "cpu",         "num": "03", "name": "CPU POWER & RESPONSIVENESS",     "component": "cpu"},
    {"id": "memory",      "num": "04", "name": "MEMORY PRESSURE & SWAP IMPACT",  "component": "ram"},
    {"id": "dpc",         "num": "05", "name": "DPC/ISR LATENCY SOURCES",        "component": None},
    {"id": "drivers",     "num": "06", "name": "DRIVER LATENCY & STABILITY",     "component": None},
    {"id": "input",       "num": "07", "name": "INPUT & USB/HID STACK",          "component": "input"},
    {"id": "storage",     "num": "08", "name": "STORAGE LATENCY & QUEUE DEPTH",  "component": "storage"},
    {"id": "graphics",    "num": "09", "name": "GRAPHICS PIPELINE & DWM",        "component": "gpu"},
    {"id": "audio",       "num": "10", "name": "AUDIO STACK LATENCY",            "component": "audio"},
    {"id": "network",     "num": "11", "name": "NETWORK STACK LATENCY",          "component": "network"},
    {"id": "network_meas","num": "12", "name": "REAL-TIME NETWORK PROBING",      "component": None},
    {"id": "gaming",      "num": "13", "name": "GAMING ENVIRONMENT ANALYSIS",    "component": None},
    {"id": "background",  "num": "14", "name": "BACKGROUND PROCESS CONTENTION",  "component": None},
    {"id": "windows",     "num": "15", "name": "WINDOWS POWER & RESPONSIVENESS", "component": "display"},
    {"id": "correlation", "num": "16", "name": "CROSS-REFERENCING DELAY SOURCES", "component": None},
    {"id": "bottleneck",  "num": "17", "name": "IDENTIFYING DELAY BOTTLENECKS",  "component": None},
    {"id": "verify",      "num": "18", "name": "VERIFYING DELAY FIXES",          "component": None},
    {"id": "scoring",     "num": "19", "name": "CALCULATING HEALTH SCORES",      "component": None},
    {"id": "diagnosis",   "num": "20", "name": "GENERATING DELAY DIAGNOSIS",     "component": None},
]


@dataclass
class DelayDestroyerResult:
    scan: ScanResult | None = None
    baseline: Baseline | None = None
    network: NetworkMeasurement | None = None
    gaming: GamingAnalysis | None = None
    scores: DelayScores | None = None
    findings: list[Finding] = field(default_factory=list)
    correlations: list[CorrelatedFinding] = field(default_factory=list)
    fixes_selected: list[Fix] = field(default_factory=list)
    plan: ExecutionPlan | None = None
    report: Report | None = None
    backup_session: BackupSession | None = None
    total_time: float = 0.0
    cancelled: bool = False


class DelayDestroyer:

    def __init__(self):
        self.scanner = SystemScanner()
        self.diagnoser = Diagnoser()
        self.correlator = Correlator()
        self.executor = Executor()
        self.reporter = Reporter()
        self.backup_manager = BackupManager()
        self._cancelled = False
        self._progress_cb = None

    def cancel(self):
        self._cancelled = True

    def set_progress_callback(self, cb):
        """cb(stage_id, detail, pct, stage_index)"""
        self._progress_cb = cb

    def _emit(self, stage_id: str, detail: str, pct: int, stage_idx: int = 0):
        if self._progress_cb:
            self._progress_cb(stage_id, detail, pct, stage_idx)

    def run(self, apply_fixes: bool = True) -> DelayDestroyerResult:
        result = DelayDestroyerResult()
        t0 = time.monotonic()
        r = ScanResult()
        r.is_admin = _is_admin()
        r.is_laptop = self.scanner._detect_laptop()

        # Stage 01: Initialization
        self._emit("init", "Initializing diagnostic engine...", 1, 0)

        # Stage 02: Baseline
        self._emit("baseline", "Capturing performance baseline...", 3, 1)
        result.baseline = measure_baseline()

        # Stage 03: CPU
        self._emit("cpu", "Scanning CPU power and responsiveness...", 6, 2)
        try:
            self.scanner._scan_cpu(r)
        except Exception as exc:
            logger.warn(f"DD cpu scan failed: {exc}")
        self._emit("cpu", "CPU delay analysis complete", 12, 2)

        # Stage 04: Memory
        self._emit("memory", "Measuring memory pressure and swap impact...", 13, 3)
        try:
            self.scanner._scan_ram(r)
        except Exception as exc:
            logger.warn(f"DD ram scan failed: {exc}")
        self._emit("memory", "Memory delay analysis complete", 18, 3)

        # Stage 05: DPC/ISR Latency
        self._emit("dpc", "Profiling DPC/ISR latency sources...", 19, 4)
        try:
            self.scanner._scan_dpc_isr(r)
        except Exception as exc:
            logger.warn(f"DD dpc_isr scan failed: {exc}")
        self._emit("dpc", "DPC/ISR latency analysis complete", 24, 4)

        # Stage 06: Drivers
        self._emit("drivers", "Scanning driver latency and stability...", 25, 5)
        try:
            self.scanner._scan_drivers(r)
        except Exception as exc:
            logger.warn(f"DD driver scan failed: {exc}")
        self._emit("drivers", "Driver delay analysis complete", 30, 5)

        # Stage 07: Input & USB/HID
        self._emit("input", "Investigating input and USB/HID stack latency...", 31, 6)
        try:
            self.scanner._scan_input(r)
        except Exception as exc:
            logger.warn(f"DD input scan failed: {exc}")
        self._emit("input", "Input/USB delay analysis complete", 36, 6)

        # Stage 08: Storage
        self._emit("storage", "Measuring storage latency and queue depth...", 37, 7)
        try:
            self.scanner._scan_storage(r)
        except Exception as exc:
            logger.warn(f"DD storage scan failed: {exc}")
        self._emit("storage", "Storage delay analysis complete", 42, 7)

        # Stage 09: Graphics
        self._emit("graphics", "Analyzing graphics pipeline and DWM latency...", 43, 8)
        try:
            self.scanner._scan_gpu(r)
            self.scanner._scan_display(r)
        except Exception as exc:
            logger.warn(f"DD gpu/display scan failed: {exc}")
        self._emit("graphics", "Graphics delay analysis complete", 50, 8)

        # Stage 10: Audio
        self._emit("audio", "Profiling audio stack latency...", 51, 9)
        try:
            self.scanner._scan_audio(r)
        except Exception as exc:
            logger.warn(f"DD audio scan failed: {exc}")
        self._emit("audio", "Audio delay analysis complete", 55, 9)

        # Stage 11: Network
        self._emit("network", "Measuring network stack latency...", 56, 10)
        try:
            self.scanner._scan_network(r)
        except Exception as exc:
            logger.warn(f"DD network scan failed: {exc}")
        self._emit("network", "Network delay analysis complete", 58, 10)

        # Stage 12: Real-time Network Probing (ICMP ping, jitter, loss)
        self._emit("network_meas", "Probing real-time network latency...", 59, 11)
        try:
            result.network = measure_network()
            self._emit("network_meas",
                       f"Ping {result.network.internet_ping_ms:.0f}ms, "
                       f"Jitter {result.network.internet_jitter_ms:.0f}ms, "
                       f"Loss {result.network.internet_loss_pct:.0f}%",
                       62, 11)
        except Exception as exc:
            logger.warn(f"DD network measurement failed: {exc}")
            result.network = NetworkMeasurement()
            self._emit("network_meas", "Network probing unavailable", 62, 11)

        # Stage 13: Gaming Environment Analysis
        self._emit("gaming", "Analyzing gaming environment...", 63, 12)
        try:
            result.gaming = analyze_gaming_environment(r)
            self._emit("gaming",
                       f"Found {len(result.gaming.games)} games, "
                       f"{len(result.gaming.findings)} issues",
                       66, 12)
        except Exception as exc:
            logger.warn(f"DD gaming analysis failed: {exc}")
            result.gaming = GamingAnalysis()
            self._emit("gaming", "Gaming analysis unavailable", 66, 12)

        # Stage 14: Background Processes
        self._emit("background", "Auditing background process contention...", 67, 13)
        try:
            self.scanner._scan_startup(r)
            self.scanner._scan_services(r)
            self.scanner._scan_processes(r)
        except Exception as exc:
            logger.warn(f"DD background scan failed: {exc}")
        self._emit("background", "Background contention analysis complete", 70, 13)

        # Stage 15: Windows Power & Responsiveness
        self._emit("windows", "Checking Windows power and responsiveness settings...", 71, 14)
        try:
            self.scanner._scan_os(r)
            self.scanner._scan_events(r)
        except Exception as exc:
            logger.warn(f"DD windows scan failed: {exc}")
        self._emit("windows", "Windows delay analysis complete", 76, 14)

        r.scan_time = time.monotonic() - t0
        result.scan = r

        logger.info(
            f"DD scan complete in {r.scan_time:.1f}s — "
            f"admin={r.is_admin}, laptop={r.is_laptop}"
        )

        # Stage 16: Diagnosis (findings first — correlation needs them)
        if self._cancelled:
            result.cancelled = True
            return result
        self._emit("bottleneck", "Identifying delay bottlenecks...", 77, 15)
        result.findings = self.diagnoser.diagnose(r)
        self._emit("bottleneck", f"Found {len(result.findings)} delay issues", 82, 15)

        # Stage 17: Correlation (now has real findings)
        if self._cancelled:
            result.cancelled = True
            return result
        self._emit("correlation", "Cross-referencing delay sources...", 83, 16)
        result.correlations = self.correlator.correlate(r, result.findings)
        self._emit("correlation",
                   f"Identified {len(result.correlations)} cross-system delay patterns",
                   86, 16)

        # Stage 18: Verify
        self._emit("verify", "Verifying delay fixes...", 87, 17)
        all_fixes = build_fixes(r)
        selected: list[Fix] = []
        for fix in all_fixes:
            try:
                should_apply, evidence = fix.predicate(r)
            except Exception as exc:
                logger.warn(f"DD predicate {fix.id} failed: {exc}")
                continue
            if should_apply:
                selected.append(fix)
        result.fixes_selected = selected
        self._emit("verify",
                   f"Verified {len(selected)} applicable delay fixes",
                   90, 17)

        # Stage 19: Scoring
        self._emit("scoring", "Calculating system health scores...", 91, 18)
        try:
            # Capture before-snapshots for network/DPC
            result.baseline.before_network.ping_ms = result.network.internet_ping_ms if result.network else 0
            result.baseline.before_network.jitter_ms = result.network.internet_jitter_ms if result.network else 0
            result.baseline.before_network.loss_pct = result.network.internet_loss_pct if result.network else 0
            result.baseline.before_network.dns_ms = result.network.dns_resolution_ms if result.network else 0
            result.baseline.before_network.gateway_ping_ms = result.network.gateway_ping_ms if result.network else 0
            result.baseline.before_dpc.dpc_rate_per_sec = r.ram.dpc_rate_per_sec
            result.baseline.before_dpc.isr_rate_per_sec = r.ram.isr_rate_per_sec
            if r.ram.dpc_top_offenders:
                top = r.ram.dpc_top_offenders[0]
                result.baseline.before_dpc.top_offender = top.get("name", "")
                result.baseline.before_dpc.top_offender_us = top.get("latency_us", 0)

            result.scores = calculate_scores(r, result.network)
            self._emit("scoring",
                       f"Overall score: {result.scores.overall.score}/100 "
                       f"({result.scores.overall.label})",
                       94, 18)
        except Exception as exc:
            logger.warn(f"DD scoring failed: {exc}")
            self._emit("scoring", "Scoring unavailable", 94, 18)

        # Stage 20: Diagnosis
        self._emit("diagnosis", "Generating delay diagnosis report...", 95, 19)
        plan = ExecutionPlan()
        result.report = self.reporter.generate(
            r, selected, plan, result.baseline, result.correlations,
        )
        result.total_time = time.monotonic() - t0
        self._emit("diagnosis",
                   f"Delay analysis complete — {result.report.summary_text}",
                   98, 19)
        logger.info(
            f"DD: finished in {result.total_time:.1f}s — "
            f"{len(result.findings)} findings, "
            f"{len(result.correlations)} correlations, "
            f"{len(selected)} fixable"
        )
        return result

    def run_apply(self, result: DelayDestroyerResult,
                  selected_fixes: list[Fix]) -> DelayDestroyerResult:
        if not selected_fixes:
            return result
        session_id = f"dd_{uuid.uuid4().hex[:12]}"
        result.backup_session = self.backup_manager.create_session(session_id)
        for fix in selected_fixes:
            try:
                self.backup_manager.backup_fix(
                    result.backup_session, fix.id, fix.actions)
            except Exception as exc:
                logger.warn(f"DD backup {fix.id} failed: {exc}")

        result.plan = self.executor.execute(selected_fixes, self.backup_manager)
        for fr in result.plan.results:
            if fr.success:
                result.backup_session.applied_fixes.append(fr.fix_id)

        if result.plan.applied > 0:
            time.sleep(2)
            result.baseline.after = capture_snapshot()
            try:
                result.baseline.after_network = capture_network_snapshot()
            except Exception:
                pass
            try:
                result.baseline.after_dpc = capture_dpc_snapshot()
            except Exception:
                pass

        try:
            self.backup_manager.save_session(result.backup_session)
        except Exception as exc:
            logger.warn(f"DD backup save failed: {exc}")

        result.report = self.reporter.generate(
            result.scan, selected_fixes, result.plan,
            result.baseline, result.correlations,
        )
        logger.info(
            f"DD apply: {result.plan.applied} applied, "
            f"{result.plan.failed} failed, "
            f"{result.plan.rollback_count} rolled back"
        )
        return result
