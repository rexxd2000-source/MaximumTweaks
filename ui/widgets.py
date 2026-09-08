"""Reusable UI widgets: premium cards, badges, dialogs and the launch screen.

Design rules (see config.app_config.THEME):
  * neutrals build the surface hierarchy (deep bg -> panels -> cards)
  * green = applied/enabled/success   red = disabled/reverted/error
  * yellow = warning/attention        accent = the only decorative color
"""
from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    QThread,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from database import BY_ID
from engine import activity, applier, state as state_mgr
from ui.categories import affects_for, group_key_for_category, logo_path


def qss_rgba(color: str, alpha_byte: int) -> str:
    """QSS color with alpha.

    Qt Style Sheets parse 8-digit hex as ``#AARRGGBB`` (alpha FIRST), so
    appending two alpha digits to a ``#RRGGBB`` color (e.g. ``"#8B5CF622"``)
    silently renders the WRONG hue. Build an explicit ``rgba(...)`` string
    instead.
    """
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_byte / 255:.3f})"


RISK_COLORS = {
    "safe": T["success"],
    "low": T["text_dim"],
    "moderate": T["warning"],
    "advanced": T["danger"],
}
STATE_COLORS = {
    "ready": T["success"],
    "optional": T["text_dim"],
    "incompatible": T["danger"],
    "not_for_you": T["text_faint"],
    "warning": T["danger"],
}
IMPACT_COLORS = {
    "extreme": T["accent"],
    "high": T["accent"],
    "moderate": T["text_dim"],
    "low": T["text_faint"],
    "very low": T["text_faint"],
}

# Short tag labels used on premium game-profile cards.
TAG_SHORT = {
    "fps": "FPS",
    "input": "Input",
    "latency": "Latency",
    "network": "Network",
    "graphics": "Graphics",
    "performance": "Performance",
    "mouse": "Mouse",
    "audio": "Audio",
    "power": "Power",
    "game": "Game",
    "cpu": "CPU",
    "gpu": "GPU",
    "ram": "RAM",
    "storage": "SSD",
}


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def badge(text, color, filled=False):
    lbl = QLabel(text)
    lbl.setObjectName("Badge")
    if filled:
        lbl.setStyleSheet(
            f"background-color: {color}; color: {T['accent_dark']};"
            "border-radius: 8px; padding: 2px 8px; font-size: 10.5px;"
            "font-weight: 800; letter-spacing: 0.5px;")
    else:
        lbl.setStyleSheet(
            "color: #8B5CF6; background-color: rgba(139, 92, 246, 0.08);"
            "border: 1px solid rgba(139, 92, 246, 0.25);"
            "border-radius: 8px; padding: 2px 8px; font-size: 12px;"
            "font-weight: 500; letter-spacing: 0.5px;")
    return lbl


def chip(text, color=None):
    lbl = QLabel(text)
    lbl.setObjectName("Badge")
    if color:
        qc = QColor(color)
        lbl.setStyleSheet(
            f"color: {color};"
            f"background-color: rgba({qc.red()}, {qc.green()}, {qc.blue()}, 26);"
            f"border: 1px solid rgba({qc.red()}, {qc.green()}, {qc.blue()}, 90);"
            "border-radius: 8px; padding: 2px 8px; font-size: 12px;"
            "font-weight: 500; letter-spacing: 0.5px;")
    else:
        lbl.setStyleSheet(
            "color: #8B5CF6; background-color: rgba(139, 92, 246, 0.08);"
            "border: 1px solid rgba(139, 92, 246, 0.25);"
            "border-radius: 8px; padding: 2px 8px; font-size: 12px;"
            "font-weight: 500; letter-spacing: 0.5px;")
    return lbl


def pill(text, color, filled=True):
    """StatusPill — the bold applied/disabled/ready state label."""
    lbl = QLabel(text)
    lbl.setObjectName("StatusPill")
    if filled:
        ss = f"background-color: {color}; color: {T['accent_dark']};"
    else:
        ss = ("color: #8B5CF6; background-color: rgba(139, 92, 246, 0.08);"
              " border: 1px solid rgba(139, 92, 246, 0.25);")
    lbl.setStyleSheet(
        ss + "border-radius: 9px; padding: 3px 10px; font-size: 12px;"
        "font-weight: 500; letter-spacing: 0.6px;")
    return lbl


def risk_badge(risk):
    return badge(risk.capitalize(), RISK_COLORS.get(risk, T["text_dim"]))


def state_badge(state):
    return badge(state.replace("_", " ").upper(), STATE_COLORS.get(state, T["text_dim"]))


def admin_badge():
    return badge("ADMIN", T["accent"], filled=True)


def rec_badge(value):
    if value == "recommended":
        return badge("RECOMMENDED", T["success"], filled=True)
    if value == "optional":
        return badge("OPTIONAL", T["text_dim"])
    if value == "advanced":
        return badge("ADVANCED", T["accent"])
    if value == "guide":
        return badge("GUIDE", T["info"])
    if value == "not_recommended":
        return badge("NOT RECOMMENDED", T["danger"])
    return None


def section_label(text):
    """Small uppercase section heading (e.g. 'PC PERFORMANCE')."""
    lbl = QLabel(text.upper())
    lbl.setObjectName("SectionLabel")
    return lbl


def stat_chip(value, label, color=None):
    """Header stat chip: bold colored value + uppercase label."""
    lbl = QLabel()
    lbl.setObjectName("StatChip")
    v = (f"<span style='color:{color or T['text']}; font-size:14px;"
         f"font-weight:800;'>{value}</span>")
    l = (f"<span style='color:{T['text_dim']}; font-size:11px;"
         f"font-weight:700;'>&nbsp;&nbsp;{label.upper()}</span>")
    lbl.setText(v + l)
    return lbl


def game_name(tweak) -> str:
    return (tweak.get("name") or "Profile").replace(" Profile", "").strip()


def clear_layout(layout):
    """Remove and immediately destroy every item in a layout.

    Widgets are hidden before being reparented so a repaint can never catch
    them mid-teardown as visible top-level windows overlapping the new
    content (the old clear_layout left them visible until the deferred
    delete ran, which showed stale cards on top of a freshly rebuilt grid).
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                clear_layout(child)


def initials(name: str) -> str:
    words = [w for w in name.replace("-", " ").split() if w and w[0].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


class IconTile(QLabel):
    """Rounded icon tile. Shows a tinted logo pixmap when ``logo`` is given,
    otherwise falls back to the ``char`` glyph (both share the tinted-glass
    tile background + soft border)."""

    def __init__(self, char, color, size=40, font_scale=0.5, radius=None,
                 bg=None, fg=None, logo=None, parent=None):
        super().__init__(parent)
        self._char = char
        self._color = color
        self._size = size
        self._font_scale = font_scale
        self._radius = radius if radius is not None else size // 2 - 2
        self._bg = bg or qss_rgba(color, 0x22)
        self._fg = fg or color
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.set_logo(logo)

    def set_logo(self, logo=None):
        """Switch the tile to a tinted logo pixmap (path) or back to the glyph."""
        self._logo = logo
        ss = (f"background-color: {self._bg};"
              f" border-radius: {self._radius}px;"
              f" border: 1px solid {qss_rgba(self._color, 0x33)};")
        if logo is not None:
            pix = QPixmap(str(logo))
            if not pix.isNull():
                pad = max(5, int(self._size * 0.3))
                side = self._size - pad * 2
                self.setPixmap(pix.scaled(side, side, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
                self.setToolTip(self._char)
                self.setStyleSheet(ss)
                return
        self.setText(self._char)
        ss += (f" color: {self._fg};"
               f" font-size: {max(10, int(self._size * self._font_scale))}px;"
               f" font-weight: 900;")
        self.setStyleSheet(ss)
        self.setToolTip(self._char)


class Avatar(QWidget):
    """Circular profile-picture widget.

    Paints the stored PFP clipped to a circle with a subtle accent ring.
    Falls back to the initials letter on a dark tile when no picture is set.
    """

    def __init__(self, size=40, letter="R", ring=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._letter = letter[:2]
        self._ring = QColor(ring or T["accent"])
        self._pixmap = None

    def set_avatar(self, path_or_none):
        if path_or_none:
            pix = QPixmap(str(path_or_none))
            if not pix.isNull():
                self._pixmap = pix
                self.update()
                return
        self._pixmap = None
        self.update()

    def set_letter(self, text: str):
        self._letter = (text or "?")[:2]
        self.update()

    def has_picture(self) -> bool:
        return self._pixmap is not None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        d = min(w, h)

        if self._pixmap is not None:
            # clip to a circle then draw the pixmap cover-fit
            path = QPainterPath()
            path.addEllipse(1, 1, d - 2, d - 2)
            p.setClipPath(path)
            src = self._pixmap
            if src.width() != src.height():
                side = min(src.width(), src.height())
                src = src.copy(
                    (src.width() - side) // 2, (src.height() - side) // 2,
                    side, side)
            p.drawPixmap(1, 1, d - 2, d - 2, src)
            p.setClipping(False)
            ring = QColor(self._ring)
            ring.setAlpha(130)
            pen = p.pen()
            pen.setColor(ring)
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(0.8, 0.8, d - 1.6, d - 1.6)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#141A22"))
            p.drawEllipse(0, 0, d, d)
            ring = QColor(self._ring)
            ring.setAlpha(110)
            pen = p.pen()
            pen.setColor(ring)
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(0.8, 0.8, d - 1.6, d - 1.6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._ring))
            f = p.font()
            f.setPixelSize(max(9, int(d * 0.42)))
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._letter)


class ToggleSwitch(QAbstractButton):
    """iOS-style animated switch — cyan when checked, muted when off.

    Painted manually (QSS cannot express a knob + animated track), so it is
    unaffected by the global stylesheet.
    """

    TRACK_ON = QColor("#8B5CF6")
    TRACK_OFF = QColor("#232A35")
    TRACK_BORDER = QColor("#333B48")
    KNOB = QColor("#F2F5F9")
    KNOB_OFF = QColor("#8A94A5")
    TRACK_DISABLED = QColor("#161B22")
    KNOB_DISABLED = QColor("#3D4754")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.setFocusPolicy(Qt.StrongFocus)
        self._slide = 0.0
        self._anim = None
        self.toggled.connect(self._animate)

    # ---- animated "slide" property (0.0 off -> 1.0 on) ----
    def get_slide(self) -> float:
        return self._slide

    def set_slide(self, value: float):
        self._slide = max(0.0, min(1.0, float(value)))
        self.update()

    slide = Property(float, get_slide, set_slide)

    def _animate(self, checked: bool):
        target = 1.0 if checked else 0.0
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"slide", self)
        self._anim.setDuration(170)
        self._anim.setStartValue(self._slide)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def sizeHint(self):
        return self.size()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        on = self._slide
        r = h / 2.0

        if not self.isEnabled():
            track = ToggleSwitch.TRACK_DISABLED
            knob = ToggleSwitch.KNOB_DISABLED
            border = ToggleSwitch.TRACK_DISABLED.darker(115)
        else:
            track = ToggleSwitch._mix(ToggleSwitch.TRACK_OFF, ToggleSwitch.TRACK_ON, on)
            knob = ToggleSwitch.KNOB
            border = ToggleSwitch._mix(ToggleSwitch.TRACK_BORDER, ToggleSwitch.TRACK_ON, on)

        pen = QColor(border)
        pen.setAlpha(140)
        p.setPen(pen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, r, r)

        margin = 3.0
        knob_d = h - margin * 2
        x = margin + on * (w - margin * 2 - knob_d)
        y = margin
        if self.isEnabled():
            # subtle shadow under the knob
            shadow = QColor("#000000")
            shadow.setAlpha(int(90 * (1.0 - 0.0)))
            p.setBrush(shadow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(x + 0.5, y + 1.0, knob_d, knob_d)
        p.setPen(Qt.NoPen)
        p.setBrush(knob)
        p.drawEllipse(x, y, knob_d, knob_d)

    @staticmethod
    def _mix(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            255,
        )


TOAST_COLORS = {
    "success": T["accent"],
    "error": T["danger"],
    "info": T["text_dim"],
    "warning": T["warning"],
}


class Toast(QFrame):
    """Lightweight slide-in notification pinned to the bottom-right corner.

    Created as a floating child of the host window so it overlays any page;
    mouse events pass straight through it.
    """

    def __init__(self, host, text, kind="info"):
        super().__init__(host)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        color = TOAST_COLORS.get(kind, TOAST_COLORS["info"])

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        dot = QLabel("\u25cf")
        dot.setStyleSheet(f"color: {color}; font-size: 11px;")
        lay.addWidget(dot)
        msg = QLabel(text)
        msg.setStyleSheet(
            f"color: {T['text']}; font-size: 12.5px; font-weight: 600;")
        msg.setWordWrap(True)
        lay.addWidget(msg, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self.adjustSize()
        max_w = int(host.width() * 0.34)
        if self.width() > max_w:
            self.setFixedWidth(max_w)
            self.adjustSize()

    def show_anim(self):
        host = self.parentWidget()
        if host is None:
            return
        x = host.width() - self.width() - 24
        y = host.height() - self.height() - 24
        self.move(x, y)
        self.raise_()
        self.show()

        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        QTimer.singleShot(2600, self._dismiss)

    def _dismiss(self):
        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(320)
        fade.setStartValue(self._effect.opacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InCubic)
        fade.finished.connect(self.deleteLater)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        host = self.parentWidget()
        if host is not None:
            self.move(host.width() - self.width() - 24,
                      host.height() - self.height() - 24)


def toast(text, kind="info", parent=None):
    """Show a bottom-right notification on the nearest top-level window."""
    from PySide6.QtWidgets import QApplication
    host = parent
    while host is not None and host.parentWidget() is not None:
        host = host.parentWidget()
    if host is None:
        host = QApplication.activeWindow()
    if host is None:
        host = QApplication.instance().activeWindow()
    if host is None:
        return
    Toast(host, text, kind).show_anim()


class StatCard(QFrame):
    def __init__(self, icon, title, value="--", sub="", accent=T["accent"], parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        lay.addWidget(IconTile(icon, accent, size=38, font_scale=0.5))
        box = QVBoxLayout()
        box.setSpacing(1)
        value_lbl = QLabel(str(value))
        value_lbl.setObjectName("StatValue")
        value_lbl.setStyleSheet(f"color: {accent};")
        title_lbl = QLabel(title)
        title_lbl.setObjectName("StatLabel")
        box.addWidget(value_lbl)
        box.addWidget(title_lbl)
        if sub:
            sub_lbl = QLabel(sub)
            sub_lbl.setObjectName("Tag")
            box.addWidget(sub_lbl)
        lay.addLayout(box, 1)


class SectionHeader(QFrame):
    """Section title with a small accent tick on the left."""

    def __init__(self, text):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        tick = QFrame()
        tick.setFixedSize(3, 16)
        tick.setStyleSheet(
            f"background-color: {T['accent']}; border-radius: 1.5px;")
        lay.addWidget(tick)
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lay.addWidget(lbl)
        lay.addStretch()


class PageHeader(QFrame):
    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("Header")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        s = QLabel(subtitle)
        s.setObjectName("PageSub")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)


class GuideDialog(QDialog):
    """Step-by-step walkthrough for a guidance-only tweak.

    Shows the guide steps front and center (each guidance action becomes a
    numbered step) with the description and "why it matters" as context.
    """

    def __init__(self, tweak: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tweak["name"])
        self.resize(640, 520)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel(
            f"<b style='color:{T['accent']}'>{tweak['id']}</b> &nbsp;|&nbsp; "
            f"{tweak['category']}")
        lay.addWidget(head)

        desc = tweak.get("desc") or ""
        if desc:
            d = QLabel(desc)
            d.setObjectName("PageSub")
            d.setWordWrap(True)
            lay.addWidget(d)

        lay.addWidget(QLabel("<b>Steps</b>"))
        steps = QPlainTextEdit()
        steps.setReadOnly(True)
        steps.setMinimumHeight(180)
        n = 0
        for action in tweak.get("actions", []):
            if not isinstance(action, (list, tuple)) or not action:
                continue
            if action[0] != "guidance":
                continue
            n += 1
            text = action[1] if len(action) > 1 else ""
            steps.appendPlainText(f"{n}.  {text}")
        if n == 0:
            steps.appendPlainText("No manual steps are documented for this "
                                  "tweak \u2014 see the description above.")
        lay.addWidget(steps)

        why = tweak.get("why") or ""
        if why:
            lay.addWidget(QLabel("<b>Why it matters</b>"))
            w = QLabel(why)
            w.setObjectName("PageSub")
            w.setWordWrap(True)
            lay.addWidget(w)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class PreviewDialog(QDialog):
    """Shows the exact actions a tweak performs before applying."""
    def __init__(self, tweak, mode="actions", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Preview \u2014 {tweak['name']}")
        self.resize(680, 460)
        lay = QVBoxLayout(self)

        head = QLabel(
            f"<b style='color:{T['accent']}'>{tweak['id']}</b> &nbsp;|&nbsp; "
            f"{tweak['category']} &nbsp;|&nbsp; risk: <b>{tweak.get('risk', 'safe')}</b> "
            f"&nbsp;|&nbsp; impact: <b>{tweak.get('impact', 'low')}</b>")
        desc = QLabel(tweak.get("desc") or tweak.get("description") or "")
        desc.setObjectName("PageSub")
        desc.setWordWrap(True)
        lay.addWidget(head)
        lay.addWidget(desc)

        lay.addWidget(QLabel(""))
        actions = tweak.get(mode) or []
        if not actions:
            info = QLabel("This tweak has no direct actions (informational/guidance).")
            info.setObjectName("PageSub")
            lay.addWidget(info)
        else:
            lay.addWidget(QLabel(f"<b>{'Actions' if mode == 'actions' else 'Revert steps'}:</b>"))
            box = QPlainTextEdit()
            box.setReadOnly(True)
            for a in actions:
                box.appendPlainText(f"  \u2022 {format_action(a)}")
            lay.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


def format_action(action) -> str:
    """Render an action tuple/list as a readable one-liner."""
    if isinstance(action, dict):
        return (action.get("name") or "action") + f"  [{action.get('action_type', '?')}]"
    if not isinstance(action, (list, tuple)) or not action:
        return str(action)
    kind = action[0]
    if kind == "reg" and len(action) >= 5:
        return f"registry: {action[1]}\\{action[2]} = {action[3]}  ({action[4]})"
    if kind == "regall" and len(action) >= 5:
        return f"registry (all subkeys): {action[1]}\\{action[2]}\\* = {action[3]}  ({action[4]})"
    if kind == "regdel" and len(action) >= 3:
        return f"registry delete: {action[1]}\\{action[2]}"
    if kind == "regdelall" and len(action) >= 3:
        return f"registry delete (all subkeys): {action[1]}\\{action[2]}\\*"
    if kind == "regkeydel" and len(action) >= 2:
        return f"registry key delete: {action[1]}"
    if kind == "svc" and len(action) >= 3:
        return f"service: {action[1]} -> {action[2]}"
    if kind == "sc":
        return "service: " + " ".join(str(x) for x in action[1:])
    if kind in ("svcstart", "svcstop"):
        return f"service: {action[1]} -> {kind[3:].upper()}"
    if kind == "cmd":
        return f"command: {(action[1] if len(action) > 1 else '')[:120]}"
    if kind == "file" and len(action) >= 3:
        return f"file: {action[1]}"
    if kind == "power":
        return f"power: {action[1]} = {action[2]}" + (f"  ({action[3]})" if len(action) > 3 else "")
    if kind == "powerscheme":
        return "power scheme: " + " ".join(str(x) for x in action[1:])
    if kind == "sched":
        return f"scheduled task: {action[1]} -> {action[2]}"
    if kind == "appx":
        return f"appx: {action[1]} -> {action[2]}"
    if kind == "restart":
        return "restart explorer.exe"
    if kind == "mkdir":
        return f"create folder: {action[1]}"
    if kind == "guidance":
        return f"guidance: {(action[1] if len(action) > 1 else '')[:140]}"
    return str(action)


class FlowLayout(QLayout):
    """Wrapping layout — items flow to a new line when they don't fit."""

    def __init__(self, parent=None, margin=0, hspacing=6, vspacing=6):
        super().__init__(parent)
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(margin, margin, margin, margin)
        self._items: list[QLayoutItem] = []

    def __del__(self):
        while self.count():
            self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize(0, 0)
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test: bool):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            wid = it.widget()
            sh = it.sizeHint()
            hfw = wid.heightForWidth(sh.width()) if wid else -1
            w = sh.width()
            h = hfw if hfw >= 0 else sh.height()
            if x + w > right + 1 and line_h > 0:
                x = rect.x() + m.left()
                y = y + line_h + self._v
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x = x + w + self._h
            line_h = max(line_h, h)
        return y + line_h + m.bottom() - rect.y()


class TweakCard(QFrame):
    """Clean toggle-based tweak card.

    Layout:  40px glassmorphic icon box | title + id | iOS-style toggle.
             Below: concise slate description, then a row of muted chips.
    States:  default    -> muted border, toggle off
             applied    -> cyan border + soft glow, cyan toggle on, APPLIED badge
             reverted   -> soft red border, toggle off, DISABLED badge
             incompatible -> soft red border, toggle disabled, INCOMPATIBLE badge
    """

    GRID_HEIGHT = 180

    apply_requested = Signal(str)
    revert_requested = Signal(str)
    guide_requested = Signal(str)

    def __init__(self, ctx, tweak, parent=None, compact=False):
        super().__init__(parent)
        self.ctx = ctx
        self.tweak = tweak
        self.tid = tweak["id"]
        self.compact = compact
        self._syncing = False
        self._state = "default"
        self.setObjectName("tweak-card")
        self.setProperty("state", "default")

        group = group_key_for_category(tweak["category"], tweak)
        from ui.categories import CATEGORY_GROUPS
        self.meta = CATEGORY_GROUPS[group]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # ---- Head: icon box + title/id + toggle
        head = QHBoxLayout()
        head.setSpacing(10)
        self.icon_tile = IconTile(
            self.meta["icon"], self.meta.get("color", "#94a3b8"), size=40,
            font_scale=0.5, radius=10, bg="#1A202C",
            logo=logo_path(group))
        head.addWidget(self.icon_tile)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        name_lbl = QLabel(tweak["name"])
        name_lbl.setStyleSheet("font-size: 14px; font-weight: 800; color: #F2F5F9;")
        name_lbl.setWordWrap(True)
        id_lbl = QLabel(tweak["id"])
        id_lbl.setStyleSheet(
            f"font-size: 10px; color: {T['text_faint']};")
        title_box.addWidget(name_lbl)
        title_box.addWidget(id_lbl)
        head.addLayout(title_box, 1)
        if tweak.get("guidance"):
            self.toggle = None
            self.btn_guide = QPushButton("\u2139  Guide")
            self.btn_guide.setObjectName("Ghost")
            self.btn_guide.setCursor(Qt.PointingHandCursor)
            self.btn_guide.setToolTip("Open the step-by-step guide")
            self.btn_guide.clicked.connect(lambda: self.guide_requested.emit(self.tid))
            head.addWidget(self.btn_guide, alignment=Qt.AlignVCenter)
        else:
            self.toggle = ToggleSwitch()
            self.toggle.setToolTip("Toggle this tweak on / off")
            self.toggle.toggled.connect(self._on_toggle_clicked)
            head.addWidget(self.toggle, alignment=Qt.AlignVCenter)
        outer.addLayout(head)

        # ---- Description
        desc = QLabel(tweak.get("desc", ""))
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #94A3B8; font-size: 12.5px;")
        if not compact:
            desc.setMinimumHeight(34)
        outer.addWidget(desc)

        # ---- Meta row: state badge + category/impact chips (wraps when tight)
        chips = FlowLayout(hspacing=6, vspacing=5)
        self.state_badge = QLabel()
        self.state_badge.setObjectName("Badge")
        self.state_badge.hide()
        chips.addWidget(self.state_badge)
        from ui.categories import CATEGORY_LABELS
        cat = CATEGORY_LABELS.get(group, self.meta["title"])
        chips.addWidget(chip(cat, T["text_faint"]))
        impact = tweak.get("impact", "low")
        chips.addWidget(chip(impact.capitalize(), T["text_faint"]))
        if tweak.get("crafted_for"):
            chips.addWidget(chip("\u2726 " + tweak["crafted_for"], T["accent"]))
        outer.addLayout(chips)

        if not compact:
            outer.addStretch(1)

        # ---- Soft glow overlay for smooth applied/disabled transitions
        self._glow = QFrame(self)
        self._glow.setObjectName("TintOverlay")
        self._glow.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._glow_effect = QGraphicsOpacityEffect(self._glow)
        self._glow.setGraphicsEffect(self._glow_effect)
        self._glow_effect.setOpacity(0.0)
        self._glow.hide()

        compat = ctx.state_of(self.tid)
        if compat in ("incompatible", "not_for_you"):
            self._apply_state("incompatible", reasons=(
                ctx.eval.get(self.tid, {}).get("reasons", [])))
        else:
            self._apply_state(self._initial_state())

    # ---------------- State ----------------

    def _initial_state(self) -> str:
        """First paint: use known live state, else the app's own record,
        else show a neutral 'detecting' skeleton while the audit runs."""
        live = self.ctx.live_state(self.tid)
        if live is not None:
            return "applied" if live else "default"
        if self.tid in state_mgr.applied_ids():
            return "applied"
        return "detecting"

    def _current_state(self) -> str:
        live = self.ctx.live_state(self.tid)
        if live is not None:
            return "applied" if live else "default"
        if self.tid in state_mgr.applied_ids():
            return "applied"
        return "default"

    def set_detected(self, value):
        """Apply a live system-state result from the background audit."""
        if self._state in ("incompatible", "not_for_you"):
            return
        if value is None:
            self._apply_state(
                "applied" if self.tid in state_mgr.applied_ids() else "default")
        else:
            self._apply_state("applied" if value else "default")

    def _on_toggle_clicked(self, checked: bool):
        if self._syncing:
            return
        # Optimistic visual flip; the page's worker reconciles on completion.
        self._apply_state("applied" if checked else "reverted")
        if checked:
            self.apply_requested.emit(self.tid)
        else:
            self.revert_requested.emit(self.tid)

    def _set_badge(self, text, color, filled=False):
        if filled:
            ss = (f"background-color: {color}; color: {T['accent_dark']};")
        else:
            ss = (f"color: {color}; border: 1px solid {color};"
                  f" background-color: {qss_rgba(color, 0x1f)};")
        self.state_badge.setStyleSheet(
            ss + "border-radius: 8px; padding: 2px 8px; font-size: 10px;"
            "font-weight: 800; letter-spacing: 0.5px;")
        self.state_badge.setText(text)
        self.state_badge.show()

    def _style_icon(self, on: bool, dim: bool = False):
        if on:
            self.icon_tile.setStyleSheet(
                f"background-color: rgba(139, 92, 246, 0.10); color: #8B5CF6;"
                " border-radius: 10px; font-size: 20px; font-weight: 900;"
                " border: 1px solid rgba(139, 92, 246, 0.40);")
        else:
            self.icon_tile.setStyleSheet(
                "background-color: #1A202C; color: #94A3B8;"
                " border-radius: 10px; font-size: 20px; font-weight: 900;"
                f" border: 1px solid {'#4A5568' if dim else '#2A313C'};")

    def _apply_state(self, state, reasons=None):
        self.setProperty("state", state)
        self._state = state
        if self.toggle is None:
            # Guidance-only cards have no toggle; just style the frame.
            self._syncing = True
            self._hide_glow()
            self._syncing = False
            repolish(self)
            return

        self._syncing = True
        if state == "applied":
            self.toggle.setEnabled(True)
            self.toggle.setChecked(True)
            self._set_badge("ACTIVE", T["accent"], filled=True)
            self._style_icon(True)
            self._fade_glow(T["accent"], T["glow_green"])
        elif state == "detecting":
            self.toggle.setEnabled(False)
            self.toggle.setChecked(False)
            self.toggle.setToolTip("Checking system state\u2026")
            self._set_badge("SYNCING\u2026", T["text_faint"])
            self._style_icon(False, dim=True)
            self._hide_glow()
        elif state == "reverted":
            self.toggle.setEnabled(True)
            self.toggle.setChecked(False)
            self._set_badge("DISABLED", T["danger"])
            self._style_icon(False)
            self._fade_glow(T["danger"], T["glow_red"])
        elif state == "incompatible":
            self.toggle.setEnabled(False)
            self.toggle.setChecked(False)
            self._set_badge("INCOMPATIBLE", T["danger"], filled=True)
            self._style_icon(False, dim=True)
            self.toggle.setToolTip(
                "\n".join(reasons) if reasons else "Not compatible with this PC")
            self._hide_glow()
        else:
            self.toggle.setEnabled(True)
            self.toggle.setChecked(False)
            self.state_badge.hide()
            self._style_icon(False)
            self._hide_glow()
        self._syncing = False

        repolish(self)

    def _fade_glow(self, color, tint):
        self._glow.setStyleSheet(
            f"#TintOverlay {{ background-color: {tint};"
            f" border: 2px solid {color}; border-radius: 11px; }}")
        self._glow.show()
        self._glow.raise_()
        anim = QPropertyAnimation(self._glow_effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(self._glow_effect.opacity())
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._glow_anim = anim

    def _hide_glow(self):
        anim = QPropertyAnimation(self._glow_effect, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(self._glow_effect.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._glow.hide)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._glow.setGeometry(1, 1, max(0, self.width() - 2), max(0, self.height() - 2))

    def refresh(self):
        if self._state == "incompatible":
            return
        self._apply_state(self._current_state())


class ProfileCard(QFrame):
    """Premium game-profile card with tags, launch and deactivate controls."""

    launch_requested = Signal(str)
    deactivate_requested = Signal(str)

    def __init__(self, ctx, tweak, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tweak = tweak
        self.tid = tweak["id"]
        self.game = game_name(tweak)
        self.setObjectName("ProfileCard")

        self.status_badge = None
        self.deactivate_btn = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconTile(initials(self.game), T["purple"], size=46, font_scale=0.45))
        box = QVBoxLayout()
        box.setSpacing(0)
        name = QLabel(self.game)
        name.setStyleSheet("font-size: 17px; font-weight: 900;")
        sub = QLabel("COMPETITIVE PERFORMANCE")
        sub.setStyleSheet(
            f"color: {T['accent']}; font-size: 10.5px; font-weight: 800;"
            "letter-spacing: 1.2px;")
        box.addWidget(name)
        box.addWidget(sub)
        head.addLayout(box, 1)
        self.status_badge = badge("READY", T["accent"])
        head.addWidget(self.status_badge)
        lay.addLayout(head)

        tags = profile_tags(tweak)
        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)
        for tg in tags:
            tag_row.addWidget(chip(tg, T["purple"]))
        tag_row.addStretch()
        lay.addLayout(tag_row)

        desc = QLabel(tweak.get("desc", ""))
        desc.setObjectName("PageSub")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.btn_launch = QPushButton("LAUNCH PROFILE")
        self.btn_launch.setObjectName("Primary")
        self.btn_launch.setMinimumHeight(32)
        self.btn_launch.clicked.connect(lambda: self.launch_requested.emit(self.tid))
        foot.addWidget(self.btn_launch)
        self.deactivate_btn = QPushButton("Deactivate")
        self.deactivate_btn.setObjectName("Danger")
        self.deactivate_btn.clicked.connect(lambda: self.deactivate_requested.emit(self.tid))
        self.deactivate_btn.setVisible(False)
        foot.addWidget(self.deactivate_btn)
        foot.addStretch()
        lay.addLayout(foot)

        self.rebuild()

    def rebuild(self):
        active_now = state_mgr.get_active_profile() == self.game
        self.setProperty("active", "true" if active_now else "false")
        self.status_badge.setParent(None)
        self.status_badge = badge("ACTIVE" if active_now else "READY",
                                  T["success"] if active_now else T["accent"],
                                  filled=active_now)
        self.layout().itemAt(0).layout().addWidget(self.status_badge)
        self.deactivate_btn.setVisible(active_now)
        self.btn_launch.setText("RELAUNCH PROFILE" if active_now else "LAUNCH PROFILE")
        repolish(self)


def profile_tags(tweak) -> list[str]:
    tags = []
    for t in tweak.get("tags") or []:
        s = TAG_SHORT.get(str(t).lower())
        if s and s not in tags:
            tags.append(s)
        if len(tags) >= 3:
            break
    return tags or ["FPS", "Input", "Network"]


class BatchWorker(QThread):
    """Runs applier.run() off the UI thread with live progress signals."""

    progress = Signal(int, int, str, bool, str)  # done, total, tid, ok, summary
    batch_done = Signal(dict)
    batch_error = Signal(str)

    def __init__(self, ids, mode="apply", parent=None):
        super().__init__(parent)
        self.ids = ids
        self.mode = mode

    def run(self):
        try:
            result = applier.run(self.ids, self.mode, progress=self._on_progress)
            self.batch_done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.batch_error.emit(str(exc))

    def _on_progress(self, done, total, tid, ok, summary):
        self.progress.emit(done, total, tid, ok, summary)


class ProgressDialog(QDialog):
    """Modal dialog that runs a batch apply/revert and reports results."""

    def __init__(self, parent, ids, mode="apply", title=None):
        super().__init__(parent)
        verb = "Applying" if mode == "apply" else "Reverting"
        self.setWindowTitle(title or f"{verb} tweaks\u2026")
        self.setModal(True)
        self.resize(560, 420)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{verb} {len(ids)} tweak(s)\u2026</b>"))

        self.bar = QProgressBar()
        self.bar.setRange(0, len(ids))
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.current = QLabel("Starting\u2026")
        self.current.setObjectName("PageSub")
        lay.addWidget(self.current)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)

        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self._close_result)
        lay.addWidget(self.close_btn, alignment=Qt.AlignHCenter)

        self.worker = BatchWorker(ids, mode, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.batch_done.connect(self._on_done)
        self.worker.batch_error.connect(self._on_error)
        self.worker.start()
        self.result = None

    def _on_progress(self, done, total, tid, ok, summary):
        self.bar.setValue(done)
        name = BY_ID.get(tid, {}).get("name", tid) if tid else ""
        mark = "OK" if ok else "FAIL"
        color = T["success"] if ok else T["danger"]
        self.current.setText(f"({done}/{total}) {tid} \u2014 {name}")
        self.log.appendHtml(
            f"<span style='color:{color}'>{mark}</span>  {tid} \u2014 {name}<br/>"
            f"<span style='color:{T['text_dim']}'>  {summary}</span>")

    def _on_done(self, result):
        self.result = result
        applied = result.get("applied", [])
        failed = [tid for tid, (ok, _d) in result["results"].items() if not ok]
        self.current.setText(
            f"Done \u2014 {len(applied)} succeeded, {len(failed)} failed/blocked.")
        self.log.appendHtml(f"<br/><b>{len(applied)} succeeded, {len(failed)} failed.</b>")
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Close")

    def _on_error(self, msg):
        self.current.setText("Error")
        self.log.appendPlainText(f"ERROR: {msg}")
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Close")

    def _close_result(self):
        # Stop the worker thread if it's still running.
        if self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(2000)
        self.accept()


class LaunchStepRow(QWidget):
    """One animated row in the profile-launch step list."""

    def __init__(self, text):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.dot = QLabel("\u25cb")
        self.dot.setFixedWidth(20)
        self.dot.setStyleSheet(
            f"color: {T['text_faint']}; font-size: 16px; font-weight: 800;")
        self.label = QLabel(text)
        self.label.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px;")
        lay.addWidget(self.dot)
        lay.addWidget(self.label, 1)

    def set_running(self):
        self.dot.setText("\u25cb")
        self.dot.setStyleSheet(
            f"color: {T['accent']}; font-size: 16px; font-weight: 800;")
        self.label.setStyleSheet(
            f"color: {T['text']}; font-size: 13px; font-weight: 600;")

    def set_done(self):
        self.dot.setText("\u2713")
        self.dot.setStyleSheet(
            f"color: {T['success']}; font-size: 16px; font-weight: 900;")
        self.label.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px;")


class ProfileLaunchDialog(QDialog):
    """Animated 'LAUNCHING <GAME> PROFILE' screen that applies a profile."""

    def __init__(self, ctx, tweak, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tweak = tweak
        self.game = game_name(tweak)
        self.setWindowTitle(f"Launching {self.game} Profile")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.resize(600, 540)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(IconTile(initials(self.game), T["purple"], size=56, font_scale=0.42))
        box = QVBoxLayout()
        box.setSpacing(1)
        self.title = QLabel(f"LAUNCHING {self.game.upper()} PROFILE")
        self.title.setStyleSheet("font-size: 19px; font-weight: 900; letter-spacing: 0.5px;")
        self.subtitle = QLabel(tweak.get("desc", ""))
        self.subtitle.setObjectName("PageSub")
        self.subtitle.setWordWrap(True)
        box.addWidget(self.title)
        box.addWidget(self.subtitle)
        head.addLayout(box, 1)
        lay.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)

        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setStyleSheet(
            f"color: {T['accent']}; font-weight: 800; font-size: 12px;")
        self.pct_lbl.setAlignment(Qt.AlignRight)
        lay.addWidget(self.pct_lbl)

        steps_card = QFrame()
        steps_card.setObjectName("Card")
        self.steps_lay = QVBoxLayout(steps_card)
        self.steps_lay.setContentsMargins(18, 16, 18, 16)
        self.steps_lay.setSpacing(10)
        self.steps_rows = []
        for s in self._step_texts():
            row = LaunchStepRow(s)
            self.steps_lay.addWidget(row)
            self.steps_rows.append(row)
        self.steps_lay.addStretch()
        lay.addWidget(steps_card)

        self.status = QLabel("")
        self.status.setObjectName("PageSub")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        lay.addWidget(self.close_btn, alignment=Qt.AlignHCenter)

        self._step_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(430)
        self._timer.timeout.connect(self._next_step)
        self._timer.start()
        self._anim_tick = 0

    def _step_texts(self):
        return [
            "Loading profile\u2026",
            "Checking system\u2026",
            "Applying settings\u2026",
            "Optimizing configuration\u2026",
            "Finalizing\u2026",
        ]

    def _next_step(self):
        n = len(self.steps_rows)
        if self._step_idx < n:
            for i in range(self._step_idx):
                self.steps_rows[i].set_done()
            self.steps_rows[self._step_idx].set_running()
            self._step_idx += 1
            self.bar.setValue(int(self._step_idx / n * 100))
            self.pct_lbl.setText(f"{int(self._step_idx / n * 100)}%")
        else:
            self._timer.stop()
            for row in self.steps_rows:
                row.set_done()
            self.bar.setValue(100)
            self.pct_lbl.setText("100%")
            self._finish()

    def _finish(self):
        self.worker = BatchWorker([self.tweak["id"]], "apply", self)
        self.worker.batch_done.connect(self._done)
        self.worker.batch_error.connect(self._error)
        self.worker.start()

    def _done(self, result):
        ok = bool(result.get("applied"))
        if ok:
            state_mgr.set_active_profile(self.game)
            activity.emit("profile", f"Game profile launched: {self.game}")
            self.title.setText(f"\u2713 {self.game.upper()} PROFILE ACTIVE")
            self.title.setStyleSheet(
                f"font-size: 19px; font-weight: 900; color: {T['success']};")
            self.status.setText(
                f"{self.game} is now your active profile. All settings applied "
                "successfully \u2014 launch your game and enjoy the boost.")
        else:
            self.title.setText(f"\u2715 LAUNCH FAILED \u2014 {self.game.upper()}")
            self.title.setStyleSheet(
                f"font-size: 19px; font-weight: 900; color: {T['danger']};")
            self.status.setText("One or more steps could not be completed. See the logs.")
        self.close_btn.setEnabled(True)

    def _error(self, msg):
        self.title.setText(f"\u2715 LAUNCH FAILED \u2014 {self.game.upper()}")
        self.title.setStyleSheet(
            f"font-size: 19px; font-weight: 900; color: {T['danger']};")
        self.status.setText(f"Error: {msg}")
        self.close_btn.setEnabled(True)


class PerfCard(QFrame):
    """Premium live hardware panel used on the performance overview."""

    def __init__(self, icon, title, color, parent=None):
        super().__init__(parent)
        self.setObjectName("PerfCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(IconTile(icon, color, size=30, font_scale=0.5))
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 13px; font-weight: 800; letter-spacing: 0.8px; color: {color};")
        head.addWidget(t, 1)
        self.dot = QLabel("\u25cf")
        self.dot.setStyleSheet(f"color: {T['text_faint']}; font-size: 12px;")
        head.addWidget(self.dot)
        lay.addLayout(head)

        self.value = QLabel("--")
        self.value.setStyleSheet("font-size: 24px; font-weight: 900;")
        lay.addWidget(self.value)

        self.sub = QLabel("")
        self.sub.setObjectName("CardDetail")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)

        self.detail = QLabel("")
        self.detail.setStyleSheet(
            f"color: {T['text_faint']}; font-size: 11px;")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self._bar_color = T["accent"]
        lay.addWidget(self.bar)

    def set_bar_color(self, color):
        if color != self._bar_color:
            self._bar_color = color
            self.bar.setStyleSheet(
                f"QProgressBar {{ background-color: {T['bg_alt']}; border: none;"
                f" border-radius: 2.5px; }}"
                f"QProgressBar::chunk {{ background-color: {color};"
                f" border-radius: 2.5px; }}")

    def update_stats(self, value_text, sub_text="", pct=0, color=None, detail_text=None):
        self.value.setText(value_text)
        self.sub.setText(sub_text)
        if detail_text is not None:
            self.detail.setText(detail_text)
        self.bar.setValue(max(0, min(100, int(pct))))
        if color:
            self.value.setStyleSheet(f"font-size: 24px; font-weight: 900; color: {color};")
            self.set_bar_color(color)
            self.dot.setStyleSheet(f"color: {color}; font-size: 12px;")


class DiscordCard(QFrame):
    """Premium Official Discord card with a disabled COMING SOON join button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DiscordCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(14)

        logo = QLabel("D")
        logo.setFixedSize(48, 48)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background-color: {T['accent']}; color: {T['accent_dark']};"
            " border-radius: 24px;"
            "font-size: 26px; font-weight: 900;")
        lay.addWidget(logo)

        text = QVBoxLayout()
        text.setSpacing(2)
        t = QLabel("Official Discord")
        t.setStyleSheet("font-size: 16px; font-weight: 900; color: #e8eef5;")
        desc = QLabel("Join the official Maximum Tweaks community.")
        desc.setObjectName("Tag")
        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        badge_row.addWidget(pill("\u25cf COMING SOON", T["warning"], filled=True))
        badge_row.addStretch()
        badge_row.setContentsMargins(0, 0, 0, 0)
        text.addWidget(t)
        text.addWidget(desc)
        text.addLayout(badge_row)
        lay.addLayout(text, 1)

        btn = QPushButton("Join Discord")
        btn.setObjectName("Primary")
        btn.setDisabled(True)
        btn.setToolTip("The official Discord is coming soon.")
        lay.addWidget(btn, alignment=Qt.AlignVCenter)
