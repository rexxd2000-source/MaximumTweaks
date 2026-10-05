"""App Optimizers — embedded QtWebEngine page with a QWebChannel bridge.

The page exposes ``activate(key, option_ids)``, ``reset(key)``, ``detect()``
and ``optimizeAll()`` via ``window.pywebview.api``. Heavy work runs off the
UI thread (QThread workers) and the page receives JSON payloads for render.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel  # noqa: F401
from PySide6.QtWidgets import QVBoxLayout, QWidget

from config.app_config import ROOT
from engine.app_optimizer import activate as eng_activate
from engine.app_optimizer import apps as eng_apps
from engine.app_optimizer import detect as eng_detect
from engine.app_optimizer import reset as eng_reset
from ui.pages._web import make_webview

HTML_REL = "ui/app_optimizers.html"


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


class _Worker(QThread):
    done = Signal(object)
    note = Signal(str, str)

    def __init__(self, fn, *args, notify: bool = False, **kw):
        super().__init__()
        self._fn, self._args, self._kw = fn, args, kw
        self._notify = notify

    def run(self):
        try:
            # Hand the engine a signal emitter instead of a GUI callback: the
            # worker runs off the UI thread, and Qt queues cross-thread signal
            # connections safely. Touching the webview directly here would not
            # be safe.
            if self._notify:
                self._kw["notify"] = self.note.emit
            self.done.emit(self._fn(*self._args, **self._kw))
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc)})


class _Bridge(QObject):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot()
    def detect(self):
        self._page._detect()

    @Slot(str, list)
    def activate(self, key, option_ids):
        self._page._activate(key, option_ids or [])

    @Slot(str)
    def reset(self, key):
        self._page._reset(key)

    @Slot()
    def optimizeAll(self):
        self._page._optimize_all()


class AppOptimizersPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._web = make_webview(self)
        self._web.setStyleSheet("background:#0a0a12; border:none;")
        self._web.page().setBackgroundColor(QColor("#0a0a12"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)
        settings = self._web.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, False)
        self._channel = QWebChannel(self)
        self._bridge = _Bridge(self, self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)
        self._html = _html_path()
        if self._html.is_file():
            self._web.load(QUrl.fromLocalFile(str(self._html)))
        self._workers = []
        self._opt_run = False
        self._cancel = False

    def _js(self, s):
        self._web.page().runJavaScript(s)

    def _toast(self, t):
        self._js(f"window.mx && window.mx.showToast({json.dumps(t)})")

    def _set_busy(self, b):
        self._js(f"window.mx && window.mx.setBusy({json.dumps(b)})")

    def _payload(self) -> dict:
        apps = eng_detect()
        total_detected = sum(1 for v in apps.values() if v["installed"])
        total_engaged = sum(1 for v in apps.values() if v["engaged"])
        # Real measured reclaim (current working set vs the working set
        # captured when the app was first optimized). No estimates.
        ram_reclaimed = sum(v.get("ram_reclaimed_mb", 0.0)
                            for v in apps.values() if v["engaged"])
        disk_saved = sum(v.get("disk_saved_mb", 0.0)
                         for v in apps.values() if v["engaged"])
        return {"apps": apps, "totalDetected": total_detected,
                "totalEngaged": total_engaged,
                "ramReclaimed": round(ram_reclaimed, 1),
                "diskSaved": round(disk_saved, 1)}

    def _push(self):
        self._js(f"window.mx && window.mx.setData({json.dumps(self._payload())})")

    def _detect(self):
        w = _Worker(eng_detect)
        w.done.connect(lambda r: self._detect_done(r))
        self._workers.append(w)
        w.start()

    def _detect_done(self, res):
        if isinstance(res, dict) and res.get("error"):
            self._toast(res["error"])
            return
        self._push()

    def _activate(self, key, option_ids):
        # Scoped busy: only this card is locked, the other apps stay usable.
        self._card_busy(key, True)
        w = _Worker(eng_activate, key, option_ids, notify=True)
        w.note.connect(self._card_notify)
        w.done.connect(lambda r: self._activate_done(key, r))
        self._workers.append(w)
        w.start()

    def _card_busy(self, key, on):
        self._js(f"window.mx && window.mx.setCardBusy({json.dumps(key)}, {json.dumps(bool(on))})")

    def _card_notify(self, key, message):
        """Runs on the UI thread via the queued signal; shows 'Restarting X…'."""
        self._card_busy(key, True)
        self._js(f"window.mx && window.mx.setCardState({json.dumps(key)}, {json.dumps(message)}, 'busy')")

    def _activate_done(self, key, res):
        self._card_busy(key, False)
        if isinstance(res, tuple) and len(res) == 2:
            errors, changed = res
        elif isinstance(res, dict):
            if res.get("error"):
                self._toast(res["error"])
                return
            errors, changed = res.get("errors", []), res.get("changed", 0)
        else:
            errors, changed = [], 0
        if errors:
            self._toast("; ".join(errors))
        elif changed:
            self._toast("Optimized")
        self._push()

    def _reset(self, key):
        self._card_busy(key, True)
        w = _Worker(eng_reset, key)
        w.done.connect(lambda r: self._reset_done(key, r))
        self._workers.append(w)
        w.start()

    def _reset_done(self, key, res):
        self._card_busy(key, False)
        if isinstance(res, tuple) and len(res) == 2:
            errors, restored = res
        elif isinstance(res, dict):
            errors, restored = res.get("errors", []), res.get("restored", 0)
        else:
            errors, restored = [], 0
        if errors:
            self._toast("; ".join(errors))
        elif restored:
            self._toast(f"Restored {restored} change(s)")
        self._push()

    def _optimize_all(self):
        if self._opt_run:
            return
        self._opt_run = True
        self._cancel = False
        self._set_busy(True)
        self._progress(0, 1, "", "Starting…")
        w = _Worker(eng_apps.optimize_all, self._is_cancelled, self._progress,
                    restart=True)
        w.done.connect(lambda r: self._opt_all_done(r))
        self._workers.append(w)
        w.start()

    def _is_cancelled(self):
        return bool(getattr(self, "_cancel", False))

    def _progress(self, index, total, key, name):
        label = f"{name}…" if name else "Finishing…"
        self._js(f"window.mx && window.mx.setProgress({int(index)}, {int(total)}, {json.dumps(label)})")

    def _opt_all_done(self, res):
        self._opt_run = False
        self._set_busy(False)
        self._push()
        if isinstance(res, dict):
            total = sum(v.get("changed", 0) for v in res.values())
            errs = []
            for v in res.values():
                errs.extend(v.get("errors", []))
            if errs:
                self._toast(f"Done ({total} changes) · some errors")
            else:
                self._toast(f"Optimized {total} item(s)")
