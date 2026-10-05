"""Category: Display — desktop, wallpaper and rendering behaviour."""
from __future__ import annotations

from ._base import make_T, validate_module

T = make_T("Display", win_default="7,8,10,11")
CATEGORY = "Display"

TWEAKS = validate_module("display", [

    T("disp-002", "Outline-Only Window Dragging",
      "Shows only the window outline while dragging.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop", "DragFullWindows", 0, "STRING")],
      revert=[("reg", "HKCU", r"Control Panel\Desktop", "DragFullWindows", 1, "STRING")],
      why="Skipping live window redraws while dragging saves CPU on weaker systems.",
      changes="Disables full window drag.",
      risk="safe", impact="low", recommended="optional",
      tags=["drag", "window", "outline"]),

    T("disp-004", "Solid Color Wallpaper",
      "Replaces the wallpaper with a solid color to reduce desktop redraws.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop", "Wallpaper", " ", "STRING")],
      revert=[("reg", "HKCU", r"Control Panel\Desktop", "Wallpaper", r"C:\Windows\Web\Wallpaper\Windows\img0.jpg", "STRING")],
      why="A static wallpaper avoids the memory and redraw cost of large images.",
      changes="Sets a blank wallpaper.",
      risk="safe", impact="very low", recommended="optional",
      tags=["wallpaper", "desktop", "memory"]),
    T("disp-005", "Disable Translucent Selection",
      "Turns off the translucent rectangle used for file selection.",
      actions=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ListviewAlphaSelect", 0, "DWORD")],
      revert=[("reg", "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ListviewAlphaSelect", 1, "DWORD")],
      why="Removes an alpha compositing pass in Explorer.",
      changes="Disables translucent selection.",
      risk="safe", impact="very low", recommended="recommended",
      tags=["selection", "transparency", "explorer"]),
    T("disp-009", "Compact Icon Spacing",
      "Tightens desktop icon spacing.",
      actions=[("reg", "HKCU", r"Control Panel\Desktop\WindowMetrics", "IconSpacing", -1125, "STRING")],
      revert=[("regdel", "HKCU", r"Control Panel\Desktop\WindowMetrics", "IconSpacing")],
      why="Denser grids fit more icons and reduce scrolling on busy desktops.",
      changes="Sets IconSpacing to -1125.",
      risk="safe", impact="very low", recommended="optional",
      tags=["icons", "spacing", "desktop"]),
    T("disp-012", "Disable Overlays",
      "Disables Game DVR overlay capture via registry.",
      actions=[("reg", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0, "DWORD")],
      revert=[("regdel", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled")],
      why="Overlay layers add input and render latency in fullscreen titles.",
      changes="Sets AppCaptureEnabled to 0.",
      risk="safe", impact="low", recommended="recommended",
      tags=["overlay", "ghosting", "latency"]),

    T("disp-014", "Disable Hardware Overlay",
      "Turns off the hardware overlay plane to force GPU compositing.",
      actions=[("reg", "HKLM", r"SOFTWARE\Microsoft\Windows\DWM", "EnableHardwareOverlay", 0, "DWORD")],
      revert=[("regdel", "HKLM", r"SOFTWARE\Microsoft\Windows\DWM", "EnableHardwareOverlay")],
      why="Hardware overlays can cause visual glitches and composition conflicts; forcing GPU compositing avoids them.",
      changes="Disables DWM hardware overlay.",
      risk="safe", impact="low", recommended="optional", admin=True,
      tags=["overlay", "dwm", "compositing"]),

    T("disp-016", "Disable Night Light",
      "Turns off the Windows Night Light blue-light filter.",
      actions=[("reg", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\current\default$windows.data.bluelightreduction.bluelightreductionstate\windows.data.bluelightreduction.bluelightreductionstate", "Enabled", 0, "DWORD")],
      revert=[("regdel", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\current\default$windows.data.bluelightreduction.bluelightreductionstate\windows.data.bluelightreduction.bluelightreductionstate", "Enabled")],
      why="Night Light applies a per-frame color transform; disabling it removes that GPU work and ensures accurate color output.",
      changes="Disables Night Light blue-light filter.",
      risk="safe", impact="very low", recommended="optional", admin=False,
      tags=["nightlight", "bluelight", "color"]),
])
