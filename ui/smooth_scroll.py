"""App-wide smooth inertial scrolling for the native Qt pages.

A port of the reference demo's ``loop``/``wheel``/``keydown``/``scroll``
handlers onto Qt: a per-scroll-area target is eased toward exponentially
(``pos += (target - pos) * (1 - exp(-dt * K))``) and written back to the
vertical scrollbar each frame. Wheel and keyboard events feed the target; a
manual scrollbar drag (or any other scroll) resynchronises target and position
so the two never fight. Under the OS reduced-motion setting the easing is
skipped and the target is applied directly.

The embedded HTML pages get the same feel from injected JavaScript (see
``ui/pages/_web.py``); this module covers every ``QAbstractScrollArea`` in the
native pages. A Python widget that overrides ``wheelEvent`` keeps its own
behaviour - the filter steps aside for it.
"""
from __future__ import annotations

import math
import os
import time

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

# Easing strength and snap threshold, matching the demo (K=7, snap<0.1px).
_K = 7.0
_SNAP = 0.1
# Pixels advanced per wheel notch (120 eighths of a degree) and per arrow key.
_NOTCH = 110.0
_ARROW = 120.0
# Frame period. 16ms ~= 60fps; the loop stops itself once everything settles.
_FRAME_MS = 16

_REDUCED_MOTION_CACHE: bool | None = None


def prefers_reduced_motion() -> bool:
    """Honour the OS "animate controls" setting (the Windows equivalent of the
    web ``prefers-reduced-motion`` media query). MT_REDUCED_MOTION=1 forces it
    on for testing. Mirrors ui/updater_dialog._prefers_reduced_motion so the
    whole app agrees on one answer."""
    global _REDUCED_MOTION_CACHE
    if _REDUCED_MOTION_CACHE is not None:
        return _REDUCED_MOTION_CACHE
    env = (os.environ.get("MT_REDUCED_MOTION")
           or os.environ.get("REDUCED_MOTION"))
    if env is not None:
        _REDUCED_MOTION_CACHE = env.strip().lower() not in ("0", "", "false", "no")
        return _REDUCED_MOTION_CACHE
    reduced = False
    try:
        import ctypes
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0)
        if ok and enabled.value == 0:
            reduced = True
    except Exception:  # noqa: BLE001 - non-Windows / restricted => play safe
        reduced = False
    _REDUCED_MOTION_CACHE = reduced
    return reduced


def _is_interactive(widget: QWidget | None) -> bool:
    """True for widgets whose own key handling must win over scrolling: text
    inputs, spin boxes, combo boxes, item views, sliders and buttons."""
    return isinstance(widget, (
        QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox,
        QAbstractItemView, QAbstractSlider, QAbstractButton,
    ))


class _Scroller(QObject):
    """Eases one scroll area's vertical scrollbar toward a target."""

    def __init__(self, area: QAbstractScrollArea, manager: "_Manager"):
        super().__init__(area)
        self.area = area
        self.manager = manager
        self.bar = area.verticalScrollBar()
        self.target = float(self.bar.value())
        self.pos = float(self.bar.value())
        self.last = time.perf_counter()
        self.active = False
        self._applying = False
        self.bar.valueChanged.connect(self._on_value_changed)
        try:
            self.bar.sliderPressed.connect(self._on_slider_pressed)
            self.bar.sliderReleased.connect(self._on_slider_released)
        except Exception:  # noqa: BLE001 - only present when usable
            pass

    # -- external scroll (drag / touch / programmatic) ----------------------
    def _on_value_changed(self, value):
        if self._applying:
            return
        # Somebody other than the loop moved the bar: adopt it so the next
        # wheel starts from where the user actually is.
        self.pos = self.target = float(value)
        self.active = False

    def _on_slider_pressed(self):
        self.active = False
        self.pos = self.target = float(self.bar.value())

    def _on_slider_released(self):
        self.pos = self.target = float(self.bar.value())
        self.active = False

    # -- input --------------------------------------------------------------
    def nudge(self, delta: float):
        lo, hi = self.bar.minimum(), self.bar.maximum()
        if hi <= lo:
            return
        self.target = max(float(lo), min(float(hi), self.target + delta))
        self.active = True
        self.last = time.perf_counter()
        self.manager._ensure_running()

    def jump(self, to_end: bool):
        lo, hi = self.bar.minimum(), self.bar.maximum()
        if hi <= lo:
            return
        self.target = float(hi if to_end else lo)
        self.active = True
        self.last = time.perf_counter()
        self.manager._ensure_running()

    # -- frame --------------------------------------------------------------
    def step(self, now: float) -> bool:
        if not self.active:
            return False
        dt = now - self.last
        self.last = now
        if dt <= 0 or dt > 0.25:
            dt = _FRAME_MS / 1000.0
        if self.manager.reduced:
            self.pos = self.target
        else:
            self.pos += (self.target - self.pos) * (1.0 - math.exp(-dt * _K))
        done = abs(self.target - self.pos) < _SNAP
        if done:
            self.pos = self.target
        value = int(round(self.pos))
        if value != self.bar.value():
            self._applying = True
            try:
                self.bar.setValue(value)
            finally:
                self._applying = False
        if done:
            self.active = False
            return False
        return True


class _Manager(QObject):
    """One per application: routes wheel/key input to a page's scroller."""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.reduced = prefers_reduced_motion()
        self._scrollers: dict[QAbstractScrollArea, _Scroller] = {}
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._tick)
        app.installEventFilter(self)

    def _ensure_running(self):
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self):
        now = time.perf_counter()
        busy = False
        for area, scroller in list(self._scrollers.items()):
            try:
                if scroller.step(now):
                    busy = True
            except RuntimeError:  # area was destroyed
                self._scrollers.pop(area, None)
        if not busy:
            self._timer.stop()

    def _scroller_for(self, area: QAbstractScrollArea) -> _Scroller:
        scroller = self._scrollers.get(area)
        if scroller is None:
            scroller = _Scroller(area, self)
            self._scrollers[area] = scroller
        return scroller

    # -- routing ------------------------------------------------------------
    @staticmethod
    def _area_for(obj: object) -> QAbstractScrollArea | None:
        widget = obj if isinstance(obj, QWidget) else None
        while widget is not None:
            if isinstance(widget, QAbstractScrollArea):
                return widget
            widget = widget.parentWidget()
        return None

    @staticmethod
    def _eligible(area: QAbstractScrollArea) -> bool:
        if area.property("mxNoSmoothScroll"):
            return False
        top = area.window()
        if top is not None:
            wtype = top.windowFlags() & Qt.WindowType.WindowType_Mask
            if wtype in (Qt.WindowType.Popup, Qt.WindowType.ToolTip):
                return False  # menus / combo dropdowns keep native scrolling
        bar = area.verticalScrollBar()
        return bar is not None and bar.maximum() > bar.minimum()

    @staticmethod
    def _child_owns_wheel(obj: object, area: QAbstractScrollArea) -> bool:
        """True when a Python widget between ``obj`` and the area (exclusive)
        defines its own ``wheelEvent`` - then it, not us, drives the wheel.

        Only Python-defined classes are considered: PySide's generated classes
        all carry a ``wheelEvent`` in their ``__dict__``, so a plain C++ widget
        (the common case, including every viewport) must not be mistaken for a
        custom handler."""
        widget = obj if isinstance(obj, QWidget) else None
        while widget is not None:
            cls = type(widget)
            module = getattr(cls, "__module__", "") or ""
            if not module.startswith("PySide6") and "wheelEvent" in cls.__dict__:
                return True
            if widget is area:
                break
            widget = widget.parentWidget()
        return False

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Type.Wheel:
            area = self._area_for(obj)
            if (area is not None and self._eligible(area)
                    and not self._child_owns_wheel(obj, area)):
                # Qt reports a downward wheel as a negative delta; the
                # scrollbar grows downward, so flip the sign to match native.
                delta = -event.pixelDelta().y()
                if delta == 0:
                    delta = int(-event.angleDelta().y() / 120.0 * _NOTCH)
                if delta:
                    self._scroller_for(area).nudge(delta)
                    event.accept()
                    return True
        elif et == QEvent.Type.KeyPress:
            focus = QApplication.focusWidget()
            if not _is_interactive(focus):
                area = self._area_for(focus)
                if area is not None and self._eligible(area):
                    key = event.key()
                    handled = True
                    if key == Qt.Key.Key_Down:
                        self._scroller_for(area).nudge(_ARROW)
                    elif key == Qt.Key.Key_Up:
                        self._scroller_for(area).nudge(-_ARROW)
                    elif key in (Qt.Key.Key_PageDown,):
                        self._scroller_for(area).nudge(
                            area.viewport().height() * 0.85)
                    elif key == Qt.Key.Key_PageUp:
                        self._scroller_for(area).nudge(
                            -area.viewport().height() * 0.85)
                    elif key == Qt.Key.Key_Home:
                        self._scroller_for(area).jump(False)
                    elif key == Qt.Key.Key_End:
                        self._scroller_for(area).jump(True)
                    else:
                        handled = False
                    if handled:
                        event.accept()
                        return True
        return False


_manager: _Manager | None = None


def install_smooth_scroll(app: QApplication) -> _Manager:
    """Install the app-wide smooth-scroll event filter (idempotent)."""
    global _manager
    if _manager is None:
        _manager = _Manager(app)
    return _manager
