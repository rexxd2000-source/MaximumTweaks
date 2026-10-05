"""Category: Input Latency — input handling and mouse behaviour guidance.

The registry-changing input tweaks that used to live here were duplicates of
the canonical ones in the Mouse / Keyboard / Gaming categories (il-007 for
mouse acceleration, mouse-002, mouse-004, kbd-001, kbd-003, kbd-004,
game-002).  Applying both a duplicate and its canonical twin made "Enhance
pointer precision" and friends flip back and forth depending on apply/revert
order, so the duplicates were removed (mouse-001 consolidated into il-007).
What remains is pointer/input guidance that has no registry action.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Input Latency", win_default="7,8,10,11")
CATEGORY = "Input Latency"

TWEAKS = validate_module("input_latency", [
    T("il-006", "Disable Pointer Trails",
      "Turns off mouse pointer trails via registry.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop", "MouseTrails", "0", "STRING")],
      revert=[("reg", "HKCU", r"Control Panel\Desktop", "MouseTrails", "10", "STRING")],
      why="Pointer trails add a visual delay and rendering work.",
      changes="Sets MouseTrails to 0.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["trails", "pointer", "mouse"]),
    T("il-007", "Disable Enhanced Pointer Precision",
      "Disables enhanced pointer precision (mouse acceleration) via registry.",
      actions=[
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseSpeed", "0", "STRING"),
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseThreshold1", "0", "STRING"),
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseThreshold2", "0", "STRING"),
      ],
      revert=[
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseSpeed", "1", "STRING"),
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseThreshold1", "6", "STRING"),
          ("reg", "HKCU", r"Control Panel\Mouse", "MouseThreshold2", "10", "STRING"),
      ],
      why="Pointer effects add latency and visual noise.",
      changes="Disables pointer acceleration (MouseSpeed=0, thresholds=0).",
      risk="safe", impact="low", recommended="recommended",
      tags=["pointer", "precision", "mouse"]),
])
