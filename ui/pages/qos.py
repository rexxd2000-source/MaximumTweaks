"""Network QoS page — renders ``ui/qos.html`` (the reference design) in a
QWebEngine view and bridges every control to the real Windows Policy-based
QoS engine (engine.qos).

Layout, palette, type and breakpoints come verbatim from network-qos.html;
only the data layer is wired to the engine — toggles write PSched DSCP
policies, the segmented control maps to DSCP level, discovery lists games
whose exe genuinely exists on this PC.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget
from PySide6.QtWebChannel import QWebChannel

from config.app_config import ROOT
from engine import qos as eng
from ui.pages._web import make_webview
from ui.categories import logo_data_uri
from ui.widgets import toast

HTML_REL = Path("ui") / "qos.html"


def _html_path() -> Path:
    meipass = getattr(__import__("sys"), "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


class _QosWorker(QThread):
    """Runs one engine call (registry policy write + gpupdate) off the UI
    thread; reports success, label, and an optional follow-up closure."""

    done = Signal(bool, str)

    def __init__(self, fn, label):
        super().__init__()
        self.fn, self.label = fn, label

    def run(self):
        try:
            self.done.emit(bool(self.fn()), self.label)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, f"{self.label} ({exc})")


class _DiscoverWorker(QThread):
    done = Signal(object)

    def run(self):
        try:
            self.done.emit(eng.discover_games())
        except Exception:  # noqa: BLE001
            self.done.emit([])


class _QosBridge(QObject):
    """Registered as ``window.api`` for the QoS HTML page."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot()
    def ready(self):
        self._page.push()

    @Slot(bool)
    def setMaster(self, on):
        self._page.on_master(on)

    @Slot(str, str)
    def setLevel(self, name, level):
        self._page.on_level(name, level)

    @Slot(str, bool)
    def setEnabled(self, name, on):
        self._page.on_enabled(name, on)

    @Slot()
    def addGame(self):
        self._page.add_game()

    @Slot(str)
    def removeGame(self, name):
        self._page.remove_game(name)


class QosPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.state = eng.load_state()
        self.discovered: list[dict] = []
        self._payload: dict = {}
        self._workers: list[_QosWorker] = []
        self._discover: _DiscoverWorker | None = None

        self._web = make_webview(self)
        # Opaque dark paint on the view widget itself so there is never a
        # 1-second white flash while Chromium spins up / first paints.
        self._web.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._web.setAutoFillBackground(True)
        pal = self._web.palette()
        pal.setColor(QPalette.ColorRole.Base, QColor("#08080c"))
        pal.setColor(QPalette.ColorRole.Window, QColor("#08080c"))
        self._web.setPalette(pal)
        self._web.setStyleSheet("background:#08080c; border:none;")
        self._web.page().setBackgroundColor(QColor("#08080c"))
        settings = self._web.settings()
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(
            settings.WebAttribute.JavascriptCanOpenWindows, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        self._bridge = _QosBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            self._web.load(html.as_uri())
        else:
            self._web.setHtml(
                "<body style='background:#08080c;color:#9797ac;"
                "font-family:sans-serif;padding:40px;'>"
                f"qos.html not found at<br><code>{html}</code></body>")

        # Refresh the "PRIORITIZING NOW" per-row running state from Python —
        # the bridge drives all page data through push(), no JS polls needed.
        self._running = QTimer(self)
        self._running.timeout.connect(self.push)
        self._running.start(5000)

        self._start_discovery()

    # ------------------------------------------------------------ data

    def _start_discovery(self):
        self._discover = _DiscoverWorker()
        self._discover.done.connect(self._on_discovered)
        self._discover.start()

    def _on_discovered(self, found):
        hidden = set(self.state.get("hidden") or [])
        self.discovered = [g for g in found if g["name"] not in hidden]
        self.push()

    def _payload_data(self) -> dict:
        merged = {g["name"]: g for g in self.discovered}
        for name, meta in (self.state.get("games") or {}).items():
            if name not in merged and meta.get("exe"):
                merged[name] = {
                    "name": name,
                    "exe": meta["exe"],
                    "exe_name": str(meta["exe"]).split("\\")[-1],
                    "last_run": None,
                }
        games = []
        for g in merged.values():
            meta = self.state.get("games", {}).get(g["name"], {})
            last = g.get("last_run") or meta.get("last_run")
            games.append({
                "name": g["name"],
                "exe": g["exe"],
                "exe_name": g["exe_name"],
                "sub": eng.last_played_text(last),
                "level": meta.get("level", "high"),
                "enabled": bool(meta.get("enabled", False)),
            })
        return {"master": bool(self.state.get("master", True)),
                "games": games,
                "running": self.running_names(),
                "icon": logo_data_uri("network")}

    def push(self):
        self._payload = self._payload_data()
        self._js("window.onQos && window.onQos("
                 + _json(self._payload) + ")")

    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    # ------------------------------------------------------------ bridge

    def running_names(self) -> list[str]:
        if not self.state.get("master", True):
            return []
        out = []
        for name, meta in (self.state.get("games") or {}).items():
            exe_name = meta.get("exe_name") or ""
            if meta.get("enabled") and exe_name and eng.is_running(exe_name):
                out.append(exe_name)
        return out

    def on_master(self, on):
        self.state["master"] = on
        eng.save_state(self.state)
        if on:
            self._run(
                lambda: (eng.set_non_besteffort_reserve(True)
                         and all(eng.set_policy(n, r["exe"], r["level"])
                                 for n, r in self._enabled_rows())),
                "all enabled games prioritized",
                done=self.push)
        else:
            self._run(lambda: all(
                eng.remove_policy(n) for n in (self.state.get("games") or {})),
                "all QoS policies removed while master is off",
                done=self.push)

    def _enabled_rows(self):
        rows = []
        for name, meta in (self.state.get("games") or {}).items():
            if meta.get("enabled") and meta.get("exe"):
                rows.append((name, meta))
        return rows

    def on_level(self, name, level):
        meta = (self.state.get("games") or {}).setdefault(name, {})
        prev = meta.get("level", "high")
        meta["level"] = level
        eng.save_state(self.state)
        if meta.get("enabled") and self.state.get("master", True) \
                and meta.get("exe"):
            self._run(
                lambda: eng.set_policy(name, meta["exe"], level),
                f"{name} tagged {level.upper()} (DSCP {eng.LEVELS[level]['dscp']})",
                done=self.push, revert=lambda: self._revert_level(name, prev))

    def _revert_level(self, name, prev):
        meta = (self.state.get("games") or {}).get(name, {})
        meta["level"] = prev
        eng.save_state(self.state)

    def on_enabled(self, name, on):
        meta = (self.state.get("games") or {}).setdefault(name, {})
        meta["enabled"] = on
        eng.save_state(self.state)
        if on and self.state.get("master", True) and meta.get("exe"):
            self._run(
                lambda: eng.set_policy(name, meta["exe"],
                                       meta.get("level", "high")),
                f"{name} QoS policy live",
                done=lambda ok: self._reflect_enabled(name, ok))
        elif not on:
            self._run(lambda: eng.remove_policy(name),
                      f"{name} policy removed",
                      done=lambda ok: self._reflect_enabled(name, not ok))

    def _reflect_enabled(self, name, enabled):
        meta = (self.state.get("games") or {}).get(name, {})
        meta["enabled"] = bool(enabled)
        eng.save_state(self.state)
        self.push()

    def remove_game(self, name):
        meta = (self.state.get("games") or {}).pop(name, {})
        self.state.setdefault("hidden", [])
        if name not in self.state["hidden"]:
            self.state["hidden"].append(name)
        self.discovered = [g for g in self.discovered if g["name"] != name]
        eng.save_state(self.state)
        if meta.get("enabled") and meta.get("exe") \
                and self.state.get("master", True):
            self._run(lambda: eng.remove_policy(name),
                      f"{name} removed from QoS", done=self.push)
        else:
            self.push()

    def add_game(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the game's executable", "",
            "Executable (*.exe)")
        if not path:
            return
        name = str(path).split("\\")[-1].rsplit(".", 1)[0]
        hidden = self.state.get("hidden") or []
        if name in hidden:
            self.state["hidden"] = [h for h in hidden if h != name]
        meta = self.state["games"].setdefault(name, {})
        meta.update(exe=path, exe_name=str(path).split("\\")[-1],
                    level=meta.get("level", "high"),
                    enabled=self.state.get("master", True))
        eng.save_state(self.state)
        if name not in {g["name"] for g in self.discovered}:
            self.discovered.append({
                "name": name, "exe": path,
                "exe_name": str(path).split("\\")[-1], "last_run": None})
        self.push()
        if self.state.get("master", True):
            self._run(lambda: eng.set_policy(name, path, "high"),
                      f"{name} added and tagged HIGH")

    # ------------------------------------------------------------ workers

    def _run(self, fn, label, done=None, revert=None):
        w = _QosWorker(fn, label)
        w.done.connect(
            lambda ok, lab, _d=done, _r=revert: self._on_done(ok, lab, _d, _r))
        w.start()
        self._workers.append(w)

    def _on_done(self, ok, label, done=None, revert=None):
        if not ok and revert:
            revert()
        if done:
            done()
        toast(("Applied — " if ok else "Failed — ") + label
              + ("" if ok else " — reverting"),
              "success" if ok else "error", self)
        if not ok:
            self.push()

    def shutdown(self):
        for w in self._workers:
            w.wait(2000)


def _json(obj) -> str:
    import json
    return json.dumps(obj)