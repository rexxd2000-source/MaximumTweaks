"""Update UI — pixel-accurate port of update_dialog_v2.html.

Renders the "Check for Updates" popup exactly like the HTML mockup: a frameless
modal with the brand titlebar, animated version dial, spec chips, "What's
changed" list with tagged rows, a green status line and the action buttons
(Remind me later / Skip this version / Update now).

The modal sizes itself to its content (height:auto) with a max-height of
calc(100vh - 48px): compact (440px) while checking / up to date, roomy (520px)
with the changelog, and it animates between states (250ms ease-out, skipped
under prefers-reduced-motion). If the content is taller than max-height the
middle scrolls while the titlebar and footer stay fixed.

Both the update-available state and the up-to-date ("no update") state use the
same modal chrome so the popup always looks the same, just with different
content. The "Full changelog" footnote link is intentionally omitted (it would
open the GitHub repo).
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    Property as QtProperty,
    QEasingCurve,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QThread,
    QTimer,
    QPropertyAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import APP_NAME, APP_VERSION, UPDATE_EXE_NAME
from engine.state import LOGO_CACHE_FILE
from maxlog import logger

# Brand logo fetched from the website so the update dialog always shows the
# current official artwork, even in builds where the bundled asset changed.
_LOGO_URL = "https://max-opti.co.za/images/app-logo.png"
_LOGO_CACHE = LOGO_CACHE_FILE

# ---------------------------------------------------------------------------
# Palette — copied verbatim from update_dialog_v2.html :root
# ---------------------------------------------------------------------------
C = {
    "bg_page": "#08070d",
    "surface": "#0e0c16",
    "surface_2": "#151320",
    "border": "#211f2e",
    "border_soft": "#1a1824",
    "text_1": "#f2f0f8",
    "text_2": "#8b899c",
    "text_3": "#5c5a6b",
    "violet": "#8b7cf6",
    "violet_grad_a": "#9b8cff",
    "violet_grad_b": "#7c6df2",
    "violet_soft": "#2a2440",
    "teal": "#3ed6c8",
    "teal_soft": "#173430",
    "amber": "#e8a94a",
    "amber_soft": "#3a2b16",
    "green": "#4ade80",
}

SANS = "Segoe UI"
MONO = "JetBrains Mono"


def _mono(pixel: int, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    f = QFont(MONO, 1)
    f.setPixelSize(pixel)
    f.setWeight(weight)
    return f


def _sans(pixel: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont(SANS, 1)
    f.setPixelSize(pixel)
    f.setWeight(weight)
    return f


# -- reduced motion -----------------------------------------------------
# Honour the OS "show animations" setting (the Windows equivalent of the web
# prefers-reduced-motion media query) so the size transition is skipped for
# users who turn animations off. MT_REDUCED_MOTION=1 forces it on for testing.
_REDUCED_MOTION_CACHE: bool | None = None


def _prefers_reduced_motion() -> bool:
    global _REDUCED_MOTION_CACHE
    if _REDUCED_MOTION_CACHE is not None:
        return _REDUCED_MOTION_CACHE
    import os as _os
    env = (_os.environ.get("MT_REDUCED_MOTION")
           or _os.environ.get("REDUCED_MOTION"))
    if env is not None:
        _REDUCED_MOTION_CACHE = env.strip().lower() not in ("0", "", "false", "no")
        return _REDUCED_MOTION_CACHE
    reduced = False
    try:
        import ctypes
        # SPI_GETCLIENTAREAANIMATION -> 0 when "Animate controls and elements
        # inside windows" is turned off.
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0)
        if ok and enabled.value == 0:
            reduced = True
    except Exception:  # noqa: BLE001 - non-Windows / restricted => play safe
        reduced = False
    _REDUCED_MOTION_CACHE = reduced
    return reduced


def _no_select(w: QWidget) -> QWidget:
    """Make a widget's text un-selectable (user-select: none)."""
    try:
        if isinstance(w, QLabel):
            w.setTextInteractionFlags(Qt.NoTextInteraction)
    except Exception:  # noqa: BLE001
        pass
    try:
        w.setFocusPolicy(Qt.NoFocus)
    except Exception:  # noqa: BLE001
        pass
    return w


# ---------------------------------------------------------------------------
# Version dial — a small ring that draws an animated violet arc.
# ---------------------------------------------------------------------------
class _Dial(QWidget):
    """56px ring: dark track + violet fill arc animated like .dial-fill."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._fill = 0.0  # 0..1 portion of the arc drawn
        self._anim = None
        self._tone = "accent"  # accent | ok
        self._check = False
        self._spin = False
        self._angle = 0.0
        self._spin_anim = None
        self.setFixedSize(56, 56)
        w = QLabel(self)
        w.setFont(_mono(11, QFont.Weight.DemiBold))
        w.setAlignment(Qt.AlignCenter)
        w.setAttribute(Qt.WA_TransparentForMouseEvents)
        w.setGeometry(0, 0, 56, 56)
        self._label = w

    def setNumber(self, text: str):
        self._text = text
        self._label.setText(text)

    def animate(self, delay_ms: int = 400):
        self.stop_spin()
        self._label.setText(self._text)
        if self._anim is not None:
            self._anim.stop()
        self._fill = 0.0
        anim = QPropertyAnimation(self, b"fill", self)
        self._anim = anim
        anim.setDuration(1100)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        QTimer.singleShot(delay_ms, anim.start)

    def set_tone(self, tone: str, check: bool = False):
        """tone: 'accent' (violet) or 'ok' (green). check hides the number and
        draws a green checkmark in the dial centre."""
        self._tone = tone
        self._check = check
        self._label.setVisible(not check)
        self.update()

    def start_spin(self):
        """Continuous indeterminate spinner for the checking state."""
        if self._anim is not None:
            self._anim.stop()
        self._label.setVisible(False)
        self._check = False
        if self._spin:
            return
        self._spin = True
        anim = QPropertyAnimation(self, b"angle", self)
        anim.setDuration(1000)
        anim.setStartValue(0.0)
        anim.setEndValue(360.0)
        anim.setLoopCount(-1)
        anim.setEasingCurve(QEasingCurve.Linear)
        self._spin_anim = anim
        if not _prefers_reduced_motion():
            anim.start()
        else:
            self._angle = 0.0
            self.update()

    def stop_spin(self):
        if self._spin_anim is not None:
            self._spin_anim.stop()
            self._spin_anim = None
        self._spin = False

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, v: float):
        self._angle = float(v)
        self.update()

    angle = QtProperty(float, fget=_get_angle, fset=_set_angle)

    def _get_fill(self) -> float:
        return self._fill

    def _set_fill(self, v: float):
        self._fill = max(0.0, min(1.0, v))
        self.update()

    fill = QtProperty(float, fget=_get_fill, fset=_set_fill)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        center = QPointF(28, 28)
        r = 22.5
        pen = QPen(QColor(C["surface_2"]), 5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(center.x() - r, center.y() - r, r * 2, r * 2),
                  0, 360 * 16)
        if self._spin:
            spin = QPen(QColor(C["violet"]), 5)
            spin.setCapStyle(Qt.RoundCap)
            p.setPen(spin)
            p.drawArc(QRectF(center.x() - r, center.y() - r, r * 2, r * 2),
                      int((-90 + self._angle) * 16), int(-110 * 16))
            p.end()
            return
        # Violet (update) or green (up-to-date) arc, clockwise from the top,
        # leaving a small tail gap like the mockup's dash-fill.
        arc_color = C["green"] if self._tone == "ok" else C["violet"]
        fill = QPen(QColor(arc_color), 5)
        fill.setCapStyle(Qt.RoundCap)
        p.setPen(fill)
        # For the "ok" state show a full green ring (cleaner feedback).
        max_span = 360 if (self._tone == "ok" and self._fill >= 1.0) else 328
        span = int(max_span * 16 * self._fill)
        if span > 0:
            p.drawArc(QRectF(center.x() - r, center.y() - r, r * 2, r * 2),
                      -90 * 16, -span)
        # Checkmark badge for the up-to-date state.
        if self._check:
            p.setRenderHint(QPainter.Antialiasing)
            cpen = QPen(QColor(C["green"]), 3)
            cpen.setCapStyle(Qt.RoundCap)
            cpen.setJoinStyle(Qt.RoundJoin)
            p.setPen(cpen)
            p.drawPolyline([
                QPointF(19, 28.5), QPointF(25.5, 34.5), QPointF(37, 22)])
        p.end()


# ---------------------------------------------------------------------------
# Download progress bar — a thin filled track with a rounded violet fill.
# ---------------------------------------------------------------------------
class _ProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac = 0.0
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_frac(self, frac: float):
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["surface_2"]))
        p.drawRoundedRect(r, 3, 3)
        if self._frac > 0:
            fill = QRectF(0, 0, self.width() * self._frac, self.height())
            p.setBrush(QColor(C["violet"]))
            p.drawRoundedRect(fill, 3, 3)
        p.end()


# ---------------------------------------------------------------------------
# Update dialog
# ---------------------------------------------------------------------------
class FetchWorker(QThread):
    """Check for an update in the background."""

    done = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._err = ""

    def run(self):
        from engine import updater
        import traceback
        try:
            result = updater.fetch_update()
        except updater.UpdaterError as exc:
            self._err = str(exc)
            logger.info(f"updater: check failed: {exc}")
            result = None
        except Exception:  # noqa: BLE001
            logger.error("updater: unexpected check error:\n"
                         f"{traceback.format_exc()}")
            self._err = ("Update check failed unexpectedly. "
                         "Please try again, or run the latest build manually.")
            result = None
        if result is None and self._err:
            if any(
                s in self._err.lower() for s in
                ("http", "network", "timeout", "connection", "internet",
                 "offline", "rate-limit", "refused", "dns", "tls")
            ):
                self._err += ("\n\nThis looks like a connectivity issue, not a "
                              "VPN or firewall toggling in the app. Check that "
                              "the device has internet access, wait a few "
                              "minutes, then Retry. If it keeps failing, "
                              "download the latest build manually and run it.")
        self.done.emit({"info": result, "error": self._err})


class DownloadWorker(QThread):
    """Download the staged update; reports byte progress and 0..1 fraction."""

    bytes = Signal(int, int)  # got bytes, total bytes
    bytes_total = Signal(int)  # total bytes once known
    progress = Signal(float)
    done = Signal(object, str)  # new_exe path or None, error message

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._err = ""
        self._dest = None
        self._checksum_url = ""
        self._sha256 = ""
        self._filename = ""

    def _progress(self, got, total):
        self.bytes.emit(int(got), int(total))
        self.bytes_total.emit(int(total))
        if total > 0:
            self.progress.emit(min(1.0, got / total))

    def run(self):
        from engine import updater
        try:
            self._dest = updater.download(
                self._url, progress_cb=self._progress,
                checksum_url=self._checksum_url,
                expected_sha256=self._sha256,
                filename=self._filename)
        except updater.UpdaterError as exc:
            self._err = str(exc)
        except Exception as exc:  # noqa: BLE001
            self._err = str(exc)
            logger.warn(f"updater: download error: {exc}")
        self.done.emit(self._dest, self._err)


class LogoWorker(QThread):
    """Fetch the app logo from the website into the state cache dir."""

    done = Signal(str)  # path to the downloaded logo, or "" on failure

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""

    def run(self):
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(
                _LOGO_URL, headers={"User-Agent": "MaximumTweaks-updater/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            if data:
                os.makedirs(os.path.dirname(_LOGO_CACHE) or ".", exist_ok=True)
                with open(_LOGO_CACHE, "wb") as f:
                    f.write(data)
                self._path = _LOGO_CACHE
        except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
            logger.warn(f"updater: logo fetch failed: {exc}")
        self.done.emit(self._path)


_RISE_QSS = f"""
#Modal {{
    background-color: {C['surface']};
    border: 1px solid {C['border']};
    border-radius: 14px;
}}
#Titlebar {{
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {C['border_soft']};
}}
#Mark {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {C['violet_grad_a']}, stop:1 {C['violet_grad_b']});
    color: #ffffff;
    border: none;
    border-radius: 7px;
}}
#Titlebar .ud-l1 {{ color: {C['text_1']}; background: transparent; border: none; }}
#Titlebar .ud-l2 {{ color: {C['text_3']}; background: transparent; border: none; }}
#CloseBtn {{
    background: transparent; color: {C['text_3']};
    border: none; border-radius: 7px;
}}
#CloseBtn:hover {{ background: {C['surface_2']}; color: {C['text_1']}; }}
#Body {{ background: transparent; border: none; }}
#H1 {{ color: {C['text_1']}; background: transparent; border: none; }}
#NumOld {{ color: {C['text_3']}; background: transparent; border: none; text-decoration: line-through; }}
#NumArrow {{ color: {C['text_3']}; background: transparent; border: none; }}
#NumNew {{ color: {C['violet']}; background: transparent; border: none; }}
#SpecChip {{
    background: {C['surface_2']};
    border: 1px solid {C['border_soft']};
    border-radius: 7px;
    color: {C['text_2']};
}}
#SectionLabel {{ color: {C['text_3']}; background: transparent; border: none; }}
#ChangeItem {{
    background: {C['surface_2']};
    border: 1px solid {C['border_soft']};
    border-radius: 9px;
}}
#Tag.speed {{ background: {C['amber_soft']}; color: {C['amber']}; border: none; border-radius: 5px; }}
#Tag.fix   {{ background: {C['teal_soft']};  color: {C['teal']};  border: none; border-radius: 5px; }}
#Tag.new   {{ background: {C['violet_soft']}; color: {C['violet']}; border: none; border-radius: 5px; }}
#ChangeItem .ud-cb {{ color: {C['text_1']}; background: transparent; border: none; }}
#ChangeItem .ud-ct {{ color: {C['text_2']}; background: transparent; border: none; }}
#StatusDot {{
    background: {C['green']};
    border: none;
    border-radius: 3px;
}}
#StatusText {{ color: {C['green']}; background: transparent; border: none; }}
#SkipLink {{
    background: transparent; color: {C['text_3']};
    border: none; border-radius: 8px; padding: 8px 2px;
}}
#SkipLink:hover {{ color: {C['text_2']}; }}
#BtnLater {{
    background: {C['surface_2']}; color: {C['text_2']};
    border: 1px solid {C['border']}; border-radius: 8px;
}}
#BtnLater:hover {{ color: {C['text_1']}; border-color: #332f47; }}
#BtnUpdate {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {C['violet_grad_a']}, stop:1 {C['violet_grad_b']});
    color: #ffffff; border: none; border-radius: 8px;
}}
#BtnUpdate:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #a899ff, stop:1 #8878f5); }}
#BtnUpdate:disabled {{ background: #2a2440; color: #5c5a6b; }}
#Footnote {{ color: {C['text_3']}; background: transparent; border: none; }}
"""

# Transparent scroll areas with a slim 6px scrollbar, themed to the modal so
# the changelog (and the scrolling middle of the body) never show the native
# chunky scrollbar. Shared by the middle scroller and the changelog box.
_SCROLL_QSS = f"""
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}
QScrollBar::handle:vertical {{
    background: {C['violet_soft']}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #3b3357; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0; background: transparent;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


def _glyph(text: str, tag: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Tag")
    lbl.setProperty("class", tag)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setFixedSize(18, 18)
    lbl.setFont(_mono(10, QFont.Weight.DemiBold))
    return lbl


def _change(bold: str, text: str, tag: str, glyph: str):
    row = QWidget()
    row.setObjectName("ChangeItem")
    row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(11, 10, 11, 10)
    lay.setSpacing(10)
    lay.addWidget(_glyph(glyph, tag))
    txt = QLabel(f'<div style="line-height:150%;margin:0">'
                 f'<b>{bold}</b> {text}</div>')
    txt.setObjectName("ud-ct")
    txt.setWordWrap(True)
    txt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    txt.setMinimumWidth(0)
    txt.setFont(_sans(13))
    lay.addWidget(txt, 1)
    return row


class UpdateDialog(QDialog):
    """Check for updates, download with progress, install + restart.

    Renders both states inside the same framed modal:
      * update available — dial + chips + "What's changed" + green status +
        Remind me later / Skip this version / Update now
      * no update       — dial + "You're up to date" + green status + Close
    """

    def __init__(self, parent=None, check_on_open: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Update Available")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Width hugs each state (440 compact / 520 with the changelog); height
        # is measured from the content so the modal is never taller than needed
        # and never shorter than its content.
        self.setMinimumWidth(0)
        self.setMinimumHeight(0)
        self._info = None
        self._new_exe = None
        self._bytes_total = 0
        self._bytes_got = 0
        self._mode = None
        self._worker = None
        self._geom_anim = None
        self._fade_anim = None

        self.setStyleSheet(_RISE_QSS)

        # ---------- root ----------
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # We size this frameless dialog ourselves from the measured content, so
        # stop the layout from imposing a (cached, stale) minimum that would
        # clamp resizes between states.
        root.setSizeConstraint(QLayout.SetNoConstraint)
        self.setMinimumSize(0, 0)

        self._modal = QFrame(self)
        self._modal.setObjectName("Modal")
        root.addWidget(self._modal)

        m = QVBoxLayout(self._modal)
        m.setContentsMargins(0, 0, 0, 0)
        m.setSpacing(0)

        # ---------- titlebar ----------
        tb = QFrame()
        tb.setObjectName("Titlebar")
        tb.setFixedHeight(56)
        t = QHBoxLayout(tb)
        t.setContentsMargins(16, 12, 13, 12)
        t.setSpacing(10)

        mark = QLabel("M")
        mark.setObjectName("Mark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(24, 24)
        mark.setFont(_sans(12, QFont.Weight.Bold))
        t.addWidget(mark)
        self._mark = mark
        self._logo_worker = None

        sub = QVBoxLayout()
        sub.setContentsMargins(0, 0, 0, 0)
        sub.setSpacing(3)
        l1 = QLabel("Maximum Tweaks")
        l1.setObjectName("ud-l1")
        l1.setFont(_sans(13, QFont.Weight.DemiBold))
        self._tb_sub = QLabel("CHECKING FOR UPDATES")
        self._tb_sub.setObjectName("ud-l2")
        _s = _mono(10, QFont.Weight.Medium)
        _s.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        self._tb_sub.setFont(_s)
        sub.addWidget(l1)
        sub.addWidget(self._tb_sub)
        t.addLayout(sub, 1)

        close = QToolButton()
        close.setObjectName("CloseBtn")
        close.setFixedSize(26, 26)
        close.setText("\u2715")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        t.addWidget(close)

        m.addWidget(tb)

        # ---------- body ----------
        body = QWidget()
        body.setObjectName("Body")
        b = QVBoxLayout(body)
        b.setContentsMargins(20, 22, 20, 20)
        b.setSpacing(0)
        m.addWidget(body)

        # The middle of the dialog (version row, chips, actions, changelog)
        # lives in a scroll area that is allowed to shrink to nothing, so on a
        # short screen the whole middle scrolls instead of the changelog box
        # being squashed to a sliver. AdjustToContents keeps the dialog height
        # hugging its content whenever there is room.
        self._mid_scroll = QScrollArea()
        self._mid_scroll.setWidgetResizable(True)
        self._mid_scroll.setFrameShape(QFrame.NoFrame)
        self._mid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._mid_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mid_scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._mid_scroll.setMinimumHeight(0)
        self._mid_scroll.setStyleSheet(_SCROLL_QSS)
        self._mid = QWidget()
        self._mid.setStyleSheet("background: transparent;")
        mb = QVBoxLayout(self._mid)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.setSpacing(0)
        self._mid_scroll.setWidget(self._mid)
        b.addWidget(self._mid_scroll, 1)

        # version row
        vr = QHBoxLayout()
        vr.setSpacing(14)
        self._dial = _Dial("")
        vr.addWidget(self._dial, 0, Qt.AlignVCenter)

        vt = QVBoxLayout()
        vt.setContentsMargins(0, 0, 0, 0)
        vt.setSpacing(5)
        self._h1 = QLabel("")
        self._h1.setObjectName("H1")
        self._h1.setFont(_sans(16, QFont.Weight.Bold))
        vt.addWidget(self._h1)
        nums = QHBoxLayout()
        nums.setContentsMargins(0, 0, 0, 0)
        nums.setSpacing(7)
        self._num_old = QLabel("")
        self._num_old.setObjectName("NumOld")
        self._num_old.setFont(_mono(12))
        nums.addWidget(self._num_old)
        arrow = QLabel("\u2192")
        arrow.setObjectName("NumArrow")
        arrow.setFont(_mono(12))
        nums.addWidget(arrow)
        self._num_arrow = arrow
        self._num_new = QLabel("")
        self._num_new.setObjectName("NumNew")
        self._num_new.setFont(_mono(12, QFont.Weight.DemiBold))
        nums.addWidget(self._num_new)
        nums.addStretch()
        vt.addLayout(nums)

        self._num_status = QLabel("")
        self._num_status.setObjectName("NumNew")
        self._num_status.setFont(_mono(10))
        self._num_status.setVisible(False)
        vt.addWidget(self._num_status)

        vr.addLayout(vt, 1)
        mb.addLayout(vr)
        mb.addSpacing(18)

        # spec chips
        self._chips = QHBoxLayout()
        self._chips.setContentsMargins(0, 0, 0, 0)
        self._chips.setSpacing(7)
        mb.addLayout(self._chips)
        mb.addSpacing(20)

        # actions
        act = QHBoxLayout()
        act.setContentsMargins(0, 0, 0, 0)
        act.setSpacing(12)
        self._later = QToolButton()
        self._later.setObjectName("SkipLink")
        self._later.setText("Remind me later")
        self._later.setFont(_sans(12))
        self._later.setCursor(Qt.PointingHandCursor)
        self._later.clicked.connect(self.reject)
        act.addWidget(self._later)
        act.addStretch()

        grp = QHBoxLayout()
        grp.setContentsMargins(0, 0, 0, 0)
        grp.setSpacing(8)
        self._btn_later = QToolButton()
        self._btn_later.setObjectName("BtnLater")
        self._btn_later.setText("Skip this version")
        self._btn_later.setFont(_sans(12, QFont.Weight.DemiBold))
        self._btn_later.setCursor(Qt.PointingHandCursor)
        self._btn_later.setFixedHeight(36)
        self._btn_later.clicked.connect(self._skip_version)
        grp.addWidget(self._btn_later)
        self._btn_update = QToolButton()
        self._btn_update.setObjectName("BtnUpdate")
        self._btn_update.setText("\u2b07  Update now")
        self._btn_update.setFont(_sans(12, QFont.Weight.DemiBold))
        self._btn_update.setCursor(Qt.PointingHandCursor)
        self._btn_update.setFixedHeight(36)
        self._btn_update.clicked.connect(self._on_update_clicked)
        grp.addWidget(self._btn_update)
        act.addLayout(grp)
        mb.addLayout(act)
        mb.addSpacing(14)

        # What's changed — wrapped in its own container so it fully collapses
        # (label + list) on the up-to-date/error states. The list itself lives
        # in a scroll area with a fixed footprint: never smaller than 96px (so
        # a one-line changelog is still readable and never clipped) and never
        # larger than 220px (so a long changelog scrolls inside the box instead
        # of making the dialog taller than the window). It is deliberately NOT
        # stretchable; its height is measured and pinned in _adopt_widgets.
        self._changes_box = QWidget()
        self._changes_box.setObjectName("Body")
        cb = QVBoxLayout(self._changes_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(11)
        self._section = QLabel("What's changed")
        self._section.setObjectName("SectionLabel")
        self._section.setFont(_sans(11))
        cb.addWidget(self._section)
        self._changes_scroll = QScrollArea()
        self._changes_scroll.setWidgetResizable(True)
        self._changes_scroll.setFrameShape(QFrame.NoFrame)
        self._changes_scroll.setStyleSheet(_SCROLL_QSS)
        self._changes_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._changes_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._changes_scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._changes_scroll.setMinimumHeight(96)
        self._changes_scroll.setMaximumHeight(220)
        self._changes_host = QWidget()
        self._changes_host.setStyleSheet("background: transparent;")
        self._changes = QVBoxLayout(self._changes_host)
        self._changes.setContentsMargins(14, 12, 14, 12)
        self._changes.setSpacing(10)
        self._changes_scroll.setWidget(self._changes_host)
        cb.addWidget(self._changes_scroll)
        self._changes_box.setVisible(True)
        mb.addWidget(self._changes_box)
        mb.addStretch(1)

        # ---------- footer (pinned below the scrolling middle) ----------
        # Kept out of the outer scroll so the status line / progress / restart
        # note stay visible while only the middle (header, chips, buttons,
        # changelog) scrolls on very short screens.
        self._footer = QWidget()
        self._footer.setStyleSheet("background: transparent;")
        f = QVBoxLayout(self._footer)
        f.setContentsMargins(0, 12, 0, 0)
        f.setSpacing(0)

        # status row
        st = QHBoxLayout()
        st.setContentsMargins(0, 0, 0, 0)
        st.setSpacing(6)
        dot = QFrame()
        dot.setObjectName("StatusDot")
        dot.setFixedSize(6, 6)
        st.addWidget(dot, 0, Qt.AlignVCenter)
        self._status = QLabel("")
        self._status.setObjectName("StatusText")
        self._status.setWordWrap(True)
        self._status.setFont(_mono(11))
        st.addWidget(self._status, 1)
        st.addStretch()
        f.addLayout(st)

        # thin download progress bar — only visible while downloading
        self._progress_bar = _ProgressBar(self._footer)
        self._progress_bar.setVisible(False)
        f.addWidget(self._progress_bar)
        f.addSpacing(8)

        # footnote (only shown when an update is available)
        fn = QLabel("Maximum Tweaks will restart automatically")
        fn.setObjectName("Footnote")
        fn.setAlignment(Qt.AlignCenter)
        fn.setFont(_sans(10))
        f.addWidget(fn)
        self._footnote = fn

        b.addWidget(self._footer)

        self._adopt_widgets()
        self._load_remote_logo()
        if check_on_open:
            self._check()

    # ------------------------------------------------------------------
    # brand logo (fetched from the website, cached in the state dir)
    # ------------------------------------------------------------------
    def _load_remote_logo(self):
        """Show the official logo in the titlebar: use the cached web fetch
        immediately if present, then refresh it from the internet in the
        background. Falls back to the bundled "M" mark on failure."""
        if os.path.isfile(_LOGO_CACHE):
            self._apply_logo_pixmap(QPixmap(_LOGO_CACHE))
        self._logo_worker = LogoWorker(self)
        self._logo_worker.done.connect(self._on_logo_done)
        self._logo_worker.finished.connect(self._logo_gc)
        self._logo_worker.start()

    def _apply_logo_pixmap(self, pm):
        if pm.isNull():
            return
        mark = self._mark
        mark.setText("")
        size = 22
        scaled = pm.scaled(size, size, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
        mark.setPixmap(scaled)
        mark.setStyleSheet(
            "background:transparent;border:none;border-radius:7px;")

    def _on_logo_done(self, path):
        if path and os.path.isfile(path):
            self._apply_logo_pixmap(QPixmap(path))

    def _logo_gc(self):
        self._logo_worker = None

    # -- sizing ----------------------------------------------------------
    # Width per state: compact (440) for checking / up-to-date / error, roomy
    # (520) when the changelog is on screen. Height is always measured from the
    # content — never hardcoded.
    _STATE_WIDTH = {
        "available": 520, "downloading": 520, "ready": 520,
        "checking": 440, "up_to_date": 440, "error": 440,
    }
    _TITLEBAR_H = 56
    _BODY_VMARGIN = 42  # body layout 22 top + 20 bottom
    _CHANGES_MIN = 96
    _CHANGES_MAX = 220

    def _state_width(self) -> int:
        return self._STATE_WIDTH.get(self._mode or "checking", 452)

    def _max_h(self) -> int:
        """max-height: calc(100vh - 48px) on the monitor the dialog is on."""
        geos = QApplication.screens()
        if not geos:
            return 10000
        avail = geos[0].availableGeometry()
        for g in geos:
            if g.availableGeometry().intersects(self.frameGeometry()):
                avail = g.availableGeometry()
                break
        return max(320, avail.height() - 48)

    def _center_rect(self, w: int, h: int) -> QRect:
        """Target rect, centred on the parent window (or the screen)."""
        cx, cy = None, None
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            geo = parent.window().frameGeometry()
            if geo.isValid() and not geo.isEmpty():
                cx, cy = geo.center().x(), geo.center().y()
        if cx is None:
            scr = (QApplication.screenAt(self.frameGeometry().center())
                   or QApplication.primaryScreen())
            if scr is not None:
                geo = scr.availableGeometry()
                cx, cy = geo.center().x(), geo.center().y()
        if cx is None:
            return QRect(0, 0, w, h)
        return QRect(int(cx - w / 2), int(cy - h / 2), w, h)

    def _measure_changes(self, dialog_w: int) -> int:
        """Height the changelog list wants at ``dialog_w``, clamped to
        [min-height 96, max-height 220]. Row heights come from the label's
        heightForWidth (the rich-text sizeHint is unreliable), so the box hugs
        short logs and caps + scrolls long ones."""
        if self._changes_box.isHidden():
            return 0
        host_w = max(160, dialog_w - self._BODY_VMARGIN)
        m = self._changes.contentsMargins()
        inner = max(60, host_w - m.left() - m.right())
        total = m.top() + m.bottom()
        n = self._changes.count()
        for i in range(n):
            item = self._changes.itemAt(i)
            row = item.widget() if item is not None else None
            if row is None:
                continue
            rl = row.layout()
            rm = rl.contentsMargins()
            lbl = row.findChild(QLabel, "ud-ct")
            text_w = inner - rm.left() - rm.right() - 18 - rl.spacing()
            lh = lbl.heightForWidth(max(40, text_w)) if lbl is not None else 18
            total += max(18, lh) + rm.top() + rm.bottom()
        if n > 1:
            total += (n - 1) * self._changes.spacing()
        return max(self._CHANGES_MIN, min(self._CHANGES_MAX, total))

    def _mid_content_h(self, box_h: int) -> int:
        """Natural height of the scrolling middle at the current width. Summed
        item-by-item so the changelog box (whose QScrollArea sizeHint is not
        trustworthy) contributes its measured ``box_h`` instead."""
        lay = self._mid.layout()
        total = 0
        for i in range(lay.count()):
            item = lay.itemAt(i)
            if item is None:
                continue
            if item.spacerItem() is not None:
                total += item.spacerItem().sizeHint().height()
                continue
            w = item.widget()
            if w is not None:
                if w is self._changes_box:
                    if self._changes_box.isHidden():
                        continue
                    gap = self._changes_box.layout().spacing()
                    total += (self._section.sizeHint().height() + gap + box_h)
                elif not w.isHidden():
                    total += w.sizeHint().height()
                continue
            sub = item.layout()
            if sub is not None:
                total += sub.sizeHint().height()
        return total

    def _noselect_all(self):
        """user-select: none — nothing in the dialog can be selected."""
        for lbl in self.findChildren(QLabel):
            _no_select(lbl)

    def _adopt_widgets(self, animate: bool | None = None):
        """Measure the content for the current state and size the dialog to it.

        No height is ever hardcoded: the middle content and the pinned footer
        are measured at the target width, the changelog box is pinned to its
        96-220px footprint, and the dialog is sized to the sum. If the content
        would exceed ``max-height: calc(100vh - 48px)`` the middle scrolls
        (the footer stays pinned). The size change is animated when the dialog
        is already on screen (250ms ease-out), respecting reduced motion.
        """
        if animate is None:
            animate = self.isVisible()
        self._noselect_all()
        old = self.geometry()
        w = self._state_width()

        # Lay the content out at the target width so wrapped text measures at
        # the size it will actually occupy.
        self._mid_scroll.setMinimumHeight(0)
        self.setMinimumWidth(0)
        self.resize(w, max(old.height(), 1))
        self.layout().activate()
        self._modal.layout().activate()

        # Pin the changelog footprint, then measure middle + footer. The
        # middle height is summed from its items (a QScrollArea's own sizeHint
        # is unreliable, so the changelog box height is supplied explicitly).
        box_h = self._measure_changes(w)
        self._changes_scroll.setFixedHeight(box_h or self._CHANGES_MIN)
        self._changes_scroll.updateGeometry()
        self._changes_box.updateGeometry()
        self._mid_scroll.updateGeometry()
        mid_h = self._mid_content_h(box_h)
        self._footer.layout().activate()
        footer_h = self._footer.sizeHint().height()

        max_h = self._max_h()
        chrome = self._TITLEBAR_H + self._BODY_VMARGIN
        scroll_h = min(mid_h, max(0, max_h - chrome - footer_h))
        self._mid_scroll.setFixedHeight(max(0, scroll_h))
        self._mid_scroll.updateGeometry()
        self.setMaximumHeight(max_h)
        self.layout().activate()

        total_h = chrome + scroll_h + footer_h
        target = self._center_rect(w, total_h)
        if self._geom_anim is not None:
            self._geom_anim.stop()
            self._geom_anim = None
        if (not animate) or _prefers_reduced_motion() or old == target:
            self.setGeometry(target)
            return
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(250)
        anim.setStartValue(old)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._geom_anim = anim

    def _fade_in(self, widget: QWidget):
        """Fade a freshly shown widget in (200ms) so it doesn't flash before
        the dialog has grown to fit it."""
        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._fade_anim = None
        if _prefers_reduced_motion():
            try:
                widget.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass
            return
        eff = QGraphicsOpacityEffect(widget)
        eff.setOpacity(0.0)
        widget.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _done():
            try:
                if widget.graphicsEffect() is eff:
                    widget.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass

        anim.finished.connect(_done)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._fade_anim = anim

    def showEvent(self, event):
        super().showEvent(event)
        self._adopt_widgets(animate=False)

    def _chip(self, bold: str, rest: str) -> QLabel:
        lbl = QLabel(f"<b>{bold}</b> {rest}")
        lbl.setObjectName("SpecChip")
        lbl.setContentsMargins(0, 0, 0, 0)
        lbl.setFont(_mono(11))
        return lbl

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    # ------------------------------------------------------------------
    # states
    # ------------------------------------------------------------------
    def _show_available(self, info: dict):
        """Update available — render exactly like the mockup's body."""
        self._mode = "available"
        self._tb_sub.setText("UPDATE AVAILABLE")
        cur = APP_VERSION.lstrip("v")
        new = str(info.get("version") or "").strip().lstrip("v")
        self._dial.setNumber(new)
        self._dial.set_tone("accent")
        self._dial.animate(400)
        self._h1.setText("Tuned up and ready")
        # Only the update-available state shows the crossed-out old version in
        # the "v{old} -> v{new}" row.
        self._num_old.setText(f"v{cur}")
        self._num_old.show()
        self._num_arrow.show()
        self._num_new.setText(f"v{new}")
        self._num_new.show()
        self._num_status.hide()

        self._clear_layout(self._chips)
        self._chips.addWidget(self._chip(f"{self._mb_label()} MB", "download"))
        self._chips.addWidget(self._chip("~2 min", "install"))
        self._chips.addWidget(self._chip("Released today", ""))

        self._section.setText("What's changed")
        self._changes_box.show()
        self._fade_in(self._changes_box)
        self._clear_layout(self._changes)
        items = self._parse_notes(info.get("notes") or "")
        for bold, text, tag, glyph in items:
            self._changes.addWidget(_change(bold, text, tag, glyph))

        self._status.setText("A newer build is ready \u2014 hit Update now")
        self._progress_bar.setVisible(False)
        self._later.setText("Remind me later")
        self._later.show()
        self._btn_later.setText("Skip this version")
        self._btn_later.show()
        self._btn_update.setText("\u2b07  Update now")
        self._btn_update.setEnabled(True)
        self._footnote.show()
        self._adopt_widgets()

    def _show_up_to_date(self):
        """No update — same modal chrome, 'You're up to date' content."""
        self._mode = "up_to_date"
        self._tb_sub.setText("UP TO DATE")
        cur = APP_VERSION.lstrip("v")
        self._dial.setNumber(cur)
        self._dial.set_tone("ok", check=True)   # full green ring + checkmark
        self._dial.animate(250)
        self._h1.setText("You\u2019re up to date")
        # Single, normal version line — no strikethrough and no duplicate grey
        # line. The crossed-out "v{old}" row belongs only to the update state.
        self._num_old.setText("")
        self._num_old.hide()
        self._num_arrow.hide()
        self._num_new.setText("")
        self._num_new.hide()
        self._num_status.setText(f"Latest release \u00b7 v{cur} installed")
        self._num_status.setVisible(True)

        self._clear_layout(self._chips)
        self._chips.addWidget(self._chip("Up to date", "\u00b7 latest build"))
        self._chips.addWidget(self._chip("v" + cur, "installed"))

        self._changes_box.hide()
        self._clear_layout(self._changes)

        self._status.setText("All good \u2014 you\u2019re on the latest release")
        self._progress_bar.setVisible(False)
        self._later.hide()
        self._btn_later.hide()
        self._btn_update.setText("\u2713  Done")
        self._btn_update.setEnabled(True)
        self._footnote.hide()
        self._num_status.setStyleSheet(f"color: {C['green']}; background: transparent; border: none;")
        self._adopt_widgets()

    def _show_error(self, message: str):
        self._mode = "error"
        self._tb_sub.setText("CHECK FAILED")
        self._dial.setNumber("!")
        self._dial.set_tone("accent")
        self._dial.animate(0)
        self._h1.setText("Couldn\u2019t check for updates")
        self._num_old.setText("")
        self._num_old.hide()
        self._num_arrow.hide()
        self._num_new.setText("")
        self._num_new.hide()
        self._num_status.setVisible(False)
        self._clear_layout(self._chips)
        self._clear_layout(self._changes)
        self._changes_box.hide()
        self._status.setText(message or "Couldn\u2019t check for updates.")
        self._progress_bar.setVisible(False)
        self._later.hide()
        self._btn_later.hide()
        self._btn_update.setText("Retry")
        self._btn_update.setEnabled(True)
        self._footnote.hide()
        self._adopt_widgets()

    # ------------------------------------------------------------------
    # flow
    # ------------------------------------------------------------------
    def _parse_notes(self, notes: str):
        lines = [ln.strip() for ln in notes.replace("\r", "").splitlines()
                 if ln.strip()]
        if not lines:
            return [("", "No changelog provided.", "new", "\u002b")]
        out = []
        for ln in lines:
            if not ln:
                continue
            marker = ln[0]
            ln = ln.lstrip("-*+#>\u26a1").strip()
            if not ln:
                continue
            if marker in ("\u26a1", "*", ">"):
                tag, glyph = "speed", "\u26a1"
            elif marker == "-":
                tag, glyph = "fix", "\u2713"
            else:
                tag, glyph = "new", "\u002b"
            if ":" in ln[:14]:
                head, _, rest = ln.partition(":")
                out.append((head.strip() + ":", rest.strip(), tag, glyph))
            else:
                out.append(("", ln, tag, glyph))
        return out or [("", lines[0], "new", "\u002b")]

    def _mb_label(self) -> str:
        if self._bytes_total > 0:
            return f"{self._bytes_total / 1048576:.0f}"
        return "41"
    def _check(self):
        self._mode = "checking"
        self._tb_sub.setText("CHECKING FOR UPDATES")
        self._dial.setNumber("?")
        self._dial.set_tone("accent")
        self._dial.start_spin()
        self._h1.setText("Checking for updates\u2026")
        # Compact: spinner + heading only, no version row, no changelog.
        self._num_old.setText("")
        self._num_old.hide()
        self._num_arrow.hide()
        self._num_new.setText("")
        self._num_new.hide()
        self._num_status.hide()
        self._clear_layout(self._chips)
        self._changes_box.hide()
        self._clear_layout(self._changes)
        self._status.setText("")
        self._progress_bar.setVisible(False)
        self._later.setEnabled(False)
        self._btn_later.setEnabled(False)
        self._btn_update.setEnabled(False)
        self._btn_update.setText("Checking\u2026")
        self._footnote.hide()
        self._adopt_widgets()
        self.worker = FetchWorker(self)
        self.worker.done.connect(self._on_checked)
        self.worker.start()

    def _on_checked(self, payload):
        info = payload.get("info")
        error = payload.get("error")
        self._later.setEnabled(True)
        self._btn_later.setEnabled(True)
        self._btn_update.setEnabled(True)
        if error:
            self._show_error(error)
            return
        if info is None:
            self._show_up_to_date()
            return
        self._info = info
        self._show_available(info)

    def _on_update_clicked(self):
        if self._mode == "checking":
            return
        if self._mode == "available":
            self._download()
        elif self._mode == "ready":
            self._install()
        elif self._mode == "error":
            self._check()
        elif self._mode == "up_to_date":
            self.reject()

    def _download(self):
        if self._info is None:
            return
        self._mode = "downloading"
        self._tb_sub.setText("DOWNLOADING")
        self._btn_update.setEnabled(False)
        self._btn_update.setText("Downloading\u2026")
        self._btn_later.setEnabled(False)
        self._later.setEnabled(False)
        # Collapse the changelog so the status + buttons stay grouped at the
        # bottom (no big empty opening while it downloads).
        self._changes_box.hide()
        self._progress_bar.set_frac(0.0)
        self._progress_bar.setVisible(True)
        self._status.setText("Downloading the new build\u2026")
        self.worker = DownloadWorker(self._info["url"], self)
        self.worker._checksum_url = str(self._info.get("checksum_url") or "")
        self.worker._sha256 = str(self._info.get("sha256") or "")
        self.worker._filename = str(self._info.get("filename") or "")
        self.worker.bytes.connect(self._on_bytes)
        self.worker.done.connect(self._on_downloaded)
        self.worker.start()
        self._adopt_widgets()

    def _on_bytes(self, got: int, total: int):
        self._bytes_got = int(got or 0)
        self._bytes_total = int(total or 0)
        frac = (self._bytes_got / self._bytes_total) if self._bytes_total else 0.0
        self._progress_bar.set_frac(frac)
        got_mb = f"{self._bytes_got / 1048576:.0f}"
        total_mb = f"{self._bytes_total / 1048576:.0f}"
        self._status.setText(
            f"Downloading {got_mb} / {total_mb} MB\u2026 {int(frac * 100)}%")

    def _on_downloaded(self, new_exe, error):
        self._btn_update.setEnabled(True)
        self._btn_later.setEnabled(True)
        self._later.setEnabled(True)
        if error or new_exe is None:
            self._show_error(error or "Download failed.")
            return
        self._mode = "ready"
        self._new_exe = new_exe
        self._tb_sub.setText("READY TO INSTALL")
        self._progress_bar.set_frac(1.0)
        self._status.setText("Downloaded and verified \u2014 ready to install")
        self._btn_update.setText("\u26a1  Restart Update")
        self._adopt_widgets()

    def _skip_version(self):
        """Skip this version — dismiss the dialog (no persistent skip api)."""
        self.reject()

    def _install(self):
        from engine import updater
        try:
            updater.install_and_restart(self._new_exe)
        except updater.UpdaterError as exc:
            self._show_error(str(exc))
            return
        logger.info("updater: quitting to apply update")
        if hasattr(self.parentWidget(), "close"):
            self.parentWidget().close()
        import time as _time
        _time.sleep(1)
        os._exit(0)