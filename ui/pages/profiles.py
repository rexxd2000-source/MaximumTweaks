"""Game Profiles — premium per-game NIP driver profiles."""
from __future__ import annotations

import math
import traceback
from pathlib import Path

from PySide6.QtCore import (
    Qt, Signal, QThread, QPropertyAnimation, QEasingCurve,
    QRectF, QPointF, QTimer, Property,
)
from PySide6.QtGui import (
    QColor, QLinearGradient, QRadialGradient, QPainter, QPen, QBrush,
    QFont, QPainterPath, QPixmap,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget, QMessageBox, QStackedWidget,
)

from config.app_config import THEME as T
from engine import nvprofiles
from engine import state as state_mgr
from maxlog import logger

_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "profiles"
_LOGOS_DIR = Path(__file__).resolve().parents[2] / "assets" / "game_logos"


def _is_admin() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _rgba(h: str, a: int) -> str:
    c = h.lstrip("#")
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


# ═══════════════════════════════════════════════════════════════════════
#  NVIDIA PROFILE INSPECTOR LOCATOR
# ═══════════════════════════════════════════════════════════════════════

_NPI_EXE = "NVIDIA Profile Inspector.exe"

# Locations to probe for a packaged NVIDIA Profile Inspector build. The exe can
# move / be installed elsewhere, so the hardcoded dev path is only the first
# candidate — never the sole assumption.
_NPI_CANDIDATES = [
    Path(r"C:\Users\Admin\Documents\NVIDIA-Profile-Inspector\dist") / _NPI_EXE,
    Path(r"C:\Program Files\NVIDIA Profile Inspector") / _NPI_EXE,
    Path(r"C:\Program Files (x86)\NVIDIA Profile Inspector") / _NPI_EXE,
]


def _find_npi_exe() -> Path | None:
    """Locate the NVIDIA Profile Inspector executable.

    Searches known locations and the Windows uninstall registry so the path is
    never blindly hardcoded. Returns a ``Path`` when found, else ``None``.
    """
    for cand in _NPI_CANDIDATES:
        if cand.is_file():
            return cand
    # Registry uninstall entries (DisplayIcon) — catches custom install dirs.
    try:
        import winreg
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for key in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    with winreg.OpenKey(root, key) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            sub = winreg.EnumKey(k, i)
                            try:
                                with winreg.OpenKey(k, sub) as sk:
                                    icon = ""
                                    try:
                                        icon, _ = winreg.QueryValueEx(sk, "DisplayIcon")
                                    except OSError:
                                        pass
                                    if icon:
                                        p = Path(str(icon).strip('"'))
                                        if p.is_file() and _NPI_EXE.lower() in p.name.lower():
                                            return p
                            except OSError:
                                continue
                except OSError:
                    continue
    except Exception:  # noqa: BLE001
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════
#  LOGOS
# ═══════════════════════════════════════════════════════════════════════

_logo_cache: dict[str, QPixmap | None] = {}


def _logo(name: str) -> QPixmap | None:
    key = name.lower().replace(" ", "").replace("'", "")
    if key in _logo_cache:
        return _logo_cache[key]
    for pat in [key, name.lower().replace(" ", "_")]:
        for ext in (".png", ".jpg"):
            p = _LOGOS_DIR / f"{pat}{ext}"
            if p.exists():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    _logo_cache[key] = pm
                    return pm
    _logo_cache[key] = None
    return None


_COLORS = {
    "Fortnite": "#9333EA",
    "Valorant": "#FF4655",
    "CS2": "#E8A317",
}


def _color(name: str) -> str:
    return _COLORS.get(name, T["accent"])


_GAME_INFO = {
    "Fortnite": {
        "desc": "More FPS, way less input delay, zero stuttering. GPU stays "
                "pinned at max clocks so you never drop frames mid-fight.",
    },
    "CS2": {
        "desc": "A general competitive setup. Turns off the things that add "
                "delay and keeps your framerate steady, so the game just "
                "feels cleaner and more responsive overall.",
    },
    "Valorant": {
        "desc": "A general competitive setup. Focuses on lowering input "
                "delay and keeping framerate stable, so aiming feels more "
                "direct and consistent during a game.",
    },
}


# ═══════════════════════════════════════════════════════════════════════
#  NIP LOADER
# ═══════════════════════════════════════════════════════════════════════

def _load_nips() -> dict:
    try:
        from engine.nip_parser import load_all_profiles
        return load_all_profiles(_ASSETS_DIR)
    except Exception:
        return {}


class _Loader(QThread):
    done = Signal(dict)
    def run(self):
        self.done.emit(_load_nips())


# ═══════════════════════════════════════════════════════════════════════
#  APPLY BUTTON
# ═══════════════════════════════════════════════════════════════════════

class _ApplyBtn(QPushButton):
    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self._state = "idle"
        self._dot_n = 0.0
        self._auto = QTimer(self)
        self._auto.setSingleShot(True)
        self._auto.timeout.connect(self._reset_idle)
        self._spin = QTimer(self)
        self._spin.timeout.connect(self._spin_tick)

        self.setFixedSize(170, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("  Apply Profile")
        self._style_idle()

    def set_state(self, s: str):
        self._state = s
        self._auto.stop()
        self._spin.stop()
        if s == "idle":
            self.setText("  Apply Profile")
            self._style_idle()
        elif s == "applying":
            self._dot_n = 0
            self.setText("Applying...")
            self._style_muted()
            self._spin.start(60)
        elif s == "applied":
            self.setText("  Applied!")
            self._style_success()
            self._auto.start(2800)
        elif s == "error":
            self.setText("  Failed")
            self._style_error()
            self._auto.start(3500)

    def _reset_idle(self):
        self.set_state("idle")

    def _spin_tick(self):
        self._dot_n += 1
        d = "." * (1 + self._dot_n % 3)
        self.setText(f"Applying{d}")

    def _style_idle(self):
        cn = self._accent
        cl = QColor(cn).lighter(130).name()
        ch = QColor(cn).lighter(115).name()
        cd = QColor(cn).darker(112).name()
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {cd}, stop:0.3 {cn}, stop:0.7 {cl}, stop:1 {cn});
                color: #fff; border: 2px solid {_rgba(cn, 0x50)};
                border-radius: 10px; font-size: 13px; font-weight: 700;
                letter-spacing: 0.5px; padding: 0 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {cn}, stop:0.5 {cl}, stop:1 {ch});
                border-color: {_rgba(cn, 0x80)};
            }}
            QPushButton:pressed {{ background: {cd}; border-color: {cn}; }}
        """)

    def _style_muted(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background: {T['bg_alt']}; color: {T['text_dim']};
                border: 2px solid {T['border']}; border-radius: 10px;
                font-size: 13px; font-weight: 700;
            }}
        """)

    def _style_success(self):
        bg = T.get("success", "#16A34A")
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: #fff;
                border: 2px solid {_rgba(bg, 0x60)}; border-radius: 10px;
                font-size: 13px; font-weight: 700;
            }}
        """)

    def _style_error(self):
        bg = T.get("danger", "#DC2626")
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: #fff;
                border: 2px solid {_rgba(bg, 0x60)}; border-radius: 10px;
                font-size: 13px; font-weight: 700;
            }}
        """)


# ═══════════════════════════════════════════════════════════════════════
#  GAME CARD
# ═══════════════════════════════════════════════════════════════════════

class GameCard(QFrame):
    apply_clicked = Signal(str)
    reset_clicked = Signal(str)
    explore_clicked = Signal(str)

    def __init__(self, gid: str, nip=None, parent=None):
        super().__init__(parent)
        self.gid = gid
        self.nip = nip
        meta = nvprofiles.GAMES.get(gid, {})
        self.gname = meta.get("name", gid)
        self.exes = meta.get("exes", [])
        self._c = QColor(_color(self.gname))
        ginfo = _GAME_INFO.get(self.gname, {})
        self.desc = ginfo.get("desc", "")
        self._hv = 0.0
        self._applied = state_mgr.get_nv_profile_snapshot(gid) is not None
        self._pulse = 0.0

        self.setFixedHeight(170)
        self.setMouseTracking(True)

        self._anim = QPropertyAnimation(self, b"hv")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self._ptimer = QTimer(self)
        self._ptimer.timeout.connect(self._tick)
        self._ptimer.start(40)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        logo_frame = QFrame()
        logo_frame.setFixedWidth(130)
        logo_frame.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(logo_frame)

        info = QVBoxLayout()
        info.setContentsMargins(4, 14, 16, 14)
        info.setSpacing(2)

        r1 = QHBoxLayout()
        r1.setSpacing(10)
        name_lbl = QLabel(self.gname)
        name_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {T['text']}; "
            "background: transparent; border: none; letter-spacing: -0.3px;")
        r1.addWidget(name_lbl)

        if self._applied:
            snap = state_mgr.get_nv_profile_snapshot(gid)
            st = f"Applied  {snap.get('applied_at', '')}" if snap else "Applied"
            sc = T.get("success", "#4ADE80")
        else:
            st = "Ready"
            sc = T["text_faint"]
        sl = QLabel(st)
        sl.setStyleSheet(
            f"color: {sc}; font-size: 9px; font-weight: 600; letter-spacing: 1px; "
            "background: transparent; border: none;")
        r1.addWidget(sl)
        r1.addStretch()
        info.addLayout(r1)

        if self.desc:
            d = QLabel(self.desc)
            d.setStyleSheet(
                f"color: {T['text_dim']}; font-size: 10.5px; line-height: 1.4; "
                "background: transparent; border: none;")
            d.setWordWrap(True)
            info.addWidget(d)

        set_n = len(nip.settings) if nip else 0
        exe_str = ", ".join(self.exes[:2]) if self.exes else ""
        detail = f"{set_n} driver settings"
        if exe_str:
            detail += f"  \u00b7  {exe_str}"
        dl = QLabel(detail)
        dl.setStyleSheet(
            f"color: {T['text_faint']}; font-size: 9.5px; "
            "background: transparent; border: none;")
        info.addWidget(dl)

        info.addStretch()

        reset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset")
        reset_btn.setObjectName("ResetBtn")
        reset_btn.setFixedSize(56, 28)
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(lambda: self.reset_clicked.emit(self.gid))
        reset_row.addWidget(reset_btn)
        reset_row.addStretch()
        info.addLayout(reset_row)

        outer.addLayout(info, 1)

        self._apply_btn = _ApplyBtn(self._c.name())
        self._apply_btn.clicked.connect(lambda: self.apply_clicked.emit(self.gid))

        explore_btn = QPushButton("Explore More")
        explore_btn.setObjectName("ExploreBtn")
        explore_btn.setFixedSize(108, 32)
        explore_btn.setCursor(Qt.PointingHandCursor)
        explore_btn.clicked.connect(lambda: self.explore_clicked.emit(self.gid))

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 16, 0)
        right_col.setSpacing(8)
        right_col.addStretch(1)
        right_col.addWidget(self._apply_btn, 0, Qt.AlignRight)
        right_col.addWidget(explore_btn, 0, Qt.AlignRight)
        right_col.addStretch(1)
        outer.addLayout(right_col)

        cn = self._c.name()
        self.setStyleSheet(f"""
            QPushButton#ResetBtn {{
                background: transparent; color: {T['text_faint']};
                border: 1px solid {_rgba(T['text_faint'], 0x25)}; border-radius: 6px;
                font-size: 10px; font-weight: 600;
            }}
            QPushButton#ResetBtn:hover {{
                background: {T['card_hover']}; color: {T['text']};
                border-color: {T['text_faint']};
            }}
            QPushButton#ExploreBtn {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {_rgba(T["accent"], 0x28)},
                    stop:1 {_rgba(T["accent"], 0x14)});
                color: {T["accent"]};
                border: 1px solid {_rgba(T["accent"], 0x55)}; border-radius: 8px;
                font-size: 11px; font-weight: 700;
            }}
            QPushButton#ExploreBtn:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {_rgba(T["accent"], 0x42)},
                    stop:1 {_rgba(T["accent"], 0x28)});
                color: #fff;
                border-color: {T["accent"]};
            }}
        """)

    def _tick(self):
        self._pulse += 0.08
        if self._applied:
            self.update()

    def _get_hv(self):
        return self._hv

    def _set_hv(self, v):
        self._hv = v
        self.update()

    hv = Property(float, _get_hv, _set_hv)

    def enterEvent(self, e):
        self._anim.setStartValue(self._hv)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, e):
        self._anim.setStartValue(self._hv)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        R = 12.0
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, R, R)
        hv = self._hv
        c = self._c

        bg0 = QColor(T["card"])
        bg1 = QColor(T["card_hover"])
        bg = QColor(
            int(bg0.red() + (bg1.red() - bg0.red()) * hv),
            int(bg0.green() + (bg1.green() - bg0.green()) * hv),
            int(bg0.blue() + (bg1.blue() - bg0.blue()) * hv),
        )
        p.fillPath(path, bg)

        wa = 0.03 + hv * 0.05
        gw = QLinearGradient(0, 0, w * 0.45, h * 0.8)
        gw.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(255 * wa)))
        gw.setColorAt(0.4, QColor(c.red(), c.green(), c.blue(), 0))
        p.fillPath(path, gw)

        bar = QPainterPath()
        bar.addRoundedRect(QRectF(0, 14, 2.5, h - 28), 1.25, 1.25)
        p.fillPath(bar, QColor(c.red(), c.green(), c.blue(), int(50 + hv * 90)))

        bdr = int(20 + hv * 50)
        gb = QLinearGradient(0, 0, w, h)
        gb.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), bdr))
        gb.setColorAt(0.4, QColor(255, 255, 255, int(1 + hv * 6)))
        gb.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), int(bdr * 0.25)))
        p.setPen(QPen(QBrush(gb), 0.6 + hv * 0.3))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, R, R)

        if self._applied:
            pulse = (math.sin(self._pulse) + 1) / 2
            p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(12 + pulse * 16)), 3))
            p.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), R + 1, R + 1)

        logo_px = 76.0
        logo_x = (130 - logo_px) / 2.0
        logo_y = (h - logo_px) / 2.0
        logo_rect = QRectF(logo_x, logo_y, logo_px, logo_px)
        logo_R = 16.0

        glow = QRadialGradient(65.0, h / 2.0, logo_px * 0.7)
        glow.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 22))
        glow.setColorAt(0.6, QColor(c.red(), c.green(), c.blue(), 6))
        glow.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(logo_rect.adjusted(-10, -10, 10, 10), logo_R + 4, logo_R + 4)

        logo = _logo(self.gname)
        if logo and not logo.isNull():
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(logo_rect, logo_R, logo_R)
            p.setClipPath(clip)
            lw, lh = logo.width(), logo.height()
            scale = max(logo_px / lw, logo_px / lh)
            sw, sh = int(lw * scale), int(lh * scale)
            scaled = logo.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            dx = logo_x + (logo_px - scaled.width()) / 2
            dy = logo_y + (logo_px - scaled.height()) / 2
            p.drawPixmap(int(dx), int(dy), scaled)
            p.restore()
            p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(30 + hv * 40)), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(logo_rect, logo_R, logo_R)
        else:
            grad = QRadialGradient(logo_x + logo_px * 0.4, logo_y + logo_px * 0.4, logo_px * 0.6)
            grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue()))
            grad.setColorAt(1.0, QColor(max(0, c.red() - 50),
                                         max(0, c.green() - 50),
                                         max(0, c.blue() - 50)))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(logo_rect, logo_R, logo_R)
            p.setPen(QColor(255, 255, 255, 220))
            f = QFont("Segoe UI", 26, QFont.Weight.Bold)
            p.setFont(f)
            p.drawText(logo_rect, Qt.AlignCenter, self.gname[0].upper())

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(18 + hv * 25)), 1.0))
        p.drawLine(130, 20, 130, h - 20)

        p.end()


# ═══════════════════════════════════════════════════════════════════════
#  EXPLORE MORE
# ═══════════════════════════════════════════════════════════════════════

_EXPLORE = {
    "Fortnite": [
        {
            "preset": "potato",
            "title": "Potato Graphics",
            "tag": "MAX FPS",
            "desc": "Potato graphics for low end PCs. Textures, AA and shadows "
                    "turned way down so even a weak PC holds a steady high FPS. "
                    "Made for low-spec rigs or stretched-res players.",
            "badge": "INSTALLED",
        },
    ],
    "CS2": [],
    "Valorant": [
        {
            "preset": "potato",
            "title": "Potato Graphics",
            "tag": "MAX FPS",
            "desc": "For older or weaker PCs. Turns off anti-aliasing, "
                    "ambient occlusion and other visual effects so the game "
                    "runs faster. Lowers the graphics quality a fair amount, "
                    "but you gain a good chunk of performance.",
            "badge": "INSTALLED",
        },
    ],
}

_EXPLORE_COMING = {
    "CS2": "More CS2 profiles coming soon.",
}


class ExplorePage(QWidget):
    back_clicked = Signal()
    apply_explore = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        hero = QFrame()
        hero.setFixedHeight(68)
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:0.7,y2:1,
                    stop:0 {_rgba(T["accent"], 0x0A)},
                    stop:0.3 {T['card']},
                    stop:1 {T['card']});
                border: 1px solid {_rgba(T["accent"], 0x18)};
                border-radius: 12px;
            }}
        """)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(22, 8, 22, 8)
        hl.setSpacing(12)

        back_btn = QPushButton("\u2190  Back")
        back_btn.setObjectName("BackBtn")
        back_btn.setFixedSize(96, 32)
        back_btn.setCursor(Qt.PointingHandCursor)
        back_btn.clicked.connect(self.back_clicked)
        hl.addWidget(back_btn)

        ht = QVBoxLayout()
        ht.setSpacing(2)
        t1 = QLabel("Explore More")
        t1.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {T['text']}; "
            "background: transparent; border: none; letter-spacing: -0.3px;")
        ht.addWidget(t1)
        t2 = QLabel("Extra driver presets beyond the main profile")
        t2.setStyleSheet(
            f"font-size: 11px; color: {T['text_dim']}; background: transparent; border: none;")
        ht.addWidget(t2)
        ht.addStretch()
        hl.addLayout(ht, 1)
        root.addWidget(hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        self._cw = QWidget()
        self._cw.setStyleSheet("background: transparent;")
        self._clay = QVBoxLayout(self._cw)
        self._clay.setContentsMargins(0, 0, 0, 0)
        self._clay.setSpacing(10)
        scroll.setWidget(self._cw)
        root.addWidget(scroll, 1)

        self.setStyleSheet(f"""
            QPushButton#BackBtn {{
                background: {T['card']}; color: {T['text_dim']};
                border: 1px solid {T['border']}; border-radius: 8px;
                font-size: 12px; font-weight: 700;
            }}
            QPushButton#BackBtn:hover {{
                background: {T['card_hover']}; color: {T['text']};
                border-color: {_rgba(T["accent"], 0x4A)};
            }}
        """)

    def set_game(self, gid: str):
        while self._clay.count():
            it = self._clay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        from ui.categories import GAME_PROFILE_IDS
        gname = nvprofiles.GAMES.get(gid, {}).get("name", gid)
        presets = _EXPLORE.get(gname, [])
        coming = _EXPLORE_COMING.get(gname)

        if not presets and not coming:
            empty = QLabel(f"No extra presets for {gname} yet.")
            empty.setStyleSheet(
                f"color: {T['text_faint']}; font-size: 12px; "
                "background: transparent; border: none; padding: 20px 4px;")
            self._clay.addWidget(empty)
            self._clay.addStretch()
            return

        for pr in presets:
            card = ExploreCard(gid, pr)
            card.apply_clicked.connect(self.apply_explore)
            self._clay.addWidget(card)
        if coming:
            card = ComingSoonCard(gid, coming)
            self._clay.addWidget(card)
        self._clay.addStretch()


class _ComingSoonBase(QFrame):
    """Shared robust base for cinematic 'coming soon' style cards.

    Fully opaque painting + guarantee that paint errors never blank the
    widget (which made earlier versions 'disappear' on hover).
    """

    _BG = QColor("#0A0C11")
    _BG_HOVER = QColor("#13161F")
    _GOLD = QColor(255, 214, 120)
    _LAV = QColor(167, 139, 250)
    R = 16.0

    def __init__(self, accent: str, height: int, parent=None):
        super().__init__(parent)
        self._c = QColor(accent)
        self._hv = 0.0
        self._ph = 0.0

        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAutoFillBackground(False)

        self._anim = QPropertyAnimation(self, b"hv")
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self._ptimer = QTimer(self)
        self._ptimer.timeout.connect(self._tick)
        self._ptimer.start(50)

    def _tick(self):
        self._ph += 0.04
        if self._ph > 100000.0:
            self._ph = 0.0
        self.update()

    def _get_hv(self):
        return self._hv

    def _set_hv(self, v):
        v = min(1.0, max(0.0, v))
        self._hv = v
        self.update()

    hv = Property(float, _get_hv, _set_hv)

    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hv)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._hv)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, event):
        try:
            self._paint()
        except Exception:
            import traceback as _tb
            logger.error(f"profiles: {type(self).__name__} paint failed:\n{_tb.format_exc()}")

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        border = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath()
        path.addRoundedRect(border, self.R, self.R)
        hv = self._hv
        c = self._c

        bg = QColor(
            int(self._BG.red() + (self._BG_HOVER.red() - self._BG.red()) * hv),
            int(self._BG.green() + (self._BG_HOVER.green() - self._BG.green()) * hv),
            int(self._BG.blue() + (self._BG_HOVER.blue() - self._BG.blue()) * hv),
        )
        p.fillPath(path, bg)

        gw = QLinearGradient(0, 0, w * 0.6, h)
        gw.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(14 + hv * 16)))
        gw.setColorAt(0.6, QColor(c.red(), c.green(), c.blue(), 0))
        p.fillPath(path, gw)

        for i in range(2):
            yy = self._ph * 55 + i * 52
            ga = QRadialGradient(w * 0.5, yy, 190)
            ga.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(3 + hv * 5)))
            ga.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillPath(path, QBrush(ga))

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(26 + hv * 46)), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(border, self.R, self.R)

        self._draw_content(p, w, h, hv, c)
        p.end()

    def _draw_content(self, p, w, h, hv, c):
        raise NotImplementedError

    def _draw_rule(self, p, w, y, hv, c, half=170, thick=2.0):
        a = int(50 + hv * 110)
        col = QColor(c.red(), c.green(), c.blue(), a)
        p.setPen(QPen(col, thick))
        x1 = int(w * 0.5) - half
        x2 = int(w * 0.5) - half + 100
        p.drawLine(x1, int(y), x2, int(y))
        p.drawLine(int(w * 0.5) + half - 100, int(y), int(w * 0.5) + half, int(y))


class ComingSoonCard(_ComingSoonBase):
    """Cinematic 'coming soon' teaser card (shown in the Explore tab)."""

    def __init__(self, gid: str, note: str, parent=None):
        meta = nvprofiles.GAMES.get(gid, {})
        self.gname = meta.get("name", gid)
        self.note = note
        self._c0 = _color(self.gname)
        super().__init__(self._c0, 170, parent)

    def _draw_content(self, p, w, h, hv, c):
        self._draw_rule(p, w, 24, hv, c)

        flick = 0.75 + 0.25 * math.sin(self._ph * 1.7)
        p.setPen(QPen(self._GOLD, 1))
        ff = QFont("Segoe UI", 13, QFont.Weight.Bold)
        ff.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        p.setFont(ff)
        p.drawText(QRectF(0, 32, w, 30), Qt.AlignCenter, "COMING SOON")

        logo_px = 52.0
        logo_x = (w - logo_px) / 2.0
        logo_y = 78.0
        logo_rect = QRectF(logo_x, logo_y, logo_px, logo_px)
        logo_R = 12.0

        glow = QRadialGradient(w / 2.0, logo_y + logo_px / 2, logo_px * 0.9)
        glow.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(30 + 34 * flick)))
        glow.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawRoundedRect(logo_rect.adjusted(-12, -12, 12, 12), logo_R + 4, logo_R + 4)

        logo = _logo(self.gname)
        if logo and not logo.isNull():
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(logo_rect, logo_R, logo_R)
            p.setClipPath(clip)
            lw, lh = logo.width(), logo.height()
            scale = max(logo_px / lw, logo_px / lh)
            sw, sh = int(lw * scale), int(lh * scale)
            scaled = logo.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            dx = logo_x + (logo_px - scaled.width()) / 2
            dy = logo_y + (logo_px - scaled.height()) / 2
            p.drawPixmap(int(dx), int(dy), scaled)
            p.restore()
        else:
            grad = QRadialGradient(logo_x + logo_px * 0.4, logo_y + logo_px * 0.4, logo_px * 0.6)
            grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue()))
            grad.setColorAt(1.0, QColor(max(0, c.red() - 50), max(0, c.green() - 50), max(0, c.blue() - 50)))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(logo_rect, logo_R, logo_R)

        p.setPen(QColor(255, 255, 255, int(60 + 120 * hv)))
        f = QFont("Segoe UI", 10, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRectF(0, 132, w, 18), Qt.AlignCenter, self.gname)

        p.setPen(QColor(self._LAV.red(), self._LAV.green(), self._LAV.blue(), int(80 + 140 * hv)))
        fs = QFont("Segoe UI", 11, QFont.Weight.Medium)
        p.setFont(fs)
        p.drawText(QRectF(0, 150, w, 18), Qt.AlignCenter, self.note)


class MoreComingSoonCard(_ComingSoonBase):
    """Cinematic centered 'more coming soon' teaser for the main profile list."""

    def __init__(self, note="More profiles on the way", parent=None):
        super().__init__(T["accent"], 150, parent)
        self.note = note

    def _draw_content(self, p, w, h, hv, c):
        self._draw_rule(p, w, 26, hv, c, half=190, thick=1.5)

        flick = 0.75 + 0.25 * math.sin(self._ph * 1.7)
        p.setPen(QPen(self._GOLD, 1))
        ff = QFont("Segoe UI", 15, QFont.Weight.Bold)
        ff.setLetterSpacing(QFont.AbsoluteSpacing, 7)
        p.setFont(ff)
        p.drawText(QRectF(0, 40, w, 32), Qt.AlignCenter, "MORE  COMING  SOON")

        p.setPen(QColor(self._LAV.red(), self._LAV.green(), self._LAV.blue(), int(80 + 150 * hv)))
        fs = QFont("Segoe UI", 12, QFont.Weight.Medium)
        p.setFont(fs)
        p.drawText(QRectF(0, 84, w, 24), Qt.AlignCenter, self.note)

        p.setPen(QColor(c.red(), c.green(), c.blue(), int(40 + 80 * hv)))
        fs2 = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        fs2.setLetterSpacing(QFont.AbsoluteSpacing, 3)
        p.setFont(fs2)
        p.drawText(QRectF(0, 112, w, 20), Qt.AlignCenter, "STAY TUNED")


class ExploreCard(QFrame):
    apply_clicked = Signal(str, str)

    def __init__(self, gid: str, preset: dict, parent=None):
        super().__init__(parent)
        self.gid = gid
        meta = nvprofiles.GAMES.get(gid, {})
        self.gname = meta.get("name", gid)
        self.preset = preset
        self._c = QColor(_color(self.gname))
        self._hv = 0.0

        self.setFixedHeight(118)
        self.setMouseTracking(True)

        self._anim = QPropertyAnimation(self, b"hv")
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        logo_frame = QFrame()
        logo_frame.setFixedWidth(120)
        logo_frame.setStyleSheet("background: transparent; border: none;")
        outer.addWidget(logo_frame)

        info = QVBoxLayout()
        info.setContentsMargins(4, 14, 16, 14)
        info.setSpacing(3)

        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.title_lbl = QLabel(preset["title"])
        self.title_lbl.setStyleSheet(
            f"font-size: 17px; font-weight: 700; color: {T['text']}; "
            "background: transparent; border: none;")
        r1.addWidget(self.title_lbl)
        from ui.widgets import badge
        tag = badge(preset.get("tag", ""), _color(self.gname), filled=True)
        r1.addWidget(tag)
        r1.addStretch()
        info.addLayout(r1)

        d = QLabel(preset["desc"])
        d.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 10.5px; background: transparent; border: none;")
        d.setWordWrap(True)
        info.addWidget(d)
        info.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._apply_btn = _ApplyBtn(self._c.name())
        self._apply_btn.setText("  Apply Preset")
        self._apply_btn.clicked.connect(
            lambda: self.apply_clicked.emit(self.gid, self.preset["preset"]))
        btn_row.addStretch()
        btn_row.addWidget(self._apply_btn)
        info.addLayout(btn_row)

        outer.addLayout(info, 1)

    def _get_hv(self):
        return self._hv

    def _set_hv(self, v):
        self._hv = v
        self.update()

    hv = Property(float, _get_hv, _set_hv)

    def enterEvent(self, e):
        self._anim.setStartValue(self._hv)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, e):
        self._anim.setStartValue(self._hv)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        R = 12.0
        rect = QRectF(0.5, 0.5, w - 1, h - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, R, R)
        hv = self._hv
        c = self._c

        bg0 = QColor(T["card"])
        bg1 = QColor(T["card_hover"])
        bg = QColor(
            int(bg0.red() + (bg1.red() - bg0.red()) * hv),
            int(bg0.green() + (bg1.green() - bg0.green()) * hv),
            int(bg0.blue() + (bg1.blue() - bg0.blue()) * hv),
        )
        p.fillPath(path, bg)

        wa = 0.03 + hv * 0.05
        gw = QLinearGradient(0, 0, w * 0.45, h * 0.8)
        gw.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), int(255 * wa)))
        gw.setColorAt(0.4, QColor(c.red(), c.green(), c.blue(), 0))
        p.fillPath(path, gw)

        logo_px = 76.0
        logo_x = (120 - logo_px) / 2.0
        logo_y = (h - logo_px) / 2.0
        logo_rect = QRectF(logo_x, logo_y, logo_px, logo_px)
        logo_R = 16.0

        glow = QRadialGradient(60.0, h / 2.0, logo_px * 0.7)
        glow.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 22))
        glow.setColorAt(0.6, QColor(c.red(), c.green(), c.blue(), 6))
        glow.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(logo_rect.adjusted(-10, -10, 10, 10), logo_R + 4, logo_R + 4)

        logo = _logo(self.gname)
        if logo and not logo.isNull():
            p.save()
            clip = QPainterPath()
            clip.addRoundedRect(logo_rect, logo_R, logo_R)
            p.setClipPath(clip)
            lw, lh = logo.width(), logo.height()
            scale = max(logo_px / lw, logo_px / lh)
            sw, sh = int(lw * scale), int(lh * scale)
            scaled = logo.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            dx = logo_x + (logo_px - scaled.width()) / 2
            dy = logo_y + (logo_px - scaled.height()) / 2
            p.drawPixmap(int(dx), int(dy), scaled)
            p.restore()
            p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(30 + hv * 40)), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(logo_rect, logo_R, logo_R)
        else:
            grad = QRadialGradient(logo_x + logo_px * 0.4, logo_y + logo_px * 0.4, logo_px * 0.6)
            grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue()))
            grad.setColorAt(1.0, QColor(max(0, c.red() - 50),
                                         max(0, c.green() - 50),
                                         max(0, c.blue() - 50)))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(logo_rect, logo_R, logo_R)

        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), int(18 + hv * 25)), 1.0))
        p.drawLine(120, 20, 120, h - 20)

        bdr = int(20 + hv * 50)
        gb = QLinearGradient(0, 0, w, h)
        gb.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), bdr))
        gb.setColorAt(0.4, QColor(255, 255, 255, int(1 + hv * 6)))
        gb.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), int(bdr * 0.25)))
        p.setPen(QPen(QBrush(gb), 0.6 + hv * 0.3))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, R, R)
        p.end()


# ═══════════════════════════════════════════════════════════════════════
#  BACKGROUND
# ═══════════════════════════════════════════════════════════════════════

class _Bg(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._ph = 0.0
        import random
        rng = random.Random(42)
        self._pts = [{
            "x": rng.random(), "y": rng.random(),
            "vx": (rng.random() - 0.5) * 0.0004,
            "vy": (rng.random() - 0.5) * 0.00025,
            "sz": rng.uniform(1.2, 2.5),
            "p": rng.random() * math.pi * 2,
            "sp": rng.uniform(0.7, 1.5),
        } for _ in range(20)]
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(33)

    def _tick(self):
        self._ph += 0.04
        for pt in self._pts:
            pt["x"] += pt["vx"]
            pt["y"] += pt["vy"]
            if pt["x"] < -0.05 or pt["x"] > 1.05:
                pt["vx"] *= -1
            if pt["y"] < -0.05 or pt["y"] > 1.05:
                pt["vy"] *= -1
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = float(self.width()), float(self.height())
        for yi in range(0, int(h), 3):
            a = int(1.2 + 0.8 * math.sin(yi * 0.03 + self._ph * 0.4))
            p.setPen(QColor(139, 92, 246, a))
            p.drawLine(0, yi, int(w), yi)
        for pt in self._pts:
            px, py = pt["x"] * w, pt["y"] * h
            a = int(10 + 6 * math.sin(self._ph * pt["sp"] + pt["p"]))
            gr = QRadialGradient(px, py, pt["sz"] * 4)
            gr.setColorAt(0.0, QColor(167, 139, 250, a))
            gr.setColorAt(1.0, QColor(167, 139, 250, 0))
            p.setBrush(QBrush(gr))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(px, py), pt["sz"] * 4, pt["sz"] * 4)
        p.end()


# ═══════════════════════════════════════════════════════════════════════
#  PROFILES PAGE
# ═══════════════════════════════════════════════════════════════════════

class ProfilesPage(QStackedWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._nip = {}
        self._cards: dict[str, GameCard] = {}

        self._list_page = QWidget()
        root = QVBoxLayout(self._list_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._bg = _Bg(self)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(12)

        hero = QFrame()
        hero.setFixedHeight(68)
        hero.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:0.7,y2:1,
                    stop:0 {_rgba(T["accent"], 0x0A)},
                    stop:0.3 {T['card']},
                    stop:1 {T['card']});
                border: 1px solid {_rgba(T["accent"], 0x18)};
                border-radius: 12px;
            }}
        """)
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(22, 8, 22, 8)
        hl.setSpacing(12)
        ht = QVBoxLayout()
        ht.setSpacing(2)
        t1 = QLabel("Game Profiles")
        t1.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {T['text']}; "
            "background: transparent; border: none; letter-spacing: -0.3px;")
        ht.addWidget(t1)
        t2 = QLabel("NVIDIA driver profiles tuned for maximum performance")
        t2.setStyleSheet(
            f"font-size: 11px; color: {T['text_dim']}; background: transparent; border: none;")
        ht.addWidget(t2)
        ht.addStretch()
        hl.addLayout(ht, 1)
        info = QHBoxLayout()
        info.setSpacing(6)
        self.gpu_lbl = QLabel("")
        self.gpu_lbl.setStyleSheet(
            f"color: {T['text_dim']}; font-size: 10px; background: transparent; border: none;")
        info.addWidget(self.gpu_lbl)
        from ui.widgets import badge
        info.addWidget(badge("ADMIN", T["accent"], filled=True) if _is_admin()
                       else badge("NOT ADMIN", T.get("warning", "#FFB454")))
        info.addStretch()
        hl.addLayout(info)
        cl.addWidget(hero)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent; border: none;")
        self._cw = QWidget()
        self._cw.setStyleSheet("background: transparent;")
        self._clay = QVBoxLayout(self._cw)
        self._clay.setContentsMargins(0, 0, 0, 0)
        self._clay.setSpacing(8)
        scroll.setWidget(self._cw)
        cl.addWidget(scroll, 1)

        root.addWidget(content)
        self.addWidget(self._list_page)

        self._explore_page = ExplorePage()
        self.addWidget(self._explore_page)
        self._explore_page.back_clicked.connect(lambda: self.setCurrentWidget(self._list_page))
        self._explore_page.apply_explore.connect(self._apply_explore)

        self._load_gpu()
        self._loader = _Loader()
        self._loader.done.connect(self._on_nips)
        self._loader.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._bg:
            self._bg.setGeometry(self.rect())

    def showEvent(self, e):
        super().showEvent(e)
        if self._bg:
            self._bg.lower()
            self._bg.setGeometry(self.rect())

    def _load_gpu(self):
        try:
            gpus = nvprofiles.gpu_names()
            if gpus:
                self.gpu_lbl.setText("GPU: " + ", ".join(gpus))
        except Exception:
            pass

    def _on_nips(self, nips):
        self._nip = nips
        self._build()

    def _build(self):
        while self._clay.count():
            it = self._clay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._cards.clear()

        from ui.categories import GAME_PROFILE_IDS
        from engine.nip_parser import game_id_for_profile

        nip_by_gid = {}
        for stem, nip in self._nip.items():
            gid = game_id_for_profile(nip)
            if gid:
                nip_by_gid[gid] = nip

        for gid in GAME_PROFILE_IDS:
            if gid not in nvprofiles.GAMES:
                continue
            nip = nip_by_gid.get(gid)
            card = GameCard(gid, nip=nip)
            card.apply_clicked.connect(self._apply)
            card.reset_clicked.connect(self._reset)
            card.explore_clicked.connect(self._open_explore)
            self._cards[gid] = card
            self._clay.addWidget(card)

        self._clay.addWidget(MoreComingSoonCard())

        self._clay.addStretch()

    def _nip_for(self, gid):
        from engine.nip_parser import game_id_for_profile
        for nip in self._nip.values():
            if game_id_for_profile(nip) == gid:
                return nip
        return None

    def _open_explore(self, gid):
        self._explore_page.set_game(gid)
        self.setCurrentWidget(self._explore_page)

    def _apply_explore(self, gid, preset):
        from ui.premium_widgets import toast
        import subprocess
        name = nvprofiles.GAMES.get(gid, {}).get("name", gid)
        npi_exe = _find_npi_exe()
        if npi_exe is None:
            toast("NVIDIA Profile Inspector is not installed. Install it to "
                  "apply extra presets.", "warning")
            return
        try:
            subprocess.Popen(
                [str(npi_exe), "--game", name, "--preset", preset],
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            logger.error(f"profiles: failed to launch NPI explore: {traceback.format_exc()}")
            toast(f"Failed to launch NVIDIA Profile Inspector: {exc}", "error")

    def _apply(self, gid):
        from ui.premium_widgets import toast
        name = nvprofiles.GAMES.get(gid, {}).get("name", gid)
        card = self._cards.get(gid)

        if card:
            card._apply_btn.set_state("applying")

        if not nvprofiles.driver_available():
            logger.error(f"profiles: NVIDIA driver/DRS unavailable for apply of {name}")
            if card:
                card._apply_btn.set_state("error")
            toast("NVIDIA driver could not be accessed.\n"
                  "Reinstall the NVIDIA driver (Game Ready) and try again.",
                  "warning")
            return

        try:
            # Apply via the in-app NvAPI DRS engine, which reads back each
            # setting and reports applied/skipped/failed — not a blind launch.
            report = nvprofiles.apply_profile(gid)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"profiles: apply {name} failed: {traceback.format_exc()}")
            if card:
                card._apply_btn.set_state("error")
            toast(f"Failed to apply driver profile for {name}: {exc}", "error")
            return

        if report.get("failed"):
            # Partially applied — surface which settings failed rather than
            # declaring a clean PASS.
            if card:
                card._apply_btn.set_state("error")
            fails = ", ".join(item[0] for item in report["failed"])
            toast(f"Profile for {name} applied with errors: {fails}", "warning")
            return

        if not report.get("applied"):
            if card:
                card._apply_btn.set_state("error")
            toast(f"No driver settings could be applied for {name}.", "warning")
            return

        if card:
            card._apply_btn.set_state("applied")
        state_mgr.set_active_profile(name)
        self.ctx.note_state_change()
        toast(f"Applied {len(report['applied'])} settings to {name}", "success")

    def _reset(self, gid):
        name = nvprofiles.GAMES.get(gid, {}).get("name", gid)
        if QMessageBox.question(self, "Reset",
                                f"Reset {name} to defaults?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        from ui.premium_widgets import toast
        try:
            rpt = nvprofiles.reset_profile(gid)
            if state_mgr.get_active_profile() == name:
                state_mgr.clear_active_profile()
            toast(f"{name} reset  \u2022  {len(rpt.get('applied', []))} settings restored",
                  "success")
            self.ctx.note_state_change()
            self._build()
        except Exception as exc:
            toast(f"Failed to reset: {exc}", "error")
