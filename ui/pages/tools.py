"""Tools page — renders ``ui/tools.html`` (the redesign) inside an embedded
QtWebEngine view, and exposes a QWebChannel bridge under
``window.pywebview.api`` exactly like the other HTML pages.

The page's data is the real tool set: the five quick-launch shortcuts plus
every tool in the ``tools`` DB group, mapped onto the redesign's user-facing
categories (System, Network, Storage, Display, Hardware, Repair, Input, Audio,
USB, Startup). Python pushes it to the page as ``window.mxSetTools(payload)``.

Running a tool is unchanged: a ``ToolRunner`` QThread calls the same
``engine.tools_runner`` entry points as before, a failed launch raises the
native error toast, and guidance-only tweaks still open the native info dialog.
The page shows the transient "Running: <name>…" pill itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from config.app_config import ROOT
from engine.tools_runner import launch_tool, run_tweak
from ui.categories import group_tweaks
from ui.pages._web import make_webview
from ui.widgets import toast

HTML_REL = "ui/tools.html"

# Pills row, left to right. "All" always leads.
CATEGORY_TABS = [
    "All", "System", "Network", "Storage", "Display", "Hardware",
    "Repair", "Input", "Audio", "USB", "Startup",
]

QUICK_LAUNCH = [
    {"name": "Windows Version",
     "desc": "Check your Windows edition and OS build details.",
     "launch_key": "winver"},
    {"name": "System Information",
     "desc": "Open the full CPU, motherboard and hardware summary.",
     "launch_key": "msinfo32"},
    {"name": "DirectX Diagnostics",
     "desc": "Launch dxdiag for GPU, driver and feature-level info.",
     "launch_key": "dxdiag"},
    {"name": "Device Manager",
     "desc": "Manage drivers and connected hardware devices.",
     "launch_key": "devmgmt"},
    {"name": "Network Tools",
     "desc": "Flush the DNS cache and reset resolver state.",
     "launch_key": "flushdns"},
]

# Quick-launch tile order + the action label shown under each name.
_QUICK_TILE = [
    ("ql_winver", "Check Version"),
    ("ql_msinfo32", "Open Info"),
    ("ql_dxdiag", "Run dxdiag"),
    ("ql_devmgmt", "Open"),
    ("ql_flushdns", "Flush DNS"),
]

# Tool id -> the redesign's user-facing category. The quick-launch shortcuts and
# every DB tool are listed so the page never has to guess (and a newly added
# tool falls back to "System").
_CAT_BY_ID = {
    # quick launch
    "ql_winver": "System",
    "ql_msinfo32": "System",
    "ql_dxdiag": "Display",
    "ql_devmgmt": "System",
    "ql_flushdns": "Network",
    # Diagnostics
    "audio-033": "Audio",
    "audio-034": "Audio",
    "bios-001": "Hardware",
    "db-014": "Storage",
    "diag-001": "System",
    "diag-003": "Storage",
    "diag-004": "Repair",
    "diag-005": "Hardware",
    "diag-006": "Hardware",
    "diag-007": "Repair",
    "diag-008": "Startup",
    "diag-010": "Hardware",
    "diag-011": "System",
    "diag-012": "Display",
    "diag-014": "Startup",
    "dx-001": "Display",
    "dx-003": "Display",
    "eth-012": "Network",
    "eth-013": "Network",
    "fpsb-026": "Hardware",
    "gpu-047": "Display",
    "mon-003": "Display",
    "mon-014": "Display",
    "net-014": "Network",
    "net-015": "Network",
    "net-016": "Network",
    "rep-001": "Repair",
    "rep-002": "Repair",
    "rep-004": "Repair",
    "rep-007": "Repair",
    "rep-008": "Repair",
    "rep-009": "Repair",
    "rep-013": "Repair",
    "rep-014": "Storage",
    "sec-009": "Repair",
    "start-001": "Startup",
    "stor-008": "Storage",
    "stor-009": "Storage",
    "stor-010": "Storage",
    "sys-008": "Repair",
    "perf-new-001": "Display",
    "usb-003": "USB",
    "usb-004": "USB",
    "usb-012": "USB",
    "wifi-004": "Network",
    "wifi-008": "Network",
    "wifi-012": "Network",
    # Repair
    "rep-005": "Repair",
    "rep-015": "Repair",
    # System Tools
    "expl-014": "System",
    "gpu-048": "System",
    "mouse-055": "Input",
    "mouse-056": "Input",
    "mouse-057": "Input",
    "mouse-058": "Input",
    "tools-001": "System",
    "tools-002": "System",
    "tools-003": "System",
    "tools-004": "System",
    "tools-005": "System",
    "tools-006": "System",
    "tools-007": "System",
    "tools-008": "System",
    "tools-009": "System",
    "tools-010": "Storage",
    "tools-011": "System",
    "tools-012": "System",
    "tools-013": "System",
    "tools-014": "Network",
}


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


def _quick_launch_items() -> list[dict]:
    return [
        {**q, "id": "ql_" + q["launch_key"], "category": "Quick Launch"}
        for q in QUICK_LAUNCH
    ]


def _dedupe(items: list[dict]) -> list[dict]:
    """A quick-launch shortcut and a tweak of the same tool are one row."""
    out, seen = [], set()
    for t in items:
        k = t["name"].strip().lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


def _tool_rows() -> list[dict]:
    """The 74 tools, sorted into the redesign's category order."""
    order = {c: i for i, c in enumerate(CATEGORY_TABS)}
    items = _dedupe(_quick_launch_items() + group_tweaks("tools"))
    return sorted(
        items,
        key=lambda t: order.get(_CAT_BY_ID.get(t["id"], "System"), 99))


def _row(t: dict) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "desc": t.get("desc", ""),
        "cat": _CAT_BY_ID.get(t["id"], "System"),
        "admin": bool(t.get("admin")),
    }


class ToolRunner(QThread):
    """Runs a tool/launcher in the background so a UAC prompt or console
    wait never freezes the UI thread. Emits (ok, kind) when done."""

    finished_ok = Signal(bool, str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.key = item["id"]

    def run(self):
        item = self.item
        try:
            if item.get("launch_key"):
                ok, kind = launch_tool(item["launch_key"]), "run"
            else:
                ok, kind = run_tweak(item)
        except Exception:
            ok, kind = False, "run"
        self.finished_ok.emit(ok, kind)


class _ToolsBridge(QObject):
    """Registered as ``window.pywebview.api`` on the page's QWebChannel."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot(str)
    def run(self, tool_id):
        self._page.run_tool(tool_id)

    @Slot()
    def scanHardware(self):
        self._page.open_detect()

    @Slot()
    def logs(self):
        self._page.open_logs()


class ToolsPage(QWidget):
    """Embedded-webview port of the Tools redesign."""

    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._items: dict[str, dict] = {}
        self._workers: list[ToolRunner] = []

        self._web = make_webview(self)
        self._web.setStyleSheet("background:#0b0912; border:none;")
        self._web.page().setBackgroundColor(QColor("#0b0912"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(
            settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _ToolsBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            self._web.load(QUrl.fromLocalFile(str(html)))
        else:
            self._web.setHtml(
                "<body style='background:#0b0912;color:#8b84a6;"
                "font-family:sans-serif;padding:40px;'>"
                f"tools.html not found at<br><code>{html}</code>"
                "</body>")
        self._web.loadFinished.connect(self._on_load_finished)

    # ------------------------------------------------------- JS transport
    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    def _on_load_finished(self, _ok):
        self.push()

    # ------------------------------------------------------- data payload
    def _payload(self) -> dict:
        items = _tool_rows()
        self._items = {t["id"]: t for t in items}
        quick = []
        for tid, label in _QUICK_TILE:
            t = self._items.get(tid)
            if t is not None:
                quick.append({**_row(t), "label": label})
        return {"tools": [_row(t) for t in items], "quick": quick}

    def push(self):
        try:
            payload = self._payload()
        except Exception as exc:  # noqa: BLE001 - surfaced via the log
            from maxlog import logger
            logger.warn(f"tools: payload failed: {exc}")
            return
        self._js("window.mxSetTools && window.mxSetTools({})".format(
            json.dumps(payload, ensure_ascii=False)))

    # ------------------------------------------------------- navigation
    def open_detect(self):
        if self.navigate:
            self.navigate("detect")

    def open_logs(self):
        if self.navigate:
            self.navigate("logs")

    # ------------------------------------------------------- run
    def run_tool(self, tool_id: str):
        item = self._items.get(tool_id)
        if item is None:
            return
        worker = ToolRunner(item)
        worker.finished_ok.connect(self._finish_slot)
        worker.finished.connect(self._on_worker_finished)
        self._workers.append(worker)
        worker.start()

    def _finish_slot(self, ok, kind):
        worker = self.sender()
        if worker is None:
            return
        self._finish(worker.key, ok, worker.item, kind)

    def _on_worker_finished(self):
        self._workers = [w for w in self._workers if not w.isFinished()]

    def _finish(self, key, ok, item, kind="run"):
        name = item["name"]
        if not ok:
            msg = f"Failed to launch {name}."
            if item.get("admin"):
                msg += " It needs administrator permission."
            toast(msg, "error", self)
            return
        if kind == "guidance":
            self._show_guidance(item)

    def _show_guidance(self, tweak: dict):
        text = ""
        for action in tweak.get("actions", []):
            if (isinstance(action, (tuple, list)) and action
                    and action[0] == "guidance"):
                text = action[1] if len(action) > 1 else ""
                break
        if not text:
            text = tweak.get("desc", "")
        box = QMessageBox(self)
        box.setWindowTitle(tweak["name"])
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(text)
        desc = tweak.get("desc", "")
        if desc and desc != text:
            box.setInformativeText(desc)
        why = tweak.get("why")
        if why:
            box.setDetailedText(f"Why it matters:\n{why}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
