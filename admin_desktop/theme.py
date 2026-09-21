"""Maximum Tweaks Admin - "Sigil" theme: teal surface, gold accents, serif.

Design tokens taken from the key-manager.html mockup (teal/ink background,
gold serif headings, cream ink, live-green/warn-amber/rose states, IBM Plex
Mono key labels) so the native desktop admin panel matches the mockup 1:1.

Fonts are bundled under ``assets/fonts`` and registered via QFontDatabase so
the EXE carries the same typography without any web dependency; they fall back
to Georgia/Segoe UI/Consolas when missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- tokens ----------------------------------------------------------------

SIGIL = {
    "bg": "#061a1d",
    "bg_end": "#051417",
    "ink": "#efe8d8",
    "ink_2": "#c9c3b3",
    "muted": "#8ea3a0",
    "line": "rgba(232, 214, 168, 38)",
    "line_dim": "rgba(232, 214, 168, 22)",
    "line_soft": "rgba(232, 214, 168, 12)",
    "line_gold": "#e6cc92",
    "gold": "#e6cc92",
    "gold_deep": "#b18f52",
    "gold_hi": "#f2dfb2",
    "live": "#7fe0b0",
    "warn": "#efb56a",
    "rose": "#ec7686",
    "teal": "#5fc4c0",
    "chip_bg": "rgba(95, 196, 192, 32)",
    "field": "rgba(0, 0, 0, 0.28)",
    "panel_a": "rgba(255, 255, 255, 22)",
    "panel_b": "rgba(255, 255, 255, 10)",
    "panel_border": "rgba(232, 214, 168, 38)",
}

# --- font helpers -----------------------------------------------------------

_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

FONT_FILES = (
    "InstrumentSerif-Regular.ttf",
    "InstrumentSerif-Italic.ttf",
    "Manrope-Regular.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)

SERIF = "Instrument Serif"
SANS = "Manrope"
MONO = "IBM Plex Mono"


def register_fonts() -> None:
    """Load the bundled fonts into this process so QSS family names resolve."""
    from PySide6.QtGui import QFontDatabase  # local import (PyInstaller safety)

    for name in FONT_FILES:
        path = _FONT_DIR / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def resource_path(rel: str) -> str:
    """Resolve bundled assets in both dev (source tree) and one-file EXE mode."""
    try:
        # PyInstaller one-file: bundled assets are extracted next to sys._MEIPASS
        import sys as _sys
        if getattr(_sys, "frozen", False):
            base = Path(_sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent
    except Exception:  # noqa: BLE001
        base = Path(__file__).resolve().parent
    return str(base / rel)


ICON_PATH = resource_path("assets/app.ico")


def rgba(hex_color: str, alpha: float) -> str:
    """rgba() for the QSS variants; hex must be #rrggbb."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return hex_color
    return (f"rgba({int(hex_color[0:2], 16)}, {int(hex_color[2:4], 16)}, "
            f"{int(hex_color[4:6], 16)}, {alpha:.2f})")


# --- QSS ---------------------------------------------------------------------

def build_qss(t: dict | None = None) -> str:
    T = t or SIGIL
    return f"""
* {{
    font-family: "{SANS}", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {T["ink"]};
}}
QMainWindow {{
    background: {T["bg"]};
}}
QWidget {{
    background: transparent;
}}
QDialog {{
    background: #0d282d;
}}
::placeholder {{ color: {T["muted"]}; }}

/* ---------- header ---------- */
#Header {{
    background: {T["bg"]};
    border-bottom: 1px solid {T["line_soft"]};
}}
#Brand {{
    font-family: "{SERIF}", Georgia, serif;
    font-size: 24px;
    color: {T["ink"]};
}}
#BrandWord {{ color: {T["gold"]}; }}
#BrandSub {{
    font-family: "{MONO}", Consolas, monospace;
    font-size: 9px;
    color: {T["muted"]};
    letter-spacing: 3px;
}}

/* ---------- hero title ---------- */
#HeroTitle {{
    font-family: "{SERIF}", Georgia, serif;
    font-size: 30px;
    color: {T["ink"]};
}}
#HeroSub {{
    color: {T["muted"]};
    font-size: 13px;
}}

/* ---------- panels ---------- */
#Panel {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {T["panel_a"]}, stop:1 {T["panel_b"]});
    border: 1px solid {T["line"]};
    border-radius: 18px;
}}

/* ---------- stats ---------- */
#Stat {{ border-left: 1px solid {T["line_soft"]}; }}
#Stat:first-child {{ border-left: none; }}
#StatNum {{
    font-family: "{SERIF}", Georgia, serif;
    font-size: 30px;
    color: {T["ink"]};
}}
#StatLabel {{
    color: {T["muted"]};
    font-size: 12px;
    margin-top: 4px;
}}

/* ---------- tabs ---------- */
#Tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: {T["muted"]};
    font-weight: 600;
    font-size: 13px;
    padding: 6px 2px;
}}
#Tab:hover {{ color: {T["ink_2"]}; }}
#Tab:checked {{
    color: {T["ink"]};
    border-bottom: 2px solid {T["gold"]};
}}
#TabCount {{
    background: {rgba("#ffffff", 0.10)};
    border-radius: 8px;
    padding: 1px 7px;
    color: {T["ink_2"]};
    font-size: 11px;
    font-weight: 600;
}}

/* ---------- search ---------- */
#Search {{
    background: {rgba("#ffffff", 0.05)};
    border: 1px solid {T["line"]};
    border-radius: 20px;
    padding: 7px 14px;
    color: {T["ink"]};
}}
#Search:focus {{ border-color: {T["gold"]}; }}

/* ---------- column header + list head ---------- */
#ColHead {{
    color: {T["muted"]};
    font-size: 11.5px;
}}
#Key {{
    color: {T["muted"]};
    font-family: "{MONO}", Consolas, monospace;
    font-size: 11.5px;
}}

/* ---------- chips ---------- */
#Chip {{
    font-weight: 700;
    font-size: 12px;
    border-radius: 7px;
    padding: 3px 9px;
    border: 1px solid;
}}
#Chip.m1 {{ color: {T["teal"]}; border-color: {rgba("#5fc4c0", 0.40)}; background: {rgba("#5fc4c0", 0.10)}; }}
#Chip.m6 {{ color: {T["gold"]}; border-color: {rgba("#e6cc92", 0.40)}; background: {rgba("#e6cc92", 0.10)}; }}
#Chip.life {{ color: #2a1f08; border-color: transparent;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f2dfb2, stop:1 #cfab6b); }}

/* ---------- buttons ---------- */
QPushButton {{
    border: 1px solid transparent;
    border-radius: 18px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:focus {{ border-color: {T["gold"]}; outline: none; }}
#BtnGold {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f2dfb2, stop:1 #d3b071);
    color: #241a06;
}}
#BtnGold:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f7e8c3, stop:1 #dcbb7d); }}
#BtnGold:disabled {{ background: {rgba("#e6cc92", 0.35)}; color: {rgba("#241a06", 0.5)}; }}
#BtnGhost {{
    background: transparent;
    border: 1px solid {rgba("#e8d6a8", 0.30)};
    color: {T["ink"]};
}}
#BtnGhost:hover {{ background: {rgba("#ffffff", 0.06)}; }}
#BtnRose {{
    color: {T["rose"]};
    border: 1px solid {rgba("#ec7686", 0.40)};
    background: {rgba("#ec7686", 0.06)};
    font-weight: 700;
    font-size: 12px;
    border-radius: 16px;
    padding: 5px 12px;
}}
#BtnRose:hover {{ background: {rgba("#ec7686", 0.18)}; border-color: {rgba("#ec7686", 0.7)}; }}
#BtnRoseSolid {{
    background: {T["rose"]};
    color: #2b0a11;
    font-weight: 700;
}}
#BtnRoseSolid:hover {{ background: #f28d9a; }}

/* ---------- list rows ---------- */
#Row {{
    border-bottom: 1px solid {T["line_soft"]};
}}
#Row:hover {{ background: {rgba("#ffffff", 0.03)}; }}
#Row[selected="true"] {{ background: {rgba("#e6cc92", 0.075)}; }}
#RowName {{ font-weight: 700; font-size: 13px; }}
#RowLast {{ font-size: 12.5px; }}
#Online {{ color: {T["live"]}; font-weight: 600; font-size: 12.5px; }}
#Dot {{ background: {T["live"]}; border-radius: 3px; }}

/* ---------- detail ---------- */
#DetailTitle {{
    font-family: "{SERIF}", Georgia, serif;
    font-size: 25px;
    color: {T["ink"]};
}}
#DetailSub {{ color: {T["muted"]}; font-size: 12.5px; }}
#KeyBox {{
    background: {rgba("#000000", 0.28)};
    border: 1px solid {T["line"]};
    border-radius: 13px;
}}
#KeyCode {{
    font-family: "{MONO}", Consolas, monospace;
    font-size: 13px;
    letter-spacing: 1px;
    color: {T["gold"]};
}}
#FactName {{ color: {T["muted"]}; font-size: 11.5px; }}
#FactValue {{ font-weight: 600; font-size: 12.5px; }}
#FactWarn {{ color: {T["warn"]}; font-weight: 600; font-size: 12.5px; }}
#NoteRose {{
    color: #f6b3bc;
    border: 1px solid {rgba("#ec7686", 0.35)};
    background: {rgba("#ec7686", 0.07)};
    border-radius: 11px;
    font-size: 12.5px;
    padding: 10px 13px;
}}
#NoteAmber {{
    color: #f3cf9d;
    border: 1px solid {rgba("#efb56a", 0.35)};
    background: {rgba("#efb56a", 0.07)};
    border-radius: 11px;
    font-size: 12.5px;
    padding: 10px 13px;
}}
#SectionTitle {{
    font-family: "{SERIF}", Georgia, serif;
    font-size: 18px;
    color: {T["ink"]};
}}
#SectionSum {{ color: {T["muted"]}; font-size: 12.5px; }}

/* ---------- pill ---------- */
#Pill {{
    font-weight: 700;
    font-size: 12px;
    border-radius: 14px;
    padding: 3px 12px;
    border: 1px solid;
}}
#Pill[state="active"] {{ color: {T["live"]}; border-color: {rgba("#7fe0b0", 0.35)}; background: {rgba("#7fe0b0", 0.08)}; }}
#Pill[state="expired"] {{ color: {T["warn"]}; border-color: {rgba("#efb56a", 0.35)}; background: {rgba("#efb56a", 0.08)}; }}
#Pill[state="revoked"] {{ color: {T["rose"]}; border-color: {rgba("#ec7686", 0.40)}; background: {rgba("#ec7686", 0.08)}; }}

/* ---------- PC rows ---------- */
#PcvPC {{ border-bottom: 1px solid {T["line_soft"]}; }}
#PcName {{ font-weight: 600; font-size: 13px; }}
#PcHw {{ font-family: "{MONO}", Consolas, monospace; font-size: 11px; color: {T["muted"]}; }}
#PcStatus {{ font-size: 12.5px; }}
#PcStatus small {{ color: {T["muted"]}; font-size: 11.5px; }}
#MiniStat {{ font-size: 12px; color: {T["muted"]}; }}
#TextDi {{ color: {T["ink_2"]}; }}

/* ---------- inputs ---------- */
QLineEdit {{
    background: {T["field"]};
    border: 1px solid {T["line"]};
    border-radius: 9px;
    padding: 9px 12px;
    color: {T["ink"]};
    selection-background-color: {rgba("#e6cc92", 0.30)};
}}
QLineEdit:focus {{ border-color: {T["gold"]}; }}
QSpinBox {{
    background: {T["field"]};
    border: 1px solid {T["line"]};
    border-radius: 9px;
    padding: 7px 10px;
    color: {T["ink"]};
}}
QSpinBox:focus {{ border-color: {T["gold"]}; }}

/* ---------- plan cards (create-key dialog) ---------- */
#PlanCard {{
    background: {T["field"]};
    border: 1px solid {T["line"]};
    border-radius: 12px;
}}
#PlanCard:hover {{ border-color: {rgba("#e6cc92", 0.45)}; }}
#PlanCard[on="true"] {{
    border-color: {T["gold"]};
    background: {rgba("#e6cc92", 0.09)};
}}

/* ---------- list container ---------- */
#KeyList QListWidget {{
    border: none;
    background: transparent;
}}
#KeyList::item {{ border: none; background: transparent; }}
#KeyList::item:selected {{ background: transparent; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {rgba("#ffffff", 0.16)}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {rgba("#ffffff", 0.28)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {rgba("#ffffff", 0.16)}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------- toast ---------- */
#Toast {{
    background: #10333a;
    border: 1px solid {T["line"]};
    border-radius: 18px;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 13px;
}}
#Toast[danger="true"] {{ color: #f6b3bc; border-color: {rgba("#ec7686", 0.4)}; }}

QDialog #DialogTitle {{
    font-family: "{SERIF}", Georgia, serif;
    font-size: 22px;
}}
#DlgHint {{ color: {T["muted"]}; font-size: 13px; }}
#DlgFieldName {{ font-size: 12.5px; font-weight: 600; }}
#DlgErr {{ color: {T["rose"]}; font-size: 12px; }}
"""


SIGIL_QSS = build_qss()


def repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()