"""Controller Overclock page.

Nine real optimizations along the signal path between a gamepad and Windows.
Every switch maps to a single, verifiable Windows setting, and every change is
snapshotted before it is made so ``Revert all`` restores the previous value
exactly -- including deleting the override entirely when Windows was using its
default.

The polling-rate selector is deliberately disabled: changing a pad's report rate
means rewriting the bInterval on its interrupt endpoint, which is kernel work
(a signed USB filter driver). This app ships no driver, so the page measures
the real rate and says plainly that it cannot change it.
"""
from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QWidget

from config.app_config import ROOT
from engine import controller as eng
from ui.pages._web import make_webview

_BG = "#08070f"
_GREEN = "#2dd4a7"
_AMBER = "#f0b34a"

# Snapshots live next to the exe (ROOT/data), so a restart can still revert.
_STATE_FILE = Path(ROOT) / "data" / "controller_cards.json"

_CARDS = (
    {"id": "suspend", "n": "1", "kind": "suspend", "impact": "high",
     "title": "USB selective suspend",
     "desc": "Turn off the USB port's own suspend. This is the #1 cause of "
             "dead zones on the first press after a pause.",
     "scope": "system-wide"},
    {"id": "usbpm", "n": "2", "kind": "pm", "src": "controller", "impact": "medium",
     "title": "USB power management",
     "desc": "Let the pad's own USB device idle without the system powering it "
             "down in the middle of a burst.",
     "scope": "per device"},
    {"id": "hid", "n": "3", "kind": "pm", "src": "hid", "impact": "medium",
     "title": "HID input optimization",
     "desc": "Exempt the HID endpoints from power management so buttons never "
             "arrive late.",
     "scope": "per device"},
    {"id": "hub", "n": "4", "kind": "pm", "src": "hubs", "impact": "low",
     "title": "USB hub power saving",
     "desc": "Keep the hub's own link powered so it stops renegotiating every "
             "time you touch the pad.",
     "scope": "hub"},
    {"id": "conn", "n": "5", "kind": "pm", "src": "bth", "bt": True, "impact": "medium",
     "title": "Connection stability",
     "desc": "Stop the pad's Bluetooth link from idling between bursts, so "
             "every input arrives on the same connection.",
     "scope": "no controller", "scope_live": "bluetooth"},
    {"id": "gamebar", "n": "6", "kind": "gamebar", "impact": "high",
     "title": "Xbox button focus steal",
     "desc": "Route the guide button through the overlay instead of letting it "
             "take focus away from the game.",
     "scope": "system-wide"},
    {"id": "usblpm", "n": "7", "kind": "lpm", "impact": "medium",
     "title": "USB 3 link power states",
     "desc": "Hold the xHCI link at full power so the first button press never "
             "waits on a link waking up. Takes effect after a reboot.",
     "scope": "xHCI ports"},
    {"id": "btradio", "n": "8", "kind": "pm", "src": "btradio", "bt": True,
     "impact": "high",
     "title": "Bluetooth radio power saving",
     "desc": "Keep the Bluetooth adapter awake between packets. Latency only "
             "improves if the radio itself stays on.",
     "scope": "no controller", "scope_live": "bluetooth radio"},
    {"id": "prio", "n": "9", "kind": "prio", "impact": "medium",
     "title": "Foreground input priority",
     "desc": "Shorten the foreground quantum so a busy background process "
             "cannot hold the input thread for longer than one slice.",
     "scope": "system-wide"},
    {"id": "msi", "n": "10", "kind": "msi", "impact": "high",
     "title": "MSI interrupt delivery",
     "desc": "Deliver the controller's interrupts on its own message-signalled "
             "line instead of a shared legacy channel, so input is not stuck "
             "behind another device. Takes effect after a reboot.",
     "scope": "xHCI host"},
    {"id": "epm", "n": "11", "kind": "devparam", "src": "path", "val": "epm",
     "impact": "medium",
     "title": "Enhanced power management",
     "desc": "Turn off the enhanced power management stack on the pad's own "
             "device nodes, which is what decides whether Windows may drop a "
             "link while you are still holding the buttons.",
     "scope": "pad path"},
    {"id": "dss", "n": "12", "kind": "devparam", "src": "controller",
     "val": "dss", "impact": "medium",
     "title": "Device selective suspend",
     "desc": "Stop the USB device node from idling into a suspended state on "
             "its own, the other half of the sleep that selective suspend "
             "starts.",
     "scope": "pad device"},
)

_LPM_OPTIMIZED = 65535

HTML_REL = "ui/controller.html"


def _html_path() -> Path:
    """Bundled when frozen (sys._MEIPASS), source tree in dev."""
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ workers

class _DetectWorker(QThread):
    done = Signal(object)

    def run(self):
        data = eng.detect()
        # Skip the virtual "System Controller" / generic gamepad nodes; acting
        # on one of those would change power settings for the whole machine.
        pads = [p for p in (data.get("pads") or [])
                if p.get("name")
                and "system controller" not in p["name"].lower()]
        data["pads"] = pads
        data["driver"] = eng.driver_version(pads[0].get("id") or "") if pads else None
        self.done.emit(data)


class _TestWorker(QThread):
    done = Signal(object)

    def __init__(self, pad, parent=None):
        super().__init__(parent)
        self._pad = pad

    def run(self):
        try:
            self.done.emit(eng.test_controller(self._pad))
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"ok": False, "note": exc.__class__.__name__})


class _OpWorker(QThread):
    """Applies a list of (label, fn, args) off the UI thread."""

    done = Signal(object)

    def __init__(self, ops, parent=None):
        super().__init__(parent)
        self._ops = ops

    def run(self):
        applied, failed = [], []
        for label, fn, args in self._ops:
            try:
                ok = bool(fn(*args))
            except Exception as exc:  # noqa: BLE001
                ok, label = False, f"{label} ({exc.__class__.__name__})"
            (applied if ok else failed).append(label)
        self.done.emit({"applied": applied, "failed": failed})


# -------------------------------------------------------------------- bridge

class _ControllerBridge(QObject):
    """Registered as ``window.pywebview.api`` on the controller page."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot()
    def ready(self):
        self._page.push()

    @Slot()
    def test(self):
        self._page.run_test()

    @Slot(str)
    def applyMany(self, ids_json):
        self._page.request_apply(json.loads(ids_json or "[]"))

    @Slot()
    def revertAll(self):
        self._page.request_revert_all()


# ---------------------------------------------------------------------- page

class ControllerPage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.pad = None
        self.detect_data = None
        self._test_res = None
        self._rel: dict = {}
        self._btradio: list[str] = []
        self._on: dict[str, bool] = {}
        self._saved: dict[str, dict] = {}
        self._detect_worker = None
        self._test_worker = None
        self._op_worker = None
        self._busy = False

        self._load_saved()

        self._web = make_webview(self)
        self._web.setStyleSheet(f"background:{_BG}; border:none;")
        self._web.page().setBackgroundColor(QColor(_BG))
        self._web.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._web.customContextMenuRequested.connect(self._text_menu)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _ControllerBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            self._web.load(QUrl.fromLocalFile(str(html)))
        else:
            self._web.setHtml(
                f"<body style='background:{_BG};color:#8d88ac;"
                "font-family:sans-serif;padding:40px;'>"
                f"controller.html not found at<br><code>{html}</code></body>")
        self._web.loadFinished.connect(self._on_load_finished)

    # ------------------------------------------------------- JS transport

    def _text_menu(self, pos) -> None:
        """Minimal right-click menu so page text stays copyable.

        make_webview() suppresses Chromium's stock menu app-wide because its
        Back/Forward/Reload entries look out of place beside the dark shell.
        That also removes the only way to copy a value off the page, so this
        page offers just the two text actions, and only when the page reports
        a live selection.
        """
        self._web.page().runJavaScript(
            "(window.getSelection() ? String(window.getSelection()) : '').trim()",
            lambda text: self._show_text_menu(pos, text or ""),
        )

    def _show_text_menu(self, pos, text: str) -> None:
        if not text:
            return
        menu = QMenu(self)
        copy_act = menu.addAction("Copy")
        copy_act.triggered.connect(lambda: QApplication.clipboard().setText(text))
        sel_all = menu.addAction("Select all")
        sel_all.triggered.connect(
            lambda: self._js(
                "document.body.style.userSelect='text';"
                "document.body.style.webkitUserSelect='text';"
                "var r=document.createRange();r.selectNodeContents(document.body);"
                "var s=window.getSelection();s.removeAllRanges();s.addRange(r);1"
            )
        )
        menu.exec(self._web.viewport().mapToGlobal(pos))

    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    def _on_load_finished(self, ok):
        self.push()

    def _toast(self, stype, title, sub=None):
        self._js("window.mx && window.mx.showToast({}, {}, {})".format(
            json.dumps(stype), json.dumps(title), json.dumps(sub or "")))

    def _set_busy(self, busy, label="Working..."):
        self._busy = busy
        self._js("window.mx && window.mx.setBusy({}, {})".format(
            json.dumps(bool(busy)), json.dumps(label)))

    def showEvent(self, ev):
        super().showEvent(ev)
        if self.detect_data is None and self._detect_worker is None:
            self._start_detect()

    # ------------------------------------------------------------- storage

    def _load_saved(self):
        try:
            self._saved = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if not isinstance(self._saved, dict):
                self._saved = {}
        except Exception:  # noqa: BLE001
            self._saved = {}

    def _store_saved(self):
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(
                json.dumps(self._saved, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ----------------------------------------------------------- detection

    def _start_detect(self):
        self._detect_worker = _DetectWorker()
        self._detect_worker.done.connect(self._on_detect)
        self._detect_worker.start()

    def _on_detect(self, data):
        self.detect_data = data
        self.pad = (data.get("pads") or [None])[0]
        self._rel = eng.related_instances(self.pad) if self.pad else {}
        self._btradio = eng.bt_radio_instances() if self.pad else []
        self.push()

    # ------------------------------------------------------------ targets

    def _targets(self, card) -> list[str]:
        """Device instances a per-device card acts on; empty = not present."""
        if card.get("src") == "btradio":
            return list(self._btradio)
        if not self.pad:
            return []
        if card.get("src") == "path":
            rel = self._rel or {}
            seen, out = set(), []
            for kind in ("hid", "controller"):
                for base in (rel.get(kind) or {}):
                    if base not in seen:
                        seen.add(base)
                        out.append(base)
            return out
        if card.get("src") == "bth":
            if (self.pad.get("conn") or "").lower() != "bluetooth":
                return []
            base = str(self.pad.get("id") or "").lower()
            hits = [k for k in eng._PM_CACHE if k.startswith("bth\\")]
            if base:
                tail = base.rsplit("\\", 1)[-1].rsplit("&", 1)[-1]
                near = [k for k in hits if tail and tail in k.lower()]
                hits = near or hits
            return sorted(hits)
        return list((self._rel or {}).get(card.get("src") or "") or {})

    def _avail(self, card) -> tuple[bool, str]:
        if card["kind"] in ("suspend", "gamebar", "lpm", "prio"):
            return True, ""
        if card["kind"] == "msi":
            if not self.pad:
                return False, "no controller"
            if not eng._xhci_instance(self.pad):
                return False, "no xHCI link"
            return True, ""
        if self._targets(card):
            return True, ""
        return False, "bluetooth only" if card.get("bt") else "no controller"

    # -------------------------------------------------------------- state

    def _read_state(self, card) -> bool:
        """True when the optimization is actually in place in Windows."""
        kind = card["kind"]
        if kind == "suspend":
            # ON == suspend disabled, which is the inverse of the raw setting.
            return eng.selective_suspend_get() is False
        if kind == "gamebar":
            return eng.gamebar_get() == 0
        if kind == "lpm":
            return eng.lpm_get() == _LPM_OPTIMIZED
        if kind == "prio":
            return eng.win32_prio_get() == eng.PRIORITY_SEPARATION_GAMING
        if kind == "pm":
            tg = self._targets(card)
            return bool(tg) and all(eng._PM_CACHE.get(t) is False for t in tg)
        if kind == "msi":
            return self.pad is not None and eng.msi_get(self.pad) is True
        if kind == "devparam":
            tg = self._targets(card)
            if not tg:
                return False
            getter = (eng.epm_get if card.get("val") == "epm" else eng.dss_get)
            return all(getter([t]).get(t) == 0 for t in tg)
        return False

    def _snapshot(self, card) -> dict:
        """Capture the pre-change value so revert can restore it exactly."""
        kind = card["kind"]
        if kind == "suspend":
            return {"sel": eng.selective_suspend_get()}
        if kind in ("gamebar", "lpm", "prio"):
            getter = {"gamebar": eng.gamebar_get,
                      "lpm": eng.lpm_get,
                      "prio": eng.win32_prio_get}[kind]
            return {"v": getter()}
        if kind == "pm":
            return {"pm": {t: eng._PM_CACHE.get(t) for t in self._targets(card)}}
        if kind == "msi":
            return {"v": eng.msi_raw(self.pad) if self.pad else None}
        if kind == "devparam":
            tg = self._targets(card)
            getter = (eng.epm_get if card.get("val") == "epm" else eng.dss_get)
            return {"vals": getter(tg), "name":
                    (eng._ENHANCED_PM if card.get("val") == "epm"
                     else eng._DEVICE_SUSPEND)}
        return {}

    # ---------------------------------------------------------------- ops

    def _ops_for(self, card, on: bool) -> list[tuple]:
        """Engine calls for one card. Empty means it has nothing to do."""
        kind, cid = card["kind"], card["id"]
        saved = self._saved.get(cid) or {}
        if kind == "suspend":
            if on:
                return [("USB selective suspend", eng.selective_suspend_set, (True,))]
            # sel True == suspend enabled, which is the Windows default.
            return [("USB selective suspend", eng.selective_suspend_set,
                     (saved.get("sel") is not False,))]
        if kind == "gamebar":
            if on:
                return [("Xbox button focus steal", eng.gamebar_set, (0,))]
            orig = saved.get("v")
            if orig is None:
                return [("Xbox button focus steal", eng.gamebar_delete, ())]
            return [("Xbox button focus steal", eng.gamebar_set, (int(orig),))]
        if kind == "lpm":
            val = _LPM_OPTIMIZED if on else saved.get("v")
            return [("USB 3 link power states", eng.lpm_set_raw, (val,))]
        if kind == "prio":
            if on:
                return [("Foreground input priority", eng.win32_prio_set,
                         (eng.PRIORITY_SEPARATION_GAMING,))]
            orig = saved.get("v")
            if orig is None:
                return [("Foreground input priority", eng.win32_prio_delete, ())]
            return [("Foreground input priority", eng.win32_prio_set, (int(orig),))]
        if kind == "pm":
            tg = self._targets(card)
            if not tg:
                return []
            title = card["title"]
            if on:
                return [(title, eng.device_pm_set, (tg, False))]
            groups: dict = {}
            for inst in tg:
                groups.setdefault(bool((saved.get("pm") or {}).get(inst)), []).append(inst)
            return [(title, eng.device_pm_set, (insts, val))
                    for val, insts in groups.items() if insts]
        if kind == "msi":
            if on:
                return [("MSI interrupt delivery", eng.msi_set_raw, (self.pad, 1))]
            return [("MSI interrupt delivery", eng.msi_set_raw,
                     (self.pad, saved.get("v")))]
        if kind == "devparam":
            tg = self._targets(card)
            if not tg:
                return []
            title = card["title"]
            name = saved.get("name")
            if on:
                setter = (eng.epm_set if card.get("val") == "epm"
                          else eng.dss_set)
                return [(title, setter, (tg, True))]
            # Exact restore: put back the original DWORD, or delete the value
            # again when Windows had not set it before.
            prev = saved.get("vals") or {}
            return [(title, eng.devparam_set, ([inst], name, prev.get(inst)))
                    for inst in tg if inst in prev]
        return []

    # ------------------------------------------------------------- actions

    def request_apply(self, ids):
        cards = {c["id"]: c for c in _CARDS}
        ops, blocked = [], []
        for cid in ids:
            card = cards.get(cid)
            if not card:
                continue
            avail, _ = self._avail(card)
            if not avail:
                blocked.append(card["title"])
                continue
            if card["id"] not in self._saved:
                self._saved[card["id"]] = self._snapshot(card)
            ops.extend(self._ops_for(card, True))
        if not ops:
            if blocked:
                self._toast("warn", "Nothing applied",
                            ", ".join(blocked) + " has no matching device.")
            return
        self._store_saved()
        self._run_ops(ops, "applied")

    def request_revert_all(self):
        cards = {c["id"]: c for c in _CARDS}
        ops, names = [], []
        for cid, saved in self._saved.items():
            card = cards.get(cid)
            if not card:
                continue
            ops.extend(self._ops_for(card, False))
            names.append(card["title"])
        if not ops:
            self._toast("info", "Nothing to revert",
                        "no optimization has been changed by this page yet.")
            return
        self._run_ops(ops, "reverted", names=names)

    def _run_ops(self, ops, verb, names=None):
        if self._op_worker and self._op_worker.isRunning():
            return
        self._set_busy(True, "Applying...")
        self._op_worker = _OpWorker(ops)
        self._op_worker.done.connect(lambda r, v=verb, n=names: self._finish(r, v, n))
        self._op_worker.start()

    def _finish(self, res, verb, names=None):
        self._set_busy(False)
        failed, applied = res["failed"], res["applied"]
        if failed:
            self._toast("warn", f"{len(applied)} {verb}, {len(failed)} failed",
                        ", ".join(failed) + ".")
        else:
            extra = ""
            if applied and "USB 3 link power states" in applied:
                extra = " The link power change needs a reboot."
            if applied and not _is_admin():
                extra += " Some system-wide rows need administrator rights."
            self._toast("success", f"{len(applied)} {verb}", extra)
        if verb == "reverted" and not failed:
            self._saved.clear()
            self._store_saved()
        else:
            self._on.clear()
        self.push()

    # --------------------------------------------------------- polling test

    def run_test(self):
        if self._test_worker and self._test_worker.isRunning():
            return
        if not self.pad:
            self._toast("warn", "No controller detected",
                        "connect one and try again")
            self._set_busy(False)
            return
        self._set_busy(True, "Measuring...")
        self._test_worker = _TestWorker(self.pad)
        self._test_worker.done.connect(self._on_test)
        self._test_worker.start()

    def _on_test(self, res):
        self._set_busy(False)
        self._test_res = res
        self.push()
        if not res.get("ok"):
            self._toast("warn", "No input seen",
                        res.get("note") or "press buttons or move a stick")
            return
        live = [n for n, k in (("sticks OK", "axes"), ("triggers OK", "triggers"),
                               ("buttons OK", "buttons")) if res.get(k)]
        self._toast("success", f"~{res.get('hz')} Hz report rate",
                    (", ".join(live) + " · " if live else "") + "measured live")

    # -------------------------------------------------------------- render

    def _cards_payload(self) -> list[dict]:
        out = []
        for card in _CARDS:
            avail, why = self._avail(card)
            on = self._on.get(card["id"])
            if on is None:
                on = self._read_state(card) if avail else False
            if avail:
                tag, tagcls = (f"{card['impact']} impact",
                               "g" if card["impact"] == "high" else "a")
                scope = card.get("scope_live", card["scope"])
            else:
                tag, tagcls = why, "v" if why == "bluetooth only" else "a"
                scope = card["scope"]
            out.append({"id": card["id"], "n": card["n"], "title": card["title"],
                        "desc": card["desc"],
                        "scope": scope, "tag": tag, "tagcls": tagcls,
                        "avail": avail, "on": bool(on)})
        return out

    def _payload(self) -> dict:
        data = self.detect_data or {}
        dev = {"found": False}
        if self.pad:
            dev = {"found": True, "name": self.pad.get("name"),
                   "conn": self.pad.get("conn"), "id": self.pad.get("id"),
                   "driver": data.get("driver")}
        res = self._test_res or {}
        poll = {"ok": bool(res.get("ok")), "hz": res.get("hz"),
                "consistency": res.get("consistency"), "avg_ms": res.get("avg_ms"),
                "path": res.get("path"), "intervals": res.get("intervals") or []}
        return {"dev": dev, "cards": self._cards_payload(), "poll": poll}

    def push(self):
        self._js("window.mx && window.mx.setData({})".format(
            json.dumps(self._payload())))
