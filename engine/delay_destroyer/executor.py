"""Executor — applies fixes and verifies results.

Backup/rollback is handled by the engine. This module just applies
and verifies each fix in sequence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from .fixes import Fix, apply_fix, verify_fix


@dataclass
class FixResult:
    """Result of executing a single fix."""
    fix_id: str
    title: str
    success: bool
    message: str
    rolled_back: bool = False
    before_state: Optional[str] = None
    after_state: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class ExecutionPlan:
    """Results of executing multiple fixes."""
    results: List[FixResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def applied(self) -> int:
        return sum(1 for r in self.results if r.success and not r.rolled_back)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success and not r.rolled_back)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.message == "skipped")

    @property
    def rollback_count(self) -> int:
        return sum(1 for r in self.results if r.rolled_back)

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        successful = self.applied + self.rollback_count
        return (successful / self.total) * 100.0


class Executor:
    """Executes fixes with apply and verify support."""

    def __init__(self):
        self._execution_history: List[ExecutionPlan] = []

    def execute(
        self,
        fixes: List[Fix],
        backup_manager=None,
    ) -> ExecutionPlan:
        """Execute a list of fixes. Backup handled externally."""
        plan = ExecutionPlan()
        for fix in fixes:
            result = self._execute_single_fix(fix)
            plan.results.append(result)
        self._execution_history.append(plan)
        return plan

    def _execute_single_fix(self, fix: Fix) -> FixResult:
        """Apply a fix and verify it."""
        start = time.time()

        # Apply
        apply_ok, apply_msg = apply_fix(fix)
        if not apply_ok:
            return FixResult(
                fix_id=fix.id, title=fix.title,
                success=False, message=f"Apply failed: {apply_msg}",
                duration_ms=(time.time() - start) * 1000)

        # Wait for changes to settle
        time.sleep(0.5)

        # Verify
        verify_ok, verify_msg = verify_fix(fix)
        if not verify_ok:
            return FixResult(
                fix_id=fix.id, title=fix.title,
                success=False, message=f"Verification failed: {verify_msg}",
                duration_ms=(time.time() - start) * 1000)

        return FixResult(
            fix_id=fix.id, title=fix.title,
            success=True, message="Applied and verified",
            after_state="Applied",
            duration_ms=(time.time() - start) * 1000)

    @property
    def last_plan(self) -> Optional[ExecutionPlan]:
        return self._execution_history[-1] if self._execution_history else None

    @property
    def execution_history(self) -> List[ExecutionPlan]:
        return self._execution_history.copy()
