"""Diagnostic report generator for the Delay Destroyer engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .executor import ExecutionPlan, FixResult
from .scanner import ScanResult
from .fixes import Fix


@dataclass
class ReportItem:
    """A single item in a report section."""
    title: str
    description: str
    evidence: str
    risk: str
    status: str  # "info", "applied", "failed", "rolled_back", "warning"


@dataclass
class ReportSection:
    """A section of the diagnostic report."""
    title: str
    icon: str
    color: str
    items: List[ReportItem] = field(default_factory=list)


@dataclass
class Report:
    """Complete diagnostic report."""
    system_summary: ReportSection
    findings_section: ReportSection
    fixes_section: ReportSection
    baseline_section: ReportSection
    correlation_section: Optional[ReportSection] = None
    summary_text: str = ""
    total_findings: int = 0
    total_fixes_applied: int = 0
    total_fixes_failed: int = 0
    no_changes_needed: bool = False


class Reporter:
    """Generates diagnostic reports from scan results and execution plans."""
    
    def __init__(self):
        """Initialize the reporter."""
        self._report_history: List[Report] = []
    
    def generate(
        self,
        scan: ScanResult,
        findings: List[Fix],
        plan: ExecutionPlan,
        baseline,
        correlations=None
    ) -> Report:
        """
        Generate a comprehensive diagnostic report.
        
        Args:
            scan: ScanResult from system scan
            findings: List of Fix objects that were identified
            plan: ExecutionPlan with results
            baseline: Baseline performance data
            correlations: Optional correlation data
            
        Returns:
            Report with all sections
        """
        # Build system summary section
        system_summary = self._build_system_summary(scan)
        
        # Build findings section
        findings_section = self._build_findings_section(findings, plan)
        
        # Build fixes section
        fixes_section = self._build_fixes_section(plan)
        
        # Build baseline section
        baseline_section = self._build_baseline_section(baseline)
        
        # Build correlation section if provided
        correlation_section = None
        if correlations:
            correlation_section = self._build_correlation_section(correlations)
        
        # Calculate totals
        total_findings = len(findings)
        total_fixes_applied = plan.applied
        total_fixes_failed = plan.failed
        
        # Determine if no changes were needed
        no_changes_needed = (
            total_findings == 0 and
            total_fixes_applied == 0 and
            total_fixes_failed == 0
        )
        
        # Generate summary text
        summary_text = self._generate_summary_text(
            total_findings,
            total_fixes_applied,
            total_fixes_failed,
            plan.rollback_count,
            no_changes_needed
        )
        
        report = Report(
            system_summary=system_summary,
            findings_section=findings_section,
            fixes_section=fixes_section,
            baseline_section=baseline_section,
            correlation_section=correlation_section,
            summary_text=summary_text,
            total_findings=total_findings,
            total_fixes_applied=total_fixes_applied,
            total_fixes_failed=total_fixes_failed,
            no_changes_needed=no_changes_needed
        )
        
        self._report_history.append(report)
        return report
    
    def _build_system_summary(self, scan: ScanResult) -> ReportSection:
        """Build the system summary section."""
        section = ReportSection(
            title="System Summary",
            icon="💻",
            color="#3498db"
        )
        
        # CPU info
        section.items.append(ReportItem(
            title="Processor",
            description=scan.cpu.name or "Unknown CPU",
            evidence=f"Cores: {scan.cpu.cores} physical / {scan.cpu.threads} logical",
            risk="info",
            status="info"
        ))
        
        # GPU info
        has_dedicated = len(scan.gpu.dedicated) > 0
        gpu_name = scan.gpu.names[0] if scan.gpu.names else "Unknown GPU"
        if has_dedicated:
            gpu_desc = f"{gpu_name} (Dedicated)"
            gpu_evidence = f"Driver: {scan.gpu.driver_version}"
            if scan.gpu.dedicated_vram_gb:
                gpu_evidence += f" | Dedicated VRAM: {scan.gpu.dedicated_vram_gb} GB"
            if scan.gpu.shared_vram_gb:
                gpu_evidence += f" | Shared GPU Memory: {scan.gpu.shared_vram_gb} GB"
            if scan.gpu.vram_detection_method:
                gpu_evidence += f" | Detection: {scan.gpu.vram_detection_method}"
        else:
            gpu_desc = f"{gpu_name} (Integrated)"
            gpu_evidence = f"Driver: {scan.gpu.driver_version}"
            if scan.gpu.shared_vram_gb:
                gpu_evidence += f" | Shared GPU Memory: {scan.gpu.shared_vram_gb} GB"
            if scan.gpu.vram_detection_method:
                gpu_evidence += f" | Detection: {scan.gpu.vram_detection_method}"
        
        section.items.append(ReportItem(
            title="Graphics",
            description=gpu_desc,
            evidence=gpu_evidence,
            risk="info",
            status="info"
        ))
        
        # Memory info
        section.items.append(ReportItem(
            title="Memory",
            description=f"{scan.ram.total_gb:.1f} GB RAM",
            evidence=f"Usage: {scan.ram.pressure * 100:.1f}% | Speed: {scan.ram.speed_mtps} MHz",
            risk="info",
            status="info"
        ))
        
        # Storage info
        storage_desc = []
        if scan.storage.has_ssd:
            storage_desc.append("SSD")
        if scan.storage.has_hdd:
            storage_desc.append("HDD")
        section.items.append(ReportItem(
            title="Storage",
            description=", ".join(storage_desc) if storage_desc else "Unknown",
            evidence=f"Fast Startup: {'Enabled' if scan.storage.fast_startup_enabled else 'Disabled'}",
            risk="info",
            status="info"
        ))
        
        # OS info
        section.items.append(ReportItem(
            title="Operating System",
            description=f"{scan.os.edition} {scan.os.version}",
            evidence=f"Build: {scan.os.build}",
            risk="info",
            status="info"
        ))
        
        # Power plan
        section.items.append(ReportItem(
            title="Power Plan",
            description=scan.cpu.power_plan_guid or "Unknown",
            evidence=f"GUID: {scan.cpu.power_plan_guid or 'N/A'}",
            risk="info",
            status="info"
        ))
        
        return section
    
    def _build_findings_section(
        self,
        findings: List[Fix],
        plan: ExecutionPlan
    ) -> ReportSection:
        """Build the findings section."""
        section = ReportSection(
            title="Optimization Findings",
            icon="🔍",
            color="#f39c12"
        )
        
        # Create a map of fix IDs to their results
        result_map = {r.fix_id: r for r in plan.results}
        
        for fix in findings:
            # Determine status
            if fix.id in result_map:
                result = result_map[fix.id]
                if result.rolled_back:
                    status = "rolled_back"
                elif result.success:
                    status = "applied"
                elif "skipped" in result.message.lower():
                    status = "info"
                else:
                    status = "failed"
            else:
                status = "warning"
            
            section.items.append(ReportItem(
                title=fix.title,
                description=fix.why,
                evidence=fix.expected_effect,
                risk=fix.risk.value if hasattr(fix.risk, 'value') else str(fix.risk),
                status=status
            ))
        
        return section
    
    def _build_fixes_section(self, plan: ExecutionPlan) -> ReportSection:
        """Build the fixes section showing execution results."""
        section = ReportSection(
            title="Applied Fixes",
            icon="🔧",
            color="#27ae60"
        )
        
        for result in plan.results:
            if "skipped" in result.message.lower():
                continue
            
            if result.rolled_back:
                status = "rolled_back"
                desc = f"Rolled back: {result.message}"
            elif result.success:
                status = "applied"
                desc = result.message
            else:
                status = "failed"
                desc = result.message
            
            section.items.append(ReportItem(
                title=result.title,
                description=desc,
                evidence=f"Duration: {result.duration_ms:.1f}ms",
                risk="info",
                status=status
            ))
        
        return section
    
    def _build_baseline_section(self, baseline) -> ReportSection:
        """Build the baseline performance section."""
        from .baseline import Baseline, Snapshot
        section = ReportSection(
            title="Baseline Performance",
            icon="📊",
            color="#9b59b6"
        )
        
        if not baseline or not isinstance(baseline, Baseline):
            section.items.append(ReportItem(
                title="No Baseline Data",
                description="Baseline performance data not available",
                evidence="Run a baseline measurement to compare before/after optimization",
                risk="info",
                status="info"
            ))
            return section
        
        b = baseline.before
        section.items.append(ReportItem(
            title="CPU Usage",
            description=f"{b.cpu_percent:.1f}%",
            evidence=f"Processes: {b.process_count} | Top CPU: {b.top_cpu_process} ({b.top_cpu_pct:.1f}%)",
            risk="info",
            status="info"
        ))
        
        section.items.append(ReportItem(
            title="RAM Usage",
            description=f"{b.ram_percent:.1f}%",
            evidence=f"Used: {b.ram_used_gb:.1f} GB | Top RAM: {b.top_mem_process} ({b.top_mem_pct:.1f}%)",
            risk="info",
            status="info"
        ))
        
        if baseline.after and baseline.after.timestamp > 0:
            section.items.append(ReportItem(
                title="Post-Optimization",
                description=f"CPU: {baseline.after.cpu_percent:.1f}% | RAM: {baseline.after.ram_percent:.1f}%",
                evidence=(
                    f"CPU delta: {baseline.cpu_delta:+.1f}% | "
                    f"RAM delta: {baseline.ram_delta:+.1f}% | "
                    f"Process delta: {baseline.process_delta:+d}"
                ),
                risk="info",
                status="info"
            ))
        
        return section
    
    def _build_correlation_section(self, correlations) -> ReportSection:
        """Build the correlation analysis section."""
        section = ReportSection(
            title="Correlations",
            icon="🔗",
            color="#1abc9c"
        )
        
        if not correlations:
            section.items.append(ReportItem(
                title="No Correlation Data",
                description="No correlation analysis available",
                evidence="Provide correlation data for cross-metric analysis",
                risk="info",
                status="info"
            ))
            return section
        
        for c in correlations:
            desc = getattr(c, "description", getattr(c, "title", str(c)))
            evidence = getattr(c, "evidence", "")
            risk = getattr(c, "risk", "info")
            section.items.append(ReportItem(
                title=getattr(c, "title", "Correlation"),
                description=desc,
                evidence=evidence,
                risk=str(risk),
                status="info"
            ))
        
        return section
    
    def _generate_summary_text(
        self,
        total_findings: int,
        total_applied: int,
        total_failed: int,
        total_rollback: int,
        no_changes_needed: bool
    ) -> str:
        """Generate a human-readable summary."""
        if no_changes_needed:
            return (
                "Your system is already optimized. No changes were needed. "
                "All settings are at recommended values."
            )
        
        parts = []
        
        if total_findings > 0:
            parts.append(f"Found {total_findings} optimization opportunities.")
        else:
            parts.append("No optimization opportunities found.")
        
        if total_applied > 0:
            parts.append(f"Successfully applied {total_applied} fixes.")
        
        if total_failed > 0:
            parts.append(f"Failed to apply {total_failed} fixes.")
        
        if total_rollback > 0:
            parts.append(f"Rolled back {total_rollback} fixes due to verification failures.")
        
        if total_applied > 0 and total_failed == 0 and total_rollback == 0:
            parts.append(
                "All optimizations applied successfully. "
                "Restart your computer for changes to take full effect."
            )
        elif total_failed > 0 or total_rollback > 0:
            parts.append(
                "Some fixes could not be applied. "
                "This may be due to system permissions or compatibility issues."
            )
        
        return " ".join(parts)
    
    @property
    def last_report(self) -> Optional[Report]:
        """Get the most recent report."""
        if self._report_history:
            return self._report_history[-1]
        return None
    
    @property
    def report_history(self) -> List[Report]:
        """Get all generated reports."""
        return self._report_history.copy()