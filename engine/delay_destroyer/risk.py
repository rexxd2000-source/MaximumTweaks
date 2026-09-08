"""Risk scoring engine — evaluates potential changes before execution.

Every proposed modification receives a risk score that determines
whether it is applied automatically, requires confirmation, or is
excluded entirely.
"""
from __future__ import annotations

from enum import Enum


class Risk(Enum):
    LOW = "low"           # Safe configuration adjustment
    MODERATE = "moderate" # Hardware/OS dependent
    HIGH = "high"         # Don't auto-apply, require confirmation
    CRITICAL = "critical" # Never apply automatically


def risk_label(risk: Risk) -> str:
    return {
        Risk.LOW: "Low Risk",
        Risk.MODERATE: "Moderate Risk",
        Risk.HIGH: "High Risk",
        Risk.CRITICAL: "Critical Risk",
    }[risk]


def risk_color(risk: Risk) -> str:
    return {
        Risk.LOW: "#22C55E",
        Risk.MODERATE: "#EAB308",
        Risk.HIGH: "#F97316",
        Risk.CRITICAL: "#EF4444",
    }[risk]


def risk_emoji(risk: Risk) -> str:
    return {
        Risk.LOW: "\U0001f7e2",
        Risk.MODERATE: "\U0001f7e1",
        Risk.HIGH: "\U0001f534",
        Risk.CRITICAL: "\u26d4",
    }[risk]
