"""Smart Debloater — application-focused, dependency-aware, user-controlled.

Scans the user's actual PC, finds genuinely unnecessary applications,
checks whether anything depends on them, and recommends safe removals.
"""

from engine.debloat.types import (
    DebloatCategory, RiskLevel, OSInfo, DebloatItem, DebloatResult,
)
from engine.debloat.engine import DebloatEngine
from engine.debloat.backup import BackupManager
