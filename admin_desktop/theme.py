"""Maximum Tweaks Admin - red/black theme tokens + QSS.

Independent design system for the desktop admin app. Surfaces are obsidian
blacks with a ruby tint; the single accent is signal red:
  red = primary / action / active      amber = warning / expiring
  dim  = muted / inactive              muted-red = danger / revoked
"""
from __future__ import annotations

# --- tokens -------------------------------------------------------------
RED_BLACK = {
    "bg": "#090404",
    "bg_alt": "#0F0606",
    "sidebar": "#0B0505",
    "card": "#130A0A",
    "card_alt": "#1B0E0E",
    "card_hover": "#231212",
    "border": "#2C1414",
    "border_soft": "#1E0C0C",
    "text": "#F8F2F2",
    "text_dim": "#B3A0A0",
    "text_faint": "#6E5555",
    "accent": "#E51E2A",
    "accent_hover": "#FF3B47",
    "accent_press": "#A40F18",
    "accent_dark": "#1A0203",
    "danger": "#FF4D4D",
    "warning": "#FFB454",
    "amber": "#FFB454",
}


def _alpha(color: str, opacity: float) -> str:
    if color.startswith("#") and len(color) == 7:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return f"rgba({r}, {g}, {b}, {opacity:.2f})"
    return color


def build_admin_qss(t: dict | None = None) -> str:
    T = t or RED_BLACK
    accent_08 = _alpha(T["accent"], 0.08)
    accent_12 = _alpha(T["accent"], 0.12)
    accent_18 = _alpha(T["accent"], 0.18)
    accent_30 = _alpha(T["accent"], 0.30)
    accent_40 = _alpha(T["accent"], 0.40)
    accent_60 = _alpha(T["accent"], 0.60)
    return f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: {T["text"]};
}}
QMainWindow, QDialog {{
    background-color: {T["bg"]};
}}
QWidget {{
    background-color: transparent;
}}
QLabel {{
    background-color: transparent;
}}

/* ---------------- header ------------------ */
#Header {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #110606, stop:1 #0A0404);
    border-bottom: 1px solid {T["border"]};
}}
#BrandMark {{
    color: #FF6B70;
    font-family: "Segoe UI", "Space Grotesk", sans-serif;
    font-size: 19px;
    font-weight: 800;
    letter-spacing: 0.5px;
}}
#BrandSub {{
    color: {T["text_faint"]};
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.8px;
}}
#ServerPill {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 100px;
    padding: 5px 12px;
    color: {T["text_dim"]};
    font-size: 11px;
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
}}
#ConnDot {{
    border-radius: 5px;
}}

/* ---------------- cards ---------------- */
#Card {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 14px;
}}
#CardTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {T["text"]};
}}
#CardSub {{
    font-size: 11px;
    color: {T["text_faint"]};
}}
#StatValue {{
    font-size: 25px;
    font-weight: 800;
    color: {T["text"]};
}}
#StatLabel {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    color: {T["text_faint"]};
}}
#StatCard {{
    background-color: {T["card_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 14px;
}}
#StatCard#stat-active {{
    border: 1px solid {accent_40};
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent_12}, stop:1 {T["card_alt"]});
}}

/* ---------------- inputs ---------------- */
QLineEdit, QSpinBox, QComboBox, QTextEdit {{
    background-color: {T["bg_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 9px;
    padding: 8px 11px;
    color: {T["text"]};
    selection-background-color: {T["accent"]};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {accent_60};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {T["card_alt"]};
    border: 1px solid {T["border"]};
    selection-background-color: {accent_18};
    color: {T["text"]};
}}
QCheckBox {{
    color: {T["text_dim"]};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {T["border"]};
    border-radius: 4px;
    background-color: {T["bg_alt"]};
}}
QCheckBox::indicator:checked {{
    background-color: {T["accent"]};
    border-color: {T["accent"]};
}}

/* ---------------- buttons ---------------- */
QPushButton#Primary {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.5,
        stop:0 #F02834, stop:1 #B3121B);
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 10px 20px;
    font-size: 12.5px;
    font-weight: 700;
}}
QPushButton#Primary:hover:enabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.5,
        stop:0 #FF3F4B, stop:1 #C91822);
}}
QPushButton#Primary:disabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.5,
        stop:0 rgba(240,40,52,0.45), stop:1 rgba(179,18,27,0.45));
    color: rgba(255,255,255,0.55);
}}
QPushButton#Secondary {{
    background-color: {T["card"]};
    color: {T["text"]};
    border: 1px solid {T["border"]};
    border-radius: 10px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton#Secondary:hover:enabled {{
    background-color: {T["card_alt"]};
    border-color: {accent_40};
}}
QPushButton#Ghost {{
    background: transparent;
    color: {T["text_dim"]};
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 7px 13px;
    font-weight: 600;
}}
QPushButton#Ghost:hover:enabled {{
    color: {T["text"]};
    background-color: {accent_08};
}}
QPushButton#DangerGhost {{
    background: transparent;
    color: {T["danger"]};
    border: 1px solid {accent_30};
    border-radius: 9px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 700;
}}
QPushButton#DangerGhost:hover:enabled {{
    background-color: {accent_12};
}}
QPushButton#Chip {{
    background-color: {T["card_alt"]};
    color: {T["text_dim"]};
    border: 1px solid {T["border"]};
    border-radius: 7px;
    padding: 3px 9px;
    font-size: 11px;
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
}}
QPushButton#Chip:hover:enabled {{
    color: {T["text"]};
    border-color: {accent_40};
}}

/* ---------------- tables ---------------- */
QTableWidget {{
    background-color: {T["card"]};
    alternate-background-color: {T["bg_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
    gridline-color: {T["border_soft"]};
}}
QTableWidget::item {{
    padding: 6px 8px;
    color: {T["text_dim"]};
}}
QTableWidget::item:selected {{
    background-color: {accent_18};
    color: {T["text"]};
}}
QHeaderView::section {{
    background-color: {T["card_alt"]};
    color: {T["text_faint"]};
    border: none;
    border-bottom: 1px solid {T["border"]};
    padding: 8px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}}

/* ---------------- toast / status ---------------- */
#Toast {{
    background-color: #1A0A0A;
    border: 1px solid #3A1B1B;
    border-radius: 10px;
}}
#StatusBarWidget {{
    background-color: {T["bg_alt"]};
    border-top: 1px solid {T["border"]};
}}
#StatusText {{
    color: {T["text_dim"]};
    font-size: 11px;
}}
QLabel#KeyMono {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 12px;
    color: {T["text"]};
}}

/* ---------------- status pills ---------------- */
QLabel#Pill {{
    padding: 2px 9px;
    border-radius: 8px;
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QLabel#Pill[state="unused"] {{
    color: {T["text_faint"]};
    background-color: {_alpha(T["text_faint"], 0.10)};
    border: 1px solid {_alpha(T["text_faint"], 0.25)};
}}
QLabel#Pill[state="active"] {{
    color: #FF6B70;
    background-color: {accent_12};
    border: 1px solid {accent_40};
}}
QLabel#Pill[state="expired"] {{
    color: #FFCB7A;
    background-color: {_alpha("#FFB454", 0.10)};
    border: 1px solid {_alpha("#FFB454", 0.30)};
}}
QLabel#Pill[state="revoked"] {{
    color: {T["text_dim"]};
    background-color: {_alpha("#FFFFFF", 0.04)};
    border: 1px solid {T["border"]};
    text-decoration: line-through;
}}

/* ---------------- scrollbars ---------------- */
QScrollBar:vertical {{
    background: transparent; width: 7px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 40); border-radius: 3px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 70); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 7px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: rgba(255, 255, 255, 40); border-radius: 3px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background: rgba(255, 255, 255, 70); }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""


BASE_RED_QSS = build_admin_qss()


def repolish(widget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()