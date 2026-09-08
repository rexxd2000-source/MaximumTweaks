"""Category: Input Latency — input handling and mouse behaviour guidance.

The registry-changing input tweaks that used to live here were duplicates of
the canonical ones in the Mouse / Keyboard / Gaming categories (mouse-001,
mouse-002, mouse-004, kbd-001, kbd-003, kbd-004, game-002).  Applying both a
duplicate and its canonical twin made "Enhance pointer precision" and friends
flip back and forth depending on apply/revert order, so the duplicates were
removed.  What remains is pointer/input guidance that has no registry action.
"""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Input Latency", win_default="7,8,10,11")
CATEGORY = "Input Latency"

TWEAKS = validate_module("input_latency", [
    T("il-005", "Set Mouse Precision Mode",
      "Guidance on raw input in games.",
      actions=[("guidance", "In shooters, enable 'Raw Input' in-game so the mouse bypasses Windows pointer scaling. Your in-game sensitivity then matches your DPI exactly.")],
      revert=[("guidance", "Turn off raw input.")],
      why="Raw input skips the desktop pointer path entirely.",
      changes="Shows raw-input guidance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["rawinput", "mouse", "sensitivity"]),
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
    T("il-008", "Enable Raw Mouse Rate",
      "Guidance on mouse polling rate.",
      actions=[("guidance", "Set your mouse to its max polling rate (500-1000Hz) in its software. A 1000Hz mouse reports each ms, trimming one USB report-interval of latency.")],
      revert=[("guidance", "Lower the polling rate.")],
      why="Higher poll rates reduce worst-case input report delay.",
      changes="Shows polling-rate guidance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["polling", "mouse", "rate"]),
    T("il-012", "Disable Pointer Acceleration in Games Config",
      "Guidance to disable mouse smoothing in engine configs.",
      actions=[("guidance", "Some engines add mouse smoothing beyond Windows. Disable it in the game config (e.g. bMouseAcceleration=0 in Source, 'Mouse Smoothing' off in others).")],
      revert=[("guidance", "Re-enable engine mouse smoothing.")],
      why="Engine-level smoothing adds its own velocity curve.",
      changes="Shows engine-smoothing guidance.",
      risk="safe", impact="moderate", recommended="recommended",
      tags=["smoothing", "engine", "mouse"]),
])
