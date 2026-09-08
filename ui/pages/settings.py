"""Settings page — exact port of settings-premium.html.

Reproduces the reference layout with native system typography: #07050D backdrop
with violet/cyan glow blobs, Segoe UI Variable Display titles, JetBrains Mono mono
micro-labels, glass panels
(rgba(255,255,255,0.03) + 0.09 hairline borders), the 4-column info tile
grid with the reference's own SVG icon set, the violet license highlight
card, bordered card-lists with full-width hairline dividers, and the
cyan→violet gradient primary button.
"""
from __future__ import annotations

import ctypes
import datetime
import platform
import subprocess
import time

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import (
    APP_NAME,
    APP_VERSION,
    DIRS,
    DISCORD_INVITE_URL,
    ENGINE_NAME,
    LOG_FILE,
    current_windows_user,
)
from engine import license as license_mgr
from engine import state as state_mgr
from engine import telemetry
from ui.license import plan_label

# --- Reference palette (:root in settings-premium.html) --------------------
_BG = "#07050D"
_VIOLET = "#8B6BFF"
_VIOLET_SOFT = "#C9C0FF"
_CYAN = "#4BE8D8"
_GREEN = "#3DDC97"
_RED = "#FF6B6B"
_TEXT_1 = "#F5F3FB"
_TEXT_2 = "#A49BC4"
_TEXT_3 = "#615A80"

_DISPLAY = "Segoe UI, sans-serif"
_MONO = "JetBrains Mono, Cascadia Mono, monospace"

# Reference SVG paths (viewBox 0 0 24 24, stroke) — verbatim from the HTML.
REF_ICONS = {
    "clock": ('<circle cx="12" cy="12" r="9"/><path d="M12 8v5l3 2"/>', 1.8),
    "cpu": ('<rect x="4" y="4" width="16" height="16" rx="2"/>'
            '<path d="M9 9h6v6H9z"/>', 1.7),
    "gpu": ('<rect x="3" y="7" width="18" height="10" rx="2"/>'
            '<path d="M7 7v10M17 7v10"/>', 1.7),
    "ram": ('<rect x="4" y="9" width="16" height="6" rx="1"/>', 1.7),
    "storage": ('<rect x="3" y="4" width="18" height="6" rx="1"/>'
                '<rect x="3" y="14" width="18" height="6" rx="1"/>', 1.7),
    "os": ('<rect x="3" y="4" width="18" height="16" rx="2"/>'
           '<path d="M3 9h18"/>', 1.7),
    "uptime": ('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', 1.7),
    "check": ('<path d="M5 12l5 5 9-11"/>', 1.7),
    "bolt": ('<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>', 1.7),
}


def _ref_icon(name: str, color: str, size: int) -> QLabel:
    """A QLabel holding the reference's exact SVG icon, tinted to color."""
    paths, sw = REF_ICONS[name]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="{sw}" '
           f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r = QSvgRenderer()
    r.load(svg.encode("utf-8"))
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setPixmap(pm)
    lbl.setStyleSheet("background:transparent;border:none;")
    return lbl


def _tile_glyph(logo_kind, icon_name, color):
    """Bundled glossy logo PNG (assets/icons/<kind>.png) when one exists for
    this stat, else the reference line icon."""
    if logo_kind:
        path = DIRS["assets"] / "icons" / f"{logo_kind}.png"
        if path.is_file():
            pix = QPixmap(str(path))
            if not pix.isNull():
                scaled = pix.scaled(16, 16, Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation)
                lbl = QLabel()
                lbl.setFixedSize(16, 16)
                lbl.setPixmap(scaled)
                lbl.setStyleSheet("background:transparent;border:none;")
                return lbl
    return _ref_icon(icon_name, color, 13)


class _WrapLabel(QLabel):
    """Word-wrapped label that reports heightForWidth so siblings can never
    collide with wrapped lines (the classic Qt overlap bug)."""

    def __init__(self, text, maxw=None, parent=None):
        super().__init__(text, parent)
        self._maxw = maxw
        self.setWordWrap(True)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        w = min(width, self._maxw) if self._maxw else width
        fm = self.fontMetrics()
        r = fm.boundingRect(QRect(0, 0, max(1, w), 100000),
                            int(Qt.TextWordWrap), self.text())
        return int(r.height()) + 4

    def sizeHint(self):
        base = super().sizeHint()
        if self._maxw:
            base.setWidth(min(base.width(), self._maxw))
        return base


class _ElideLabel(QLabel):
    """Single-line label that ellipsizes to its width like CSS
    text-overflow (tile values in the reference never wrap)."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setMinimumHeight(self.fontMetrics().height() + 2)

    def set_text(self, text):
        self._full = text
        self.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        fm = self.fontMetrics()
        txt = fm.elidedText(self._full, Qt.ElideRight, max(10, self.width() - 2))
        self.setText(txt)


# ---------------------------------------------------------------------------
#  System probes (unchanged)
# ---------------------------------------------------------------------------

def _is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _cpu_name():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        return name.strip()
    except Exception:
        return "Unknown CPU"


def _gpu_name():
    try:
        out = subprocess.check_output(
            ["wmic", "path", "win32_videocontroller", "get",
             "name"], stderr=subprocess.DEVNULL, timeout=5,
            creationflags=0x08000000)
        lines = [l.strip() for l in out.decode(errors="ignore").splitlines()
                 if l.strip() and l.strip() != "Name"]
        return lines[0] if lines else "Unknown GPU"
    except Exception:
        return "Unknown GPU"


def _ram_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return "?"


def _uptime_str():
    try:
        import psutil
        secs = int(time.time() - psutil.boot_time())
        d = secs // 86400
        h = (secs % 86400) // 3600
        m = (secs % 3600) // 60
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        parts.append(f"{m}m")
        return " ".join(parts)
    except Exception:
        return "?"


def _disk_gb():
    try:
        import psutil
        d = psutil.disk_usage("/")
        return round(d.total / (1024**3), 0)
    except Exception:
        return "?"


def _win_version():
    try:
        return f"Windows {platform.version()}"
    except Exception:
        return "Windows"


# ---------------------------------------------------------------------------
#  Backdrop — .scene + .blob.a + .blob.b
# ---------------------------------------------------------------------------

class _Atmosphere(QWidget):
    """Flat #07050D base with the reference's two blurred glow blobs."""

    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(_BG))

        # violet blob: 520px, top:-220 left:-160 -> center ~(100, 40)
        ga = QRadialGradient(QPointF(100, 40), 380)
        ga.setColorAt(0.0, QColor(139, 107, 255, 60))
        ga.setColorAt(0.55, QColor(139, 107, 255, 18))
        ga.setColorAt(1.0, QColor(139, 107, 255, 0))
        p.fillRect(self.rect(), ga)

        # cyan blob: 480px, bottom:-240 right:-160 -> center (w-80, h)
        gb = QRadialGradient(QPointF(w - 80, h), 340)
        gb.setColorAt(0.0, QColor(75, 232, 216, 28))
        gb.setColorAt(0.6, QColor(75, 232, 216, 8))
        gb.setColorAt(1.0, QColor(75, 232, 216, 0))
        p.fillRect(self.rect(), gb)


# ---------------------------------------------------------------------------
#  Atoms
# ---------------------------------------------------------------------------

class GradientAvatar(QWidget):
    """.profile-avatar / .license-avatar: rounded gradient tile + letter."""

    def __init__(self, size, letter, mode="profile", parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._letter = (letter or "?")[0].upper()
        self._size = size
        self._mode = mode

    def set_letter(self, text):
        self._letter = (text or "?")[0].upper()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = 13 if self._mode == "profile" else 10
        rect = QRectF(0.5, 0.5, self._size - 1, self._size - 1)
        if self._mode == "profile":
            g = QLinearGradient(0, 0, self._size, self._size)
            g.setColorAt(0, QColor(139, 107, 255, 128))
            g.setColorAt(1, QColor(75, 232, 216, 51))
            p.setPen(Qt.NoPen)
        else:
            g = QLinearGradient(0, 0, self._size, self._size)
            g.setColorAt(0, QColor(139, 107, 255, 46))
            g.setColorAt(1, QColor(139, 107, 255, 46))
            p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(rect, r, r)
        f = QFont("Segoe UI", 18 if self._mode == "profile" else 14)
        f.setWeight(QFont.Bold)
        p.setFont(f)
        p.setPen(QColor(_TEXT_1 if self._mode == "profile" else _VIOLET_SOFT))
        p.drawText(self.rect(), Qt.AlignCenter, self._letter)


def _track(lbl: QLabel, px: float) -> QLabel:
    """Real letter-spacing (QSS cannot do it) for the reference's tracked-out
    mono micro-labels."""
    f = lbl.font()
    f.setLetterSpacing(QFont.AbsoluteSpacing, px)
    lbl.setFont(f)
    return lbl


def _badge(text):
    """.badge.violet"""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"font-family:{_MONO}; font-size:9.5px;"
        f" color:{_VIOLET_SOFT}; background-color:rgba(139,107,255,0.12);"
        f" border:1px solid rgba(139,107,255,0.30); border-radius:6px;"
        f" padding:3px 9px; font-weight:700;")
    return _track(lbl, 0.6)


def _tag(text, acc=False):
    """.row-title .tag / .tag.acc"""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        f"font-family:{_MONO}; font-size:10px; color:"
        f"{_VIOLET_SOFT if acc else _TEXT_3}; background:transparent;")
    return _track(lbl, 0.5)


def _section_head(icon_name, title, subtitle):
    """.section-head: optional 13px icon + mono h2 + 11.5px descriptor."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(9)
    if icon_name:
        lay.addWidget(_ref_icon(icon_name, _VIOLET_SOFT, 13), 0, Qt.AlignVCenter)
    h2 = QLabel(title.upper())
    h2.setStyleSheet(
        f"font-family:{_MONO}; font-size:11px;"
        f" color:{_TEXT_2}; font-weight:700; background:transparent;")
    _track(h2, 1.3)
    lay.addWidget(h2)
    p = QLabel(f"\u00b7 {subtitle}")
    p.setStyleSheet(
        f"font-size:11.5px; color:{_TEXT_3}; background:transparent;")
    lay.addWidget(p)
    lay.addStretch()
    return w


class _Tile(QFrame):
    """.info-tile: 26px bordered icon chip + 14.5px display weight-600 value +
    10.5px muted uppercase label — inside its own bordered glass block,
    exactly as the reference HTML (grid-template-columns:repeat(4,1fr))."""

    def __init__(self, icon_name, label, value, ok=False, logo=None,
                 parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("SetTile")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setStyleSheet(
            "#SetTile{background-color:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:13px;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(17, 16, 17, 16)
        lay.setSpacing(0)

        ic = QLabel()
        ic.setFixedSize(26, 26)
        color = _GREEN if ok else _VIOLET_SOFT
        inner = _tile_glyph(logo, icon_name, color)
        il = QHBoxLayout(ic)
        il.setContentsMargins(0, 0, 0, 0)
        il.setAlignment(Qt.AlignCenter)
        il.addWidget(inner)
        if ok:
            ic.setStyleSheet(
                "background-color:rgba(61,220,151,0.10);"
                " border:1px solid rgba(61,220,151,0.30); border-radius:8px;")
        else:
            ic.setStyleSheet(
                "background-color:rgba(139,107,255,0.10);"
                " border:1px solid rgba(139,107,255,0.22); border-radius:8px;")
        lay.addWidget(ic, 0, Qt.AlignLeft)
        lay.addSpacing(12)

        val = _ElideLabel(str(value))
        val.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:14.5px; font-weight:700;"
            f" color:{_TEXT_1}; background:transparent;")
        lay.addWidget(val)
        lay.addSpacing(3)

        lbl = QLabel(label.upper())
        lbl.setStyleSheet(
            f"font-size:10.5px; color:{_TEXT_3};"
            f" background:transparent;")
        _track(lbl, 0.5)
        lay.addWidget(lbl)


class _Row(QFrame):
    """.row: title(+tag)/desc left, control right. Lives inside a _CardList."""

    def __init__(self, title, desc, widget=None, tag=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent; border:none;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(20)

        box = QVBoxLayout()
        box.setSpacing(5)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(9)
        t = QLabel(title)
        t.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{_TEXT_1};"
            f" background:transparent;")
        top.addWidget(t)
        if tag is not None:
            top.addWidget(tag)
        top.addStretch()
        box.addLayout(top)

        d = _WrapLabel(desc, maxw=520)
        d.setStyleSheet(
            f"font-size:12.5px; color:{_TEXT_2}; background:transparent;")
        box.addWidget(d)

        lay.addLayout(box, 1)
        if widget is not None:
            lay.addWidget(widget, 0, Qt.AlignVCenter | Qt.AlignRight)


class _CardList(QFrame):
    """.card-list: one bordered container, full-width hairline dividers."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("SetCardList")
        self.setStyleSheet(
            "#SetCardList{background-color:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:14px;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, row in enumerate(rows):
            lay.addWidget(row)
            if i < len(rows) - 1:
                sep = QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(
                    "background-color:rgba(255,255,255,0.06); border:none;")
                lay.addWidget(sep)


class _LicenseCard(QFrame):
    """.license-card: violet-bordered highlight with the plan user."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("SetLicenseCard")
        self.setStyleSheet(
            "#SetLicenseCard{background:qlineargradient(x1:0,y1:0,x2:0.8,y2:1,"
            " stop:0 rgba(139,107,255,0.10), stop:1 rgba(75,232,216,0.03));"
            " border:1px solid rgba(139,107,255,0.35); border-radius:14px;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        label = QWidget()
        ll = QHBoxLayout(label)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        ll.addWidget(_ref_icon("bolt", _VIOLET_SOFT, 14), 0, Qt.AlignVCenter)
        lt = QLabel("License")
        lt.setStyleSheet(
            f"font-size:12.5px; color:{_TEXT_2}; font-weight:700;"
            f" background:transparent;")
        ll.addWidget(lt)
        top.addWidget(label)
        top.addStretch()

        status = QWidget()
        sl = QHBoxLayout(status)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(6)
        self._dot = QLabel()
        self._dot.setFixedSize(5, 5)
        self._dot.setStyleSheet(
            f"background-color:{_VIOLET_SOFT}; border-radius:3px;"
            f" border:none;")
        sl.addWidget(self._dot, 0, Qt.AlignVCenter)
        self._status_lbl = QLabel("LICENSED")
        self._status_lbl.setStyleSheet(
            f"font-family:{_MONO}; font-size:10px;"
            f" color:{_VIOLET_SOFT}; background:transparent;")
        _track(self._status_lbl, 0.6)
        sl.addWidget(self._status_lbl)
        top.addWidget(status)
        lay.addLayout(top)
        lay.addSpacing(14)

        user = QHBoxLayout()
        user.setContentsMargins(0, 0, 0, 0)
        user.setSpacing(12)
        self._avatar = GradientAvatar(36, "M", mode="license")
        user.addWidget(self._avatar, 0, Qt.AlignVCenter)
        meta = QVBoxLayout()
        meta.setSpacing(1)
        self._name = QLabel("—")
        self._name.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:15px; font-weight:700;"
            f" color:{_TEXT_1}; background:transparent;")
        self._plan = QLabel("Maximum Lifetime")
        self._plan.setStyleSheet(
            f"font-size:12px; color:{_VIOLET_SOFT}; background:transparent;")
        meta.addWidget(self._name)
        meta.addWidget(self._plan)
        user.addLayout(meta)
        user.addStretch()
        lay.addLayout(user)
        self.refresh()

    def refresh(self):
        sess = license_mgr.session()
        authorized = bool(sess and license_mgr.is_authorized())
        name = ""
        if authorized:
            try:
                name = license_mgr.owner_name(sess) or ""
            except Exception:
                name = ""
        if not name:
            name = current_windows_user()
        self._avatar.set_letter(name)
        self._name.setText(name)
        self._plan.setText(plan_label(sess) if authorized else "Not activated")
        self._status_lbl.setText("LICENSED" if authorized else "INACTIVE")
        c = _VIOLET_SOFT if authorized else _RED
        self._dot.setStyleSheet(
            f"background-color:{c}; border-radius:3px; border:none;")
        self._status_lbl.setStyleSheet(
            f"font-family:{_MONO}; font-size:10px; letter-spacing:1px;"
            f" color:{c}; background:transparent;")


# ---------------------------------------------------------------------------
#  Buttons (.btn / .btn.primary / .btn.danger)
# ---------------------------------------------------------------------------

def _btn(text, kind="default"):
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if kind == "primary":
        b.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0.3,"
            f" stop:0 {_CYAN}, stop:1 {_VIOLET}); color:#0A0714;"
            " border:none; border-radius:9px; padding:9px 16px;"
            " font-size:12.5px; font-weight:700;}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0.3,"
            f" stop:0 {_CYAN}, stop:1 {_VIOLET_SOFT});}}"
            "QPushButton:disabled{background:rgba(255,255,255,0.05);"
            f" color:{_TEXT_3};}}")
    elif kind == "danger":
        b.setStyleSheet(
            "QPushButton{background:rgba(255,107,107,0.06); color:" + _RED + ";"
            " border:1px solid rgba(255,107,107,0.35); border-radius:9px;"
            " padding:9px 16px; font-size:12.5px; font-weight:700;}"
            "QPushButton:hover{background:rgba(255,107,107,0.12);}"
            "QPushButton:disabled{color:#6b4a4a;"
            " border-color:rgba(255,107,107,0.15);}")
    else:
        b.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.03); color:" + _TEXT_1 + ";"
            " border:1px solid rgba(255,255,255,0.09); border-radius:9px;"
            " padding:9px 16px; font-size:12.5px; font-weight:700;}"
            "QPushButton:hover{background:rgba(255,255,255,0.06);"
            " border-color:rgba(255,255,255,0.18);}"
            "QPushButton:disabled{color:" + _TEXT_3 + ";}")
    return b


# ---------------------------------------------------------------------------
#  Page
# ---------------------------------------------------------------------------

class SettingsPage(QWidget):
    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._busy = False
        self._signout_btn = None
        self._signout_card = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._atmo = _Atmosphere(self)
        self._atmo.setGeometry(0, 0, 10, 10)
        self._atmo.lower()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        # .page styling from the reference, stretched to the content pane so
        # it doesn't read as a floating centered box inside the window.
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        root = QVBoxLayout(page)
        root.setContentsMargins(28, 48, 28, 70)
        root.setSpacing(0)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.addWidget(page)

        self._build_head(root)
        self._build_profile(root)
        self._build_system_info(root)
        self._build_account(root)
        self._build_data(root)
        self._build_updates(root)
        self._build_about(root)
        self._build_footer(root)
        root.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.ctx.license_changed.connect(self._on_license_changed)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._atmo.setGeometry(self.rect())
        self._atmo.lower()

    def _spacer(self, root, px):
        root.addSpacing(px)

    # ---- .page-head ----
    def _build_head(self, root):
        now = datetime.datetime.now()
        greeting = ("Good morning" if now.hour < 12 else
                    "Good afternoon" if now.hour < 17 else "Good evening")
        h1 = QLabel("Settings")
        h1.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:24px; font-weight:700;"
            f" color:{_TEXT_1}; background:transparent;")
        root.addWidget(h1)
        root.addSpacing(5)
        p = _WrapLabel(f"{greeting}, {current_windows_user()}. Manage your "
                       "account, system, and preferences below.")
        p.setStyleSheet(
            f"font-size:13.5px; color:{_TEXT_2}; background:transparent;")
        root.addWidget(p)
        root.addSpacing(26)

    # ---- .profile-card ----
    def _build_profile(self, root):
        card = QFrame()
        card.setObjectName("SetProfileCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            "#SetProfileCard{background-color:rgba(255,255,255,0.03);"
            " border:1px solid rgba(255,255,255,0.09); border-radius:16px;}")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        name = current_windows_user()
        lay.addWidget(GradientAvatar(48, name), 0, Qt.AlignVCenter)

        right = QVBoxLayout()
        right.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(10)
        nm = QLabel(name)
        nm.setStyleSheet(
            f"font-family:{_DISPLAY}; font-size:17px; font-weight:700;"
            f" color:{_TEXT_1}; background:transparent;")
        row.addWidget(nm)
        if _is_admin():
            row.addWidget(_badge("Admin"))
        licensed = bool(license_mgr.session() and license_mgr.is_authorized())
        if licensed:
            row.addWidget(_badge("Licensed"))
        row.addStretch()
        right.addLayout(row)

        spec = _WrapLabel(f"{_cpu_name()} \u00b7 {_ram_gb()} GB RAM")
        spec.setStyleSheet(
            f"font-size:12.5px; color:{_TEXT_3}; background:transparent;")
        right.addWidget(spec)

        lay.addLayout(right, 1)
        root.addWidget(card)
        root.addSpacing(28)

    # ---- System info ----
    def _build_system_info(self, root):
        root.addWidget(_section_head(
            "clock", "System info", "Your hardware at a glance"))
        root.addSpacing(14)

        applied_count = len(list(state_mgr.applied_ids()))
        try:
            restart = state_mgr.is_restart_required()
        except Exception:
            restart = False

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        # (line-icon, bundled logo PNG, label, value) — logo used when present.
        tiles = [
            ("cpu", "cpu", "CPU", _cpu_name()),
            ("gpu", "gpu", "GPU", _gpu_name()),
            ("ram", "ram", "Memory", f"{_ram_gb()} GB DDR"),
            ("storage", "storage", "Storage", f"{_disk_gb()} GB total"),
            ("os", "system", "OS", _win_version()),
            ("uptime", None, "Uptime", _uptime_str()),
            ("check", None, "Tweaks applied", f"{applied_count} active"),
        ]
        for i, (icon, logo, lbl, val) in enumerate(tiles):
            grid.addWidget(_Tile(icon, lbl, val, logo=logo), i // 4, i % 4)
        grid.addWidget(
            _Tile("bolt", "Status",
                  "Pending reboot" if restart else "System healthy",
                  ok=not restart, logo="performance"), 1, 3)
        for col in range(4):
            grid.setColumnStretch(col, 1)
        root.addLayout(grid)
        root.addSpacing(28)

    # ---- Account ----
    def _build_account(self, root):
        root.addWidget(_section_head(
            None, "Account", "License, privileges and session"))
        root.addSpacing(14)

        admin = _is_admin()
        btn_admin = None
        if not admin:
            from ui.main_window import relaunch_as_admin
            btn_admin = _btn("Relaunch as Admin", "primary")
            btn_admin.clicked.connect(relaunch_as_admin)
        admin_row = _Row(
            "Administrator privileges",
            "Elevated mode lets every tweak apply, including registry and "
            "service changes. Some optimizations require admin to function.",
            btn_admin,
            tag=_tag("Admin" if admin else "Standard user", acc=True))
        root.addWidget(_CardList([admin_row]))
        root.addSpacing(12)

        self._license_card = _LicenseCard()
        self._license_card.setObjectName("SetLicenseCard")
        root.addWidget(self._license_card)
        root.addSpacing(12)

        self._signout_btn = _btn("Sign out", "danger")
        self._signout_btn.clicked.connect(
            lambda: self._sign_out())
        self._signout_card = _CardList([_Row(
            "Sign out of this device",
            "Clear the local session and lock the app. You can reactivate "
            "at any time with your license key.",
            self._signout_btn)])
        root.addWidget(self._signout_card)
        root.addSpacing(28)
        self._refresh_signout()

    def _sign_out(self):
        from ui.license import deactivate
        deactivate(self.ctx, self)

    def _on_license_changed(self):
        if getattr(self, "_license_card", None) is not None:
            self._license_card.refresh()
        self._refresh_signout()

    def _refresh_signout(self):
        if self._signout_card is None:
            return
        authorized = bool(license_mgr.session() and license_mgr.is_authorized())
        self._signout_card.setVisible(authorized)
        if self._signout_btn is not None:
            self._signout_btn.setEnabled(authorized and not self._busy)

    # ---- Data & state ----
    def _build_data(self, root):
        root.addWidget(_section_head(
            None, "Data & state", "Manage applied tweaks and local data"))
        root.addSpacing(14)

        applied_count = len(list(state_mgr.applied_ids()))
        try:
            restart = state_mgr.is_restart_required()
        except Exception:
            restart = False

        b_reset = _btn("Reset")
        b_reset.clicked.connect(self._reset_applied)
        b_restart = _btn("Clear flag")
        b_restart.clicked.connect(self._clear_restart)
        b_temp = _btn("Clean")
        b_temp.clicked.connect(self._clean_temp)

        rows = [
            _Row("Applied tweaks",
                 "Tweaks marked as applied are tracked so they can be "
                 "reverted. Reset clears the tracking only \u2014 your "
                 "actual settings are not modified.",
                 b_reset,
                 tag=_tag(f"{applied_count} tracked")),
            _Row("Restart required",
                 "Some changes need a reboot to take effect. Once rebooted, "
                 "clear this flag to mark the system healthy again.",
                 b_restart,
                 tag=_tag("None" if not restart else "Pending")),
            _Row("Temporary files",
                 "Clear Windows temp files and leftover build artifacts to "
                 "free up disk space.",
                 b_temp),
        ]
        root.addWidget(_CardList(rows))
        root.addSpacing(28)

    # ---- Updates ----
    def _build_updates(self, root):
        root.addWidget(_section_head(
            None, "Updates", "Keep Maximum Tweaks current"))
        root.addSpacing(14)

        b_update = _btn("Check for updates", "primary")
        b_update.clicked.connect(self._check_updates)
        root.addWidget(_CardList([_Row(
            "Live updates",
            f"You\u2019re running {APP_NAME} v{APP_VERSION}. New builds are "
            "pushed to the server and applied in place with one click.",
            b_update,
            tag=_tag(f"v{APP_VERSION} installed", acc=True))]))
        root.addSpacing(28)

    # ---- About ----
    def _build_about(self, root):
        root.addWidget(_section_head(None, "About", "App info and community"))
        root.addSpacing(14)

        b_logs = _btn("View logs")
        b_logs.clicked.connect(lambda: self.navigate("logs"))
        b_discord = _btn("Join Discord")
        b_discord.clicked.connect(
            lambda: __import__("webbrowser").open(DISCORD_INVITE_URL))
        rows = [
            _Row(f"{APP_NAME} v{APP_VERSION} \u00b7 {ENGINE_NAME}",
                 f"Full log file: {LOG_FILE}",
                 b_logs),
            _Row("Community & support",
                 "Join the Discord server for real-time support, update "
                 "previews, and discussions with other users.",
                 b_discord),
        ]
        root.addWidget(_CardList(rows))
        root.addSpacing(36)

    # ---- Footer ----
    def _build_footer(self, root):
        f = QLabel(
            f'<span style="color:{_TEXT_3};">{APP_NAME} v{APP_VERSION} '
            f'\u00b7 Made with </span>'
            f'<span style="color:{_RED};">\u2665</span>'
            f'<span style="color:{_TEXT_3};"> by Maximum</span>')
        f.setTextFormat(Qt.RichText)
        f.setAlignment(Qt.AlignCenter)
        f.setStyleSheet(
            f"font-size:11.5px; color:{_TEXT_3}; background:transparent;")
        root.addWidget(f)

    # ---------------------------------------------------------------
    #  Actions
    # ---------------------------------------------------------------

    def set_busy(self, busy: bool):
        self._busy = busy
        if self._signout_btn is not None:
            self._signout_btn.setEnabled(not busy)
            self._signout_btn.setText("Signing out\u2026" if busy else "Sign out")

    def _confirm(self, title, text):
        return QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _reset_applied(self):
        if not self._confirm(
                "Reset applied state",
                "Reset the applied-tweak tracker? Applied settings will still be "
                "in effect \u2014 only the tracking is cleared."):
            return
        for tid in list(state_mgr.applied_ids()):
            state_mgr.unmark_applied(tid)
        self.ctx.note_state_change()

    def _clear_restart(self):
        state_mgr.clear_restart_required()
        self.ctx.note_state_change()

    def _clean_temp(self):
        try:
            result = telemetry.clean_temp_files()
            freed = result.get("freed_bytes", 0)
            mb = round(freed / (1024 * 1024), 1)
            QMessageBox.information(
                self, "Temp files cleaned",
                f"Freed {mb} MB of temporary files.")
        except Exception as exc:
            QMessageBox.warning(
                self, "Error", f"Could not clean temp files: {exc}")

    def _check_updates(self):
        from ui.updater_dialog import UpdateDialog
        UpdateDialog(self).exec()
