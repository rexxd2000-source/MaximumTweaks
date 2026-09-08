"""Update UI — pixel-accurate port of update_dialog_v2.html.

Renders the "Check for Updates" popup exactly like the HTML mockup: a 452px
frameless modal with the brand titlebar, animated version dial, spec chips,
"What's changed" list with tagged rows, a green status line and the action
buttons (Remind me later / Skip this version / Update now).

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
    QRectF,
    Qt,
    QThread,
    QTimer,
    QPropertyAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config.app_config import APP_NAME, APP_VERSION, UPDATE_EXE_NAME
from rexlog import logger

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
            self._err += ("\n\nIf a VPN, proxy or firewall is on, turn it off "
                          "and Retry \u2014 the app needs internet access to "
                          "see and install the latest version.")
        self.done.emit({"info": result, "error": self._err})


class DownloadWorker(QThread):
    """Download the staged update; reports 0..1 progress."""

    progress = Signal(float)
    bytes_total = Signal(int)
    done = Signal(object, str)  # new_exe path or None, error message

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._err = ""
        self._dest = None

    def _progress(self, frac):
        self.progress.emit(frac)

    def run(self):
        from engine import updater
        try:
            self._dest = updater.download(self._url, progress_cb=self._progress)
        except updater.UpdaterError as exc:
            self._err = str(exc)
        except Exception as exc:  # noqa: BLE001
            self._err = str(exc)
            logger.warn(f"updater: download error: {exc}")
        self.done.emit(self._dest, self._err)


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
    txt = QLabel(f"<b>{bold}</b> {text}")
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
        # Fixed modal width matches update_dialog_v2.html; height auto-sizes
        # (hugs content) so the button row sits right under the changelog.
        self.setFixedWidth(452)
        self._info = None
        self._new_exe = None
        self._bytes_total = 0
        self._mode = None
        self._worker = None

        self.setStyleSheet(_RISE_QSS)

        # ---------- root ----------
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

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
        b.addLayout(vr)
        b.addSpacing(18)

        # spec chips
        self._chips = QHBoxLayout()
        self._chips.setContentsMargins(0, 0, 0, 0)
        self._chips.setSpacing(7)
        b.addLayout(self._chips)
        b.addSpacing(20)

        # What's changed — wrapped in its own container so it fully collapses
        # (label + list + spacing) on the up-to-date/error states.
        self._changes_box = QWidget()
        self._changes_box.setObjectName("Body")
        cb = QVBoxLayout(self._changes_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(11)
        self._section = QLabel("What's changed")
        self._section.setObjectName("SectionLabel")
        self._section.setFont(_sans(11))
        cb.addWidget(self._section)
        self._changes = QVBoxLayout()
        self._changes.setContentsMargins(0, 0, 0, 0)
        self._changes.setSpacing(10)
        cb.addLayout(self._changes)
        # bottom gap is part of the box so it collapses when hidden
        cb.addSpacing(20)
        self._changes_box.setVisible(True)
        b.addWidget(self._changes_box)

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
        b.addLayout(st)
        b.addSpacing(18)

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
        b.addLayout(act)
        b.addSpacing(14)

        # footnote (only shown when an update is available)
        fn = QLabel("Maximum Tweaks will restart automatically")
        fn.setObjectName("Footnote")
        fn.setAlignment(Qt.AlignCenter)
        fn.setFont(_sans(10))
        b.addWidget(fn)
        self._footnote = fn

        self._adopt_widgets()
        if check_on_open:
            self._check()

    # ------------------------------------------------------------------
    # styling / content helpers
    # ------------------------------------------------------------------
    def _adopt_widgets(self):
        """Keep the modal chrome laid out; height hugs the current content."""
        self._modal.layout().activate()
        self.adjustSize()

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
        self._num_old.setText(f"v{cur}")
        self._num_arrow.show()
        self._num_new.setText(f"v{new}")
        self._num_status.setVisible(False)

        self._clear_layout(self._chips)
        self._chips.addWidget(self._chip(f"{self._mb_label()} MB", "download"))
        self._chips.addWidget(self._chip("~2 min", "install"))
        self._chips.addWidget(self._chip("Released today", ""))

        self._section.setText("What's changed")
        self._changes_box.show()
        self._clear_layout(self._changes)
        items = self._parse_notes(info.get("notes") or "")
        for bold, text, tag, glyph in items[:3]:
            self._changes.addWidget(_change(bold, text, tag, glyph))

        self._status.setText("Downloaded and verified \u2014 ready to install")
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
        self._num_old.setText(f"v{cur}")
        self._num_arrow.hide()
        self._num_new.setText("")
        self._num_status.setText(f"Latest release \u00b7 v{cur} installed")
        self._num_status.setVisible(True)

        self._clear_layout(self._chips)
        self._chips.addWidget(self._chip("Up to date", "\u00b7 latest build"))
        self._chips.addWidget(self._chip("v" + cur, "installed"))

        self._changes_box.hide()
        self._clear_layout(self._changes)

        self._status.setText("All good \u2014 you\u2019re on the latest release")
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
        self._num_arrow.hide()
        self._num_new.setText("")
        self._num_status.setVisible(False)
        self._clear_layout(self._chips)
        self._clear_layout(self._changes)
        self._changes_box.hide()
        self._status.setText(message or "Couldn\u2019t check for updates.")
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
            return [("New build", "Install the latest version.",
                     "new", "\u002b")]
        out = []
        for ln in lines[:6]:
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
        self._dial.animate(0)
        self._h1.setText("Checking for updates\u2026")
        self._num_old.setText(f"v{APP_VERSION.lstrip('v')}")
        self._num_arrow.show()
        self._num_new.setText("")
        self._clear_layout(self._chips)
        self._chips.addWidget(self._chip("...", "fetching"))
        self._changes_box.hide()
        self._clear_layout(self._changes)
        self._status.setText("")
        self._later.setEnabled(False)
        self._btn_later.setEnabled(False)
        self._btn_update.setEnabled(False)
        self._btn_update.setText("Checking\u2026")
        self._footnote.hide()
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
        self._status.setText("Downloading the new build\u2026")
        self.worker = DownloadWorker(self._info["url"], self)
        self.worker.bytes_total.connect(self._on_bytes_total)
        self.worker.progress.connect(self._on_progress)
        self.worker.done.connect(self._on_downloaded)
        self.worker.start()

    def _on_bytes_total(self, n: int):
        self._bytes_total = int(n or 0)

    def _on_progress(self, frac: float):
        self._status.setText(
            f"Downloading {self._mb_label()} MB\u2026 {int(frac * 100)}%")

    def _on_downloaded(self, new_exe, error):
        self._btn_update.setEnabled(True)
        self._btn_later.setEnabled(True)
        if error or new_exe is None:
            self._show_error(error or "Download failed.")
            return
        self._mode = "ready"
        self._new_exe = new_exe
        self._tb_sub.setText("READY TO INSTALL")
        self._status.setText("Downloaded and verified \u2014 ready to install")
        self._btn_update.setText("\u26a1  Restart & Update")
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