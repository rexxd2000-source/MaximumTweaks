"""Shared types for the Smart Debloater."""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field


class DebloatCategory(str, Enum):
    MICROSOFT_STORE = "Microsoft Store Apps"
    THIRD_PARTY = "Third-Party Apps"
    OEM = "OEM Apps"
    OPTIONAL_SERVICES = "Optional Services"
    SCHEDULED_TASKS = "Scheduled Tasks"
    STARTUP = "Startup Programs"


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    OPTIONAL = "OPTIONAL"
    CAUTION = "CAUTION"
    PROTECTED = "PROTECTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class OSInfo:
    product_name: str = ""
    edition: str = ""
    version: str = ""
    build: str = ""
    architecture: str = ""
    display_version: str = ""

    def to_dict(self) -> dict:
        return {
            "product_name": self.product_name,
            "edition": self.edition,
            "version": self.version,
            "build": self.build,
            "architecture": self.architecture,
            "display_version": self.display_version,
        }


@dataclass
class DebloatItem:
    id: str
    name: str
    description: str
    what_happens: str
    category: DebloatCategory
    risk: RiskLevel
    confidence: int = 0
    reversible: bool = True
    detected: bool = True
    remove_command: str = ""
    restore_command: str = ""
    verify_command: str = ""
    source: str = ""
    version_found: str = ""
    is_protected: bool = False
    protected_reason: str = ""
    required_by: list[str] = field(default_factory=list)
    is_gaming_related: bool = False
    group: str = ""
    detail_service: str = ""
    detail_state: str = ""
    detail_startup: str = ""
    detail_dependencies: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "what_happens": self.what_happens,
            "category": self.category.value,
            "risk": self.risk.value,
            "confidence": self.confidence,
            "reversible": self.reversible,
            "detected": self.detected,
            "source": self.source,
            "version_found": self.version_found,
            "is_protected": self.is_protected,
            "protected_reason": self.protected_reason,
            "required_by": self.required_by,
            "is_gaming_related": self.is_gaming_related,
            "group": self.group,
        }


@dataclass
class DebloatResult:
    os_info: OSInfo
    items: list[DebloatItem]
    scan_time: float = 0.0
    categories: dict[str, list[DebloatItem]] = field(default_factory=dict)
    groups: dict[str, list[DebloatItem]] = field(default_factory=dict)
    dep_map: object = None
    is_gaming_pc: bool = False
    gaming_software: list[str] = field(default_factory=list)
    total_protected: int = 0
    total_debloatable: int = 0

    def organize(self):
        self.categories = {}
        self.groups = {}
        for item in self.items:
            cat = item.category.value
            if cat not in self.categories:
                self.categories[cat] = []
            self.categories[cat].append(item)
            grp = item.group or "Other"
            if grp not in self.groups:
                self.groups[grp] = []
            self.groups[grp].append(item)
