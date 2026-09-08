"""Rebuilt executor with proper backup/apply/verify/rollback flow."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .backup import BackupManager
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
        """Total number of fixes attempted."""
        return len(self.results)
    
    @property
    def applied(self) -> int:
        """Number of successfully applied fixes."""
        return sum(1 for r in self.results if r.success and not r.rolled_back)
    
    @property
    def failed(self) -> int:
        """Number of fixes that failed to apply."""
        return sum(1 for r in self.results if not r.success and not r.rolled_back)
    
    @property
    def skipped(self) -> int:
        """Number of fixes skipped (predicate returned False)."""
        return sum(1 for r in self.results if r.message == "skipped")
    
    @property
    def rollback_count(self) -> int:
        """Number of fixes that were rolled back."""
        return sum(1 for r in self.results if r.rolled_back)
    
    @property
    def success_rate(self) -> float:
        """Success rate as a percentage (0-100)."""
        if self.total == 0:
            return 0.0
        successful = self.applied + self.rollback_count
        return (successful / self.total) * 100.0


class Executor:
    """Executes fixes with backup, apply, verify, and rollback support."""
    
    def __init__(self):
        """Initialize the executor."""
        self._execution_history: List[ExecutionPlan] = []
    
    def execute(
        self,
        fixes: List[Fix],
        backup_manager: Optional[BackupManager] = None
    ) -> ExecutionPlan:
        """
        Execute a list of fixes with backup/apply/verify/rollback.
        
        Args:
            fixes: List of Fix objects to execute
            backup_manager: Optional BackupManager for backup/rollback support
            
        Returns:
            ExecutionPlan with results of all fix attempts
        """
        plan = ExecutionPlan()
        
        for fix in fixes:
            result = self._execute_single_fix(fix, backup_manager)
            plan.results.append(result)
        
        self._execution_history.append(plan)
        return plan
    
    def _execute_single_fix(
        self,
        fix: Fix,
        backup_manager: Optional[BackupManager]
    ) -> FixResult:
        """Execute a single fix with full backup/apply/verify/rollback flow."""
        start_time = time.time()
        
        # Check predicate first
        can_apply, predicate_msg = fix.predicate
        if not can_apply:
            return FixResult(
                fix_id=fix.id,
                title=fix.title,
                success=True,
                message="skipped",
                duration_ms=0.0
            )
        
        # Step 1: Create backup if backup_manager provided
        before_state = None
        backup_id = None
        if backup_manager:
            try:
                backup_id = backup_manager.backup_fix(fix.id)
                before_state = f"Backup created: {backup_id}"
            except Exception as e:
                return FixResult(
                    fix_id=fix.id,
                    title=fix.title,
                    success=False,
                    message=f"Backup failed: {str(e)}",
                    duration_ms=(time.time() - start_time) * 1000
                )
        
        # Step 2: Apply the fix
        apply_success, apply_message = apply_fix(fix)
        if not apply_success:
            return FixResult(
                fix_id=fix.id,
                title=fix.title,
                success=False,
                message=f"Apply failed: {apply_message}",
                before_state=before_state,
                duration_ms=(time.time() - start_time) * 1000
            )
        
        # Step 3: Wait for changes to take effect
        time.sleep(0.5)
        
        # Step 4: Verify the fix
        verify_success, verify_message = verify_fix(fix)
        if not verify_success:
            # Step 5: Rollback if verification fails
            if backup_manager and backup_id:
                try:
                    backup_manager.restore_fix(backup_id)
                    return FixResult(
                        fix_id=fix.id,
                        title=fix.title,
                        success=False,
                        message=f"Verification failed, rolled back: {verify_message}",
                        rolled_back=True,
                        before_state=before_state,
                        after_state=f"Rolled back to backup: {backup_id}",
                        duration_ms=(time.time() - start_time) * 1000
                    )
                except Exception as rollback_error:
                    return FixResult(
                        fix_id=fix.id,
                        title=fix.title,
                        success=False,
                        message=f"Verification failed AND rollback failed: {verify_message} / {str(rollback_error)}",
                        rolled_back=False,
                        before_state=before_state,
                        duration_ms=(time.time() - start_time) * 1000
                    )
            else:
                return FixResult(
                    fix_id=fix.id,
                    title=fix.title,
                    success=False,
                    message=f"Verification failed: {verify_message}",
                    before_state=before_state,
                    duration_ms=(time.time() - start_time) * 1000
                )
        
        # Step 6: Success - save backup session
        if backup_manager and backup_id:
            try:
                backup_manager.save_session(backup_id)
            except Exception:
                pass  # Non-critical, continue
        
        return FixResult(
            fix_id=fix.id,
            title=fix.title,
            success=True,
            message="Fix applied and verified successfully",
            before_state=before_state,
            after_state="Applied and verified",
            duration_ms=(time.time() - start_time) * 1000
        )
    
    @property
    def last_plan(self) -> Optional[ExecutionPlan]:
        """Get the most recent execution plan."""
        if self._execution_history:
            return self._execution_history[-1]
        return None
    
    @property
    def execution_history(self) -> List[ExecutionPlan]:
        """Get all execution plans."""
        return self._execution_history.copy()