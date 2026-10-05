"""Maximum Tweaks QSS â€” one consistent deep-space + neon-violet design system.

Tokens live in config.app_config.THEME. Surfaces are built from dark
indigo-obsidian neutrals (translucent cards, muted text) with the neon
violet/magenta AI-page palette (#8B6BFF / #C484FF) as the single accent:
  violet = applied / enabled / active      red = incompatible / reverted
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
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: {T["text"]};
}}
QWidget {{
    background-color: transparent;
}}
QMainWindow, QDialog {{
    background-color: {T["bg"]};
}}

/* ---------------- Sidebar (color-coded design) ---------------- */
#Sidebar {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0B0814, stop:1 #07050D);
    border-right: 1px solid rgba(150, 130, 235, 0.10);
}}
#NavGlow {{
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 rgba(139, 107, 255, 0.16), stop:1 rgba(139, 107, 255, 0));
}}
#BrandMark {{
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.35, fy:0.3, stop:0 rgba(139, 107, 255, 0.38), stop:1 rgba(11, 8, 20, 0.9));
    border: 1px solid rgba(150, 130, 235, 0.35);
    color: #C3B3FF;
    border-radius: 19px;
    font-family: "Segoe UI", "Space Grotesk", sans-serif;
    font-size: 15px;
    font-weight: 700;
}}
#BrandTitle {{
    font-family: "Segoe UI", "Space Grotesk", sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.2px;
    color: {T["text"]};
}}
#BrandSub {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 9px;
    letter-spacing: 1.5px;
    color: {T["text_faint"]};
    font-weight: 700;
}}
QLabel#NavSectionLabel {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.3px;
    color: {T["text_faint"]};
    padding-top: 1px;
    padding-bottom: 1px;
}}
#NavLine {{
    background-color: rgba(150, 130, 235, 0.10);
}}
#NavRow {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
}}
#NavRow:hover {{
    background-color: rgba(255, 255, 255, 0.03);
}}
#NavRow[active="true"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(139, 107, 255, 0.16), stop:1 rgba(139, 107, 255, 0.03));
    border: 1px solid rgba(150, 130, 235, 0.18);
    border-left: 2.5px solid {T["accent"]};
}}
QLabel#NavIcon {{
    background-color: transparent;
}}
QLabel#NavText {{
    font-size: 13px;
    font-weight: 600;
    color: {T["text_dim"]};
    background-color: transparent;
}}
QLabel#NavText[hovered="true"] {{
    color: {T["text"]};
}}
QLabel#NavText[active="true"] {{
    color: {T["text"]};
    font-weight: 700;
}}
#SoonBadge {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #4BE8D8;
    background-color: rgba(75, 232, 216, 0.12);
    border: 1px solid rgba(75, 232, 216, 0.28);
    border-radius: 5px;
    padding: 2px 6px;
}}
#PlanPill {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #C3B3FF;
    background-color: rgba(139, 107, 255, 0.10);
    border: 1px solid rgba(195, 179, 255, 0.35);
    border-radius: 6px;
    padding: 2px 8px;
}}

QLabel#NewBadge {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: #051713;
    background-color: #10EBD9;
    border: 2px solid #10EBD9;
    border-radius: 7px;
    padding: 3px 10px;
}}

QLabel#UpdatedBadge {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: #2b1700;
    background-color: #FFB454;
    border: 2px solid #FFB454;
    border-radius: 7px;
    padding: 3px 10px;
}}

/* ---------------- Tweaks toolbar + pagination ---------------- */
QFrame#SearchBox {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-top: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
}}
QFrame#SearchBox:focus-within {{
    border-color: {accent_45};
    border-top: 1px solid rgba(196, 132, 255, 0.35);
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
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.35,
        stop:0 {T["accent"]}, stop:1 #6D4FE0);
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton#Primary:enabled {{
    border-top: 1px solid rgba(255, 255, 255, 0.22);
    border-bottom: 1px solid rgba(0, 0, 0, 0.25);
}}
QPushButton#Primary:hover:enabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.35,
        stop:0 #9C80FF, stop:1 #7C5FF0);
}}
QPushButton#Primary:pressed:enabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.35,
        stop:0 {T["accent_press"]}, stop:1 #5B3FC8);
}}
QPushButton#Primary:disabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0.35,
        stop:0 rgba(139,107,255,0.5), stop:1 rgba(109,79,224,0.5));
    color: rgba(255, 255, 255, 0.6);
}}
QPushButton#Secondary {{
    background-color: {T["card"]};
    color: {T["text"]};
    border: 1px solid {T["border"]};
    border-top: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 10px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton#Secondary:hover:enabled {{
    background-color: {T["card_alt"]};
}}
QPushButton#Secondary:pressed:enabled {{
    background-color: {T["card_hover"]};
    border-color: {T["border_hover"]};
}}
QPushButton#Ghost {{
    background: transparent;
    color: {T["text_dim"]};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#Ghost:hover:enabled {{
    color: {T["text"]};
    background-color: {accent_08};
    border-color: {accent_45};
}}
QPushButton#Ghost:pressed:enabled {{
    color: {T["text"]};
    background-color: {accent_12};
    border-color: {accent_55};
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
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #7C5FF0, stop:1 {T["accent"]});
    border-radius: 7px;
}}

/* ---------------- Panels / cards ---------------- */
#Card, #Hero, #ProfileCard, #ActionCard, #LicenseAccountCard, #GpuVendorCard {{
    background-color: {T["card"]};
    border: 1px solid {T["border"]};
    border-top: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 14px;
}}
/* Depth: layered gradient panel with a soft top-light edge (no blur costs). */
#Card {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.05), stop:0.14 rgba(255, 255, 255, 0.02),
        stop:1 {T["card"]});
}}
#Hero {{
    border-radius: 16px;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.06), stop:0.2 {T["card"]},
        stop:1 #0D0B14);
    border-top: 1px solid rgba(255, 255, 255, 0.14);
}}
#ProfileCard, #ActionCard, #GpuVendorCard {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 255, 255, 0.04), stop:0.16 {T["card"]},
        stop:1 {T["card"]});
}}
/* Dashboard license account card: same accent treatment as the old Discord card. */
#LicenseAccountCard {{
    border: 1px solid {accent_45};
    background-color: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
        stop:0 {accent_07}, stop:0.45 {T["card"]}, stop:1 {T["card"]});
}}
#LicenseAccountCard:hover {{
    border-color: {accent_55};
}}
#SysBar {{
    background-color: {T["card_alt"]};
    border: 1px solid {T["border"]};
    border-radius: 12px;
}}
#Card:hover, #ActionCard:hover {{
    border-color: {T["border_hover"]};
    background-color: {T["card_alt"]};
}}
#Hero {{
    border-radius: 16px;
}}
#ProfileCard:hover {{
    border-color: {T["border_hover"]};
}}
#ProfileCard[active="true"] {{
    border: 1px solid {accent_55};
    background-color: #121720;
}}
#TweakCard, QFrame#tweak-card {{
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.09);
    border-top: 1px solid rgba(255, 255, 255, 0.13);
    border-radius: 16px;
}}
#TweakCard:hover, QFrame#tweak-card:hover {{
    border-color: rgba(255, 255, 255, 0.16);
    background-color: rgba(255, 255, 255, 0.045);
}}
#TweakCard[state="applied"], QFrame#tweak-card[state="applied"] {{
    border: 1px solid rgba(74, 222, 128, 0.55);
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(74, 222, 128, 0.055), stop:0.4 rgba(255, 255, 255, 0.03), stop:1 rgba(255, 255, 255, 0.03));
    border-top: 1px solid rgba(74, 222, 128, 0.35);
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
    background-color: {T["toast_bg"]};
    border: 1px solid {T["border_hover"]};
    border-top: 1px solid rgba(255, 255, 255, 0.14);
    border-radius: 10px;
}}

/* ---------------- Telemetry dashboard (glass cards) ---------------- */
#GlassCard {{
    background-color: rgba(17, 20, 26, 0.72);
    border: 1px solid #232A35;
    border-top: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 18px;
}}
#GlassCard:hover {{
    border-color: #2E3742;
}}
/* Dashboard panel: flat solid card with a crisp single-accent border. */
#DashPanel {{
    background-color: #14121C;
    border: 1px solid #8B5CF6;
    border-radius: 14px;
}}
#DashStatusPill {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 rgba(255,255,255,0.07), stop:1 rgba(255,255,255,0.015));
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 100px;
    padding: 5px 12px;
    font-size: 12px;
    color: {T["text_dim"]};
}}
#DashChip {{
    background-color: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 8px;
    padding: 5px 11px;
    font-size: 12px;
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    color: {T["text_dim"]};
}}
#DashPanelTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {T["text"]};
}}
#DashPanelSub {{
    font-size: 12px;
    font-weight: 400;
    color: {T["text_faint"]};
}}
#DashMono {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
}}
QPushButton#DashPrimary {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #B79BFF, stop:1 #8266E8);
    color: #100B22;
    border: none;
    border-top: 1px solid rgba(255, 255, 255, 0.25);
    border-bottom: 1px solid rgba(0, 0, 0, 0.25);
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#DashPrimary:hover:enabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #C5AAFf, stop:1 #8F73F0);
}}
QPushButton#DashPrimary:pressed:enabled {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #9C85F0, stop:1 #6F55D8);
}}
QPushButton#DashGhost {{
    background-color: transparent;
    color: {T["text"]};
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 8px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#DashGhost:hover:enabled {{
    background-color: rgba(255,255,255,0.08);
}}
QPushButton#DashSmall {{
    background-color: rgba(255,255,255,0.04);
    color: {T["text"]};
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#DashSmall:hover:enabled {{
    background-color: rgba(255,255,255,0.08);
}}
#SidebarLicenseCard {{
    background-color: {T["card"]};
    border: 1px solid {accent_45};
    border-radius: 14px;
}}
#GlassCardTitle {{
    font-size: 14px;
    font-weight: 700;
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
    font-size: 12px;
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
    font-weight: 700;
    letter-spacing: 0.2px;
    color: {T["text"]};
}}
QLabel#PageSub {{
    font-size: 13px;
    color: {T["text_dim"]};
}}
QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.8px;
    color: {T["text_faint"]};
}}
QLabel#SectionTitle {{
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: {T["text"]};
}}
QLabel#StatValue {{
    font-size: 26px;
    font-weight: 700;
    color: {T["text"]};
}}
QLabel#StatLabel {{
    font-size: 12px;
    color: {T["text_dim"]};
    font-weight: 600;
}}
QLabel#Tag {{
    font-family: "JetBrains Mono", "Cascadia Mono", monospace;
    color: {T["text_faint"]};
    font-size: 9px;
    letter-spacing: 0.4px;
}}
QLabel#MutedLabel {{
    color: {T["text_dim"]};
    font-size: 13px;
}}
QLabel#ActiveProfileLabel {{
    color: {T["accent"]};
    font-weight: 700;
}}
QLabel#CardValue {{
    font-size: 20px;
    font-weight: 700;
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
    color: {T["accent"]};
    background-color: rgba(139, 92, 246, 0.08);
    border: 1px solid rgba(139, 92, 246, 0.25);
}}
QLabel#StatusPill {{
    padding: 3px 10px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.6px;
    color: {T["accent"]};
    background-color: rgba(139, 92, 246, 0.08);
    border: 1px solid rgba(139, 92, 246, 0.25);
}}
QLabel#StatChip {{
    padding: 6px 12px;
    border-radius: 9px;
    font-size: 12px;
    font-weight: 500;
    color: {T["accent"]};
    background-color: rgba(139, 92, 246, 0.08);
    border: 1px solid rgba(139, 92, 246, 0.25);
}}
QLabel#CatalogTag {{
    padding: 5px 11px;
    border-radius: 100px;
    font-family: 'JetBrains Mono', 'Cascadia Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    color: #9399A9;
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.09);
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
