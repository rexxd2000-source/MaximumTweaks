"""Rex Tweaks QSS — one consistent monochromatic + single-accent design system.

Tokens live in config.app_config.THEME. Surfaces are built from neutrals
(deep obsidian -> translucent cards -> muted text). Color is used ONLY as the
single electric-cyan accent (#00F2FE) or as a small semantic signal:
  cyan = applied / enabled / active      red = incompatible / reverted
  amber = warning / restart required
"""
from config.app_config import THEME


def _alpha(color: str, opacity: float) -> str:
    if color.startswith("#") and len(color) == 7:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return f"rgba({r}, {g}, {b}, {opacity:.2f})"
    return color


T = THEME


def build_qss(theme: dict | None = None) -> str:
    if theme is None:
        theme = THEME
    T = theme
    accent_08 = _alpha(T["accent"], 0.08)
    accent_09 = _alpha(T["accent"], 0.09)
    accent_12 = _alpha(T["accent"], 0.12)
    accent_25 = _alpha(T["accent"], 0.25)
    accent_45 = _alpha(T["accent"], 0.45)
    accent_55 = _alpha(T["accent"], 0.55)
    accent_07 = _alpha(T["accent"], 0.07)
    return f"""
* {{
    font-family: "Segoe UI Variable Display", "Segoe UI Variable Text",
                 "Segoe UI", sans-serif;
    font-size: 13px;
    color: {T["text"]};
}}
QWidget {{
    background-color: transparent;
}}
QMainWindow, QDialog {{
    background-color: {T["bg"]};
}}

/* ---------------- Sidebar ---------------- */
#Sidebar {{
    background-color: {T["sidebar"]};
    border-right: 1px solid {T["border_soft"]};
}}
#BrandLogo {{
    background-color: {T["accent"]};
    color: {T["accent_dark"]};
    border-radius: 10px;
    font-size: 20px;
    font-weight: 900;
}}
#BrandTitle {{
    font-size: 16px;
    font-weight: 800;
    letter-spacing: 0.3px;
    color: {T["text"]};
}}
#BrandSub {{
    font-size: 9px;
    letter-spacing: 2px;
    color: {T["text_faint"]};
    font-weight: 700;
}}
QLabel#NavSection {{
    font-size: 9.5px;
    font-weight: 800;
    letter-spacing: 2px;
    color: {T["text_faint"]};
    padding: 10px 8px 4px 8px;
}}
#Nav {{
    background-color: transparent;
    border: none;
    border-radius: 9px;
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
    color: {T["text_dim"]};
}}
#Nav:hover {{
    background-color: {T["card"]};
    color: {T["text"]};
}}
#Nav[active="true"] {{
    background-color: {accent_08};
    border: none;
    border-left: 3px solid {T["accent"]};
    padding-left: 9px;
    color: {T["accent"]};
    font-weight: 700;
}}

#NavSub {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 7px 10px 7px 26px;
    text-align: left;
    font-size: 12.5px;
    font-weight: 600;
    color: {T["text_dim"]};
}}
#NavSub:hover {{
    background-color: {T["card"]};
    color: {T["text"]};
}}
#NavSub[active="true"] {{
    background-color: {accent_08};
    border: none;
    border-left: 2px solid {T["accent"]};
    padding-left: 24px;
    color: {T["accent"]};
    font-weight: 700;
}}

QPushButton#NavSectionBtn {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 14px 8px 4px 8px;
    text-align: left;
    font-size: 9.5px;
    font-weight: 800;
    letter-spacing: 2px;
    color: {T["text_faint"]};
}}
QPushButton#NavSectionBtn:hover {{
    color: {T["text"]};
}}

/* ---------------- Tweaks toolbar + pagination ---------------- */
QFrame#SearchBox {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 10px;
}}
QLabel#SearchIcon {{
    color: {T["text_dim"]};
    font-size: 14px;
}}
QLineEdit {{
    background: transparent;
    border: none;
    color: {T["text"]};
    padding: 0;
}}
QComboBox {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 10px;
    padding: 6px 10px;
    color: {T["text"]};
}}
QComboBox::drop-down {{
    border: none;
}}
QComboBox QAbstractItemView {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    selection-background-color: {accent_08};
}}
QPushButton#Primary {{
    background-color: {T["accent"]};
    color: {T["accent_dark"]};
    border: none;
    border-radius: 10px;
    padding: 8px 16px;
    font-weight: 700;
}}
QPushButton#Primary:hover:enabled {{
    background-color: {accent_55};
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
}}
QWidget#PageBar {{
    background-color: transparent;
    border-top: 1px solid {T["border"]};
    border-bottom: none;
    border-left: none;
    border-right: none;
}}
QWidget#PageBar QPushButton#PageNav, QWidget#PageBar QPushButton#PageNum {{
    min-width: 36px;
    min-height: 34px;
    padding: 0 10px;
    border-radius: 10px;
    border: 1px solid {T["border"]};
    background-color: {T["card"]};
    color: {T["text"]};
    font-weight: 600;
}}
QWidget#PageBar QPushButton#PageNav:hover:enabled, QWidget#PageBar QPushButton#PageNum:hover:enabled {{
    background-color: {T["card_alt"]};
    border-color: {accent_08};
}}
QWidget#PageBar QPushButton#PageNum[current="true"] {{
    background-color: {T["accent"]};
    color: {T["accent_dark"]};
    border-color: {T["accent"]};
}}
QPushButton#PageNav:disabled {{
    color: {T["text_dim"]};
    border-color: {T["border"]};
}}

/* ---------------- Recommend wizard ---------------- */
#RecFeedBox {{
    background-color: {T["bg_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
}}
#RecRow {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
}}
#RecRow:hover {{
    border-color: {accent_45};
}}
QProgressBar {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 8px;
    text-align: center;
    color: {T["text"]};
}}
QProgressBar::chunk {{
    background-color: {T["accent"]};
    border-radius: 7px;
}}

/* ---------------- Panels / cards ---------------- */
#Card, #Hero, #ProfileCard, #PerfCard, #ActionCard, #DiscordCard {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 14px;
}}
/* Discord account card under Settings is the one that should stand out:
   accent border + subtle accent wash from the top-left corner. */
#DiscordCard {{
    border: 1px solid {accent_45};
    background-color: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
        stop:0 {accent_07}, stop:0.45 {T["card"]}, stop:1 {T["card"]});
}}
#DiscordCard:hover {{
    border-color: {accent_55};
}}
#SysBar {{
    background-color: {T["card_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
}}
#Card:hover, #ActionCard:hover, #PerfCard:hover {{
    border-color: #2A313C;
    background-color: {T["card_alt"]};
}}
#Hero {{
    border-radius: 16px;
}}
#ProfileCard:hover {{
    border-color: #2A313C;
}}
#ProfileCard[active="true"] {{
    border: 1px solid {accent_55};
    background-color: #121720;
}}
#TweakCard, QFrame#tweak-card {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
}}
#TweakCard:hover, QFrame#tweak-card:hover {{
    border-color: #2A313C;
    background-color: {T["card_alt"]};
}}
#TweakCard[state="applied"], QFrame#tweak-card[state="applied"] {{
    border: 1px solid {accent_55};
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent_07}, stop:0.4 {T["card"]}, stop:1 {T["card"]});
}}
#TweakCard[state="reverted"], QFrame#tweak-card[state="reverted"] {{
    border: 1px solid rgba(248, 121, 121, 0.35);
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(248, 121, 121, 0.05), stop:0.4 {T["card"]}, stop:1 {T["card"]});
}}
#TweakCard[state="incompatible"], QFrame#tweak-card[state="incompatible"] {{
    border: 1px solid rgba(248, 121, 121, 0.40);
    opacity: 0.78;
}}
#TweakCard[state="detecting"], QFrame#tweak-card[state="detecting"] {{
    border: 1px dashed {T["border"]};
    background-color: {T["card_alt"]};
    opacity: 0.62;
}}

/* ---------------- Game list items (profiles split-pane) ---------------- */
#GameListItem {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}}
#GameListItem:hover {{
    background-color: {T["card"]};
    border-color: {T["border"]};
}}
#GameListItem[selected="true"] {{
    background-color: {accent_08};
    border: 1px solid {accent_45};
}}

#TintOverlay {{
    border-radius: 11px;
}}
#Toast {{
    background-color: #151B24;
    border: 1px solid #2A313C;
    border-radius: 10px;
}}

/* ---------------- Telemetry dashboard (glass cards) ---------------- */
#GlassCard {{
    background-color: rgba(17, 20, 26, 0.72);
    border: 1px solid #232A35;
    border-radius: 18px;
}}
#GlassCard:hover {{
    border-color: #2E3742;
}}
#SidebarDiscordCard {{
    background-color: {T["card"]};
    border: 1px solid {accent_45};
    border-radius: 14px;
}}
#GlassCardTitle {{
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: {T["text"]};
}}
#GaugeSub {{
    color: {T["text_dim"]};
    font-size: 12px;
}}
#LinkBtn {{
    background: transparent;
    border: none;
    color: {T["accent"]};
    font-size: 11.5px;
    font-weight: 700;
    padding: 0;
}}
#LinkBtn:hover {{
    color: {T["accent_hover"]};
}}
#TogglePill {{
    background-color: {T["bg_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 999px;
}}
#SegToggle {{
    background: transparent;
    border: none;
    border-radius: 999px;
    padding: 5px 14px;
    color: {T["text_faint"]};
    font-weight: 700;
}}
#SegToggle:hover {{
    color: {T["text_dim"]};
}}
#SegToggle[active="true"] {{
    background-color: {accent_12};
    color: {T["accent"]};
}}

/* ---------------- Typography ---------------- */
QLabel#PageTitle {{
    font-size: 24px;
    font-weight: 800;
    letter-spacing: 0.2px;
    color: {T["text"]};
}}
QLabel#PageSub {{
    font-size: 13px;
    color: {T["text_dim"]};
}}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1.8px;
    color: {T["text_faint"]};
}}
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: {T["text"]};
}}
QLabel#StatValue {{
    font-size: 26px;
    font-weight: 800;
    color: {T["text"]};
}}
QLabel#StatLabel {{
    font-size: 12px;
    color: {T["text_dim"]};
    font-weight: 600;
}}
QLabel#Tag {{
    color: {T["text_dim"]};
    font-size: 11.5px;
}}
QLabel#MutedLabel {{
    color: {T["text_dim"]};
    font-size: 13px;
}}
QLabel#ActiveProfileLabel {{
    color: {T["accent"]};
    font-weight: 800;
}}
QLabel#CardValue {{
    font-size: 20px;
    font-weight: 800;
    color: {T["text"]};
}}
QLabel#CardDetail {{
    font-size: 12px;
    color: {T["text_dim"]};
}}

/* ---------------- Chips / badges / pills ---------------- */
QLabel#Badge {{
    padding: 2px 8px;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.5px;
    color: #00F2FE;
    background-color: rgba(0, 242, 254, 0.08);
    border: 1px solid rgba(0, 242, 254, 0.25);
}}
QLabel#StatusPill {{
    padding: 3px 10px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.6px;
    color: #00F2FE;
    background-color: rgba(0, 242, 254, 0.08);
    border: 1px solid rgba(0, 242, 254, 0.25);
}}
QLabel#StatChip {{
    padding: 6px 12px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 500;
    color: #00F2FE;
    background-color: rgba(0, 242, 254, 0.08);
    border: 1px solid rgba(0, 242, 254, 0.25);
}}

/* ---------------- Pagination ---------------- */
/* ---------------- Buttons ---------------- */

/* ---------------- Scrollbars ---------------- */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 40);
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 70);
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 40);
    border-radius: 3px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{
    background: rgba(255, 255, 255, 70);
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

"""


BASE_QSS = build_qss()


def repolish(widget):
    """Re-evaluate QSS after a dynamic property change."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
