"""Maximum Tweaks Engine Dashboard — Dashboard mockup v2 (live HTML page).

The dashboard now renders ``ui/dashboard.html`` — an exact clone of the
Dashboard mockup v2 (dark theme + teal/accent palette, 3-card hero row with a
live "Next best tweak" spotlight, telemetry rings with sparklines and trend
badges, thermal & clock chart with GPU/CPU toggle, system storage, Ultra Mode,
recent activity) — inside an embedded QtWebEngine view with a QWebChannel
bridge under ``window.pywebview.api`` (same pattern as tweak_cards.html).

Everything on screen is real data, refreshed live:

  * hero chips + welcome name come from the detected profile,
  * the spotlight pick is a *recommended* tweak that is not yet applied on
    this system (same source as the tweak cards), rotated per launch within
    the highest-impact compatible candidates so it isn't the same one every
    restart, and re-picked once it is applied,
  * session uptime counts from the last full scan event,
  * Tweaks applied X / Y is applied / compatible count,
  * the three ring gauges, sparklines, trend badges, thermal/clock chart and
    the storage bar stream from ``engine.telemetry`` every second,
  * the spotlight Apply button runs the REAL snapshot -> apply -> verify
    pipeline (``BatchWorker`` -> ``engine.applier.run``),
  * "Clean system cache" runs the real temp-file cleanup (``CleanupThread``),
  * Recent activity mirrors ``engine.activity``.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import psutil
from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js
from PySide6.QtWidgets import QVBoxLayout, QWidget

from config.app_config import ROOT, current_windows_user
from database import BY_ID, TWEAKS
from engine import activity as activity_bus
from engine import license as license_mgr, state as state_mgr
from engine import activity
from engine import waitlist as waitlist_mgr
from engine.telemetry import TelemetrySampler, invalidate_disk_cache
from ui.pages._web import make_webview
from ui.categories import (
    CATEGORY_LABELS,
    affects_for,
    compatible_tweaks,
    group_key_for_category,
    logo_data_uri,
)
from ui.monitor_widgets import CleanupThread
from ui.widgets import BatchWorker, toast

HTML_REL = "ui/dashboard.html"

REC_FLAG = "recommended"

# Impact tiers, highest first (mirrors the tweak cards / native list).
IMPACT_RANK = {
    "extreme": 6,
    "high": 5,
    "moderate": 4,
    "low": 3,
    "very low": 2,
    "verylow": 2,
}

# Recent-activity row cosmetics: kind -> dot color.
ACTIVITY_COLORS = {
    "success": "#2fe3ba",
    "info": "#2fe3ba",
    "apply": "#2fe3ba",
    "scan": "#e7b256",
    "profile": "#9c86f5",
    "warning": "#e7b256",
    "error": "#ea6a86",
    "restart": "#e7b256",
}

# Fallback category labels when an activity row isn't about a specific tweak.
ACTIVITY_CAT = {
    "scan": "SYSTEM",
    "restart": "SYSTEM",
    "profile": "PROFILE",
    "error": "ERROR",
    "warning": "WARNING",
}


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


def _norm_impact(value) -> str:
    impact = (value or "low").strip().lower().replace(" ", "")
    if impact in ("verylow", "very low"):
        return "verylow"
    if impact in ("low", "moderate", "high", "extreme"):
        return impact
    return "low"


def _relative_time(item: dict, now: float) -> str:
    """Activity item -> relative label like '2m ago'.

    Prefers the epoch ``ts`` recorded by the activity bus (exact across day
    boundaries); falls back to the legacy same-day 'HH:MM:SS' clock time.
    """
    ts = item.get("ts")
    if isinstance(ts, (int, float)):
        diff = max(0, int(now - ts))
    else:
        try:
            h, m, s = (int(x)
                       for x in str(item.get("time") or "").split(":")[:3])
            event = h * 3600 + m * 60 + s
            today = now % 86400
            diff = max(0, int(today - event))
        except Exception:  # noqa: BLE001
            return str(item.get("time") or "")
    if diff < 5:
        return "just now"
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    return f"{diff // 86400}d ago"


class _JoinWorker(QThread):
    """Wraps the waitlist registration off the UI thread.

    Because engine.waitlist only does a validated local store write + one
    best-effort HTTPS POST (no secrets, no credentials), a single worker
    holds the whole flow together and pushes one result dict back."""
    done = Signal(dict)

    def __init__(self, email, parent=None):
        super().__init__(parent)
        self._email = email

    def run(self):
        try:
            result = waitlist_mgr.join(self._email)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "status": "error",
                      "message": f"Could not join the waitlist — {exc}"}
        self.done.emit(result)


class _DashboardBridge(QObject):
    """Registered as ``window.pywebview.api`` for the dashboard page."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot(str)
    def apply(self, tid):
        self._page.request_apply(tid)

    @Slot()
    def clean(self):
        self._page.request_clean()

    @Slot(str)
    def joinEmail(self, email):
        self._page.request_join_email(email)

    @Slot(str)
    def navigate(self, key):
        self._page.navigate(key)


class DashboardPage(QWidget):
    """Dashboard mockup v2 rendered from ``ui/dashboard.html`` + live data."""

    def __init__(self, ctx, navigate, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.navigate = navigate
        self._ready = False
        self._busy = False
        self._spotlight = None
        self._worker = None
        self._join_worker: _JoinWorker | None = None
        self._join_busy = False
        self._clean_thread: CleanupThread | None = None
        self._scan_at = time.time()
        self._last_metrics: dict = {}
        self._boot_at = psutil.boot_time()

        self._web = make_webview(self)
        self._web.setStyleSheet("background:#07060d; border:none;")
        self._web.page().setBackgroundColor(QColor("#07060d"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._web)

        settings = self._web.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(settings.WebAttribute.JavascriptCanOpenWindows, False)

        self._bridge = _DashboardBridge(self, self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("api", self._bridge)
        self._web.page().setWebChannel(self._channel)

        html = _html_path()
        if html.is_file():
            self._web.load(QUrl.fromLocalFile(str(html)))
        else:
            self._web.setHtml(
                "<body style='background:#07060d;color:#9a93b8;"
                "font-family:sans-serif;padding:40px;'>"
                f"dashboard.html not found at<br><code>{html}</code>"
                "</body>")
        self._web.loadFinished.connect(self._on_load_finished)

        self.ctx.profile_changed.connect(self._refresh)
        self.ctx.state_changed.connect(self._refresh)
        self.ctx.license_changed.connect(self._refresh)
        sig = activity_bus.bus.qt_signal()
        if sig is not None:
            sig.connect(self._on_activity_event)

        self._last_flush = time.monotonic()

        self.sampler = TelemetrySampler(self)
        self.sampler.metrics.connect(self._on_metrics)
        self.sampler.start()

    # ------------------------------------------------------- JS transport
    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    def _on_load_finished(self, ok):
        self._ready = True
        self._push()
        self._push_activity()

    # ------------------------------------------------------- telemetry
    def _on_metrics(self, data: dict):
        self._last_metrics = data
        if self._ready:
            payload = dict(data)
            payload["cpu_threads"] = data.get("cpu_threads") or 0
            self._js(
                f"window.mx && window.mx.pushMetrics({json.dumps(payload)})")

    # ------------------------------------------------------- activity feed
    def _on_activity_event(self, item):
        if isinstance(item, dict) and item.get("kind") == "scan":
            self._scan_at = time.time()
        if self._ready:
            self._push_activity()
            self._push()

    def _activity_rows(self, n: int = 5) -> list[dict]:
        now = time.time()
        rows = []
        for item in activity_bus.history(n):
            kind = item.get("kind", "info")
            text = str(item.get("text") or "").strip()
            tid = self._tid_for_text(text)
            cat = ""
            if tid is not None:
                tweak = BY_ID.get(tid)
                if tweak:
                    group = group_key_for_category(tweak.get("category") or "")
                    cat = CATEGORY_LABELS.get(group, tweak.get("category") or "")
            if not cat:
                cat = ACTIVITY_CAT.get(kind, kind.upper())
            rows.append({
                "color": ACTIVITY_COLORS.get(kind, "#544d72"),
                "name": text,
                "cat": cat,
                "time": _relative_time(item, now),
            })
        return rows

    @staticmethod
    def _tid_for_text(text: str) -> str | None:
        """Best-effort: which tweak produced this activity line?"""
        low = text.lower()
        for tid, tweak in BY_ID.items():
            name = str(tweak.get("name") or "")
            if name and name.lower() in low:
                return tid
        return None

    def _push_activity(self):
        self._js(f"window.mx && window.mx.setActivity({json.dumps(self._activity_rows())})")

    # ------------------------------------------------------- hero / payload
    def _compatible_tweaks(self) -> list[dict]:
        # "Compatible" mirrors how the rest of the UI decides what belongs on
        # THIS machine: not guidance, not evaluator-incompatible, and not a
        # form-factor mismatch (the whole Laptop category is laptop-only
        # hardware/OS behaviour, even though those DB rows carry no gates).
        # Shared with the startup scan count so the hero total and the
        # recent-activity scan message always agree.
        return compatible_tweaks(TWEAKS, self.ctx.eval, self.ctx.profile)

    def _next_best(self):
        # Wait for detection: without a profile every tweak looks "ready" and
        # the spotlight could recommend something for the wrong machine.
        if not self.ctx.profile:
            return {}
        # PC-aware candidates: recommended, compatible here, not already active.
        cands = [t for t in self._compatible_tweaks()
                 if t.get("recommended") == REC_FLAG
                 and not self.ctx.live_active(t["id"])]
        if not cands:
            self._spotlight = None
            return {}
        # Reuse the session's pick while it is still valid, so the card keeps
        # a stable target until that tweak gets applied (then it rotates).
        if self._spotlight is None or self._spotlight.get("tid") not in {
                c["id"] for c in cands}:
            self._spotlight = self._pick_spotlight(cands)
        if self._spotlight is None:
            return {}
        best = self._spotlight
        affects = affects_for(best)
        return {
            "tid": best["id"],
            "name": best.get("name", best["id"]),
            "impact": _norm_impact(best.get("impact")),
            "affects": affects[0] if affects else "",
        }

    def _pick_spotlight(self, cands):
        # Vary the "next best" card across launches: draw from the highest
        # impact candidates instead of always the same argmax tweak, while
        # skipping the tweak shown last session so restarts surface something
        # new. Still PC-aware — candidates are already per-machine.
        ranked = sorted(cands, key=lambda t: -IMPACT_RANK.get(
            (t.get("impact") or "low").strip().lower(), 0))
        pool = ranked[:max(1, min(8, len(ranked)))]
        last = state_mgr.get_meta("spotlight_last")
        if last and len(pool) > 1:
            rest = [t for t in pool if t["id"] != last]
            if rest:
                pool = rest
        pick = random.choice(pool)
        try:
            state_mgr.set_meta("spotlight_last", pick["id"])
        except Exception:  # noqa: BLE001 — persistence is best-effort
            pass
        return pick

    def _payload(self) -> dict:
        profile = self.ctx.profile or {}
        compatible = self._compatible_tweaks()
        # Applied = tweaks this app has actually applied and recorded, the
        # exact same source the AI assistant's stat uses (ui/pages/chat.py).
        applied_ids = state_mgr.applied_ids()
        applied = len(applied_ids)
        remaining = sum(
            1 for t in compatible
            if t.get("recommended") == REC_FLAG
            and t["id"] not in applied_ids)

        sess = license_mgr.session()
        licensed = bool(sess and license_mgr.is_authorized())
        telemetry = "Telemetry live" if self.sampler.isRunning() else "Telemetry offline"

        chips = []
        if profile:
            chips.append(
                f"Windows {profile.get('win_version', '?')} · build {profile.get('win_build', 0)}")
            chips.append("Laptop" if profile.get("laptop") else "Desktop")
            cpu = (profile.get("cpu_name") or "").strip()
            if cpu:
                chips.append(cpu[:34])
            for name in profile.get("gpu_names", []) or []:
                chips.append(str(name).strip())
        if not chips:
            chips.append("Scanning system…")

        return {
            "welcome": f"Welcome back, {current_windows_user()}",
            "license": "License active" if licensed else "Awaiting activation",
            "telemetry": telemetry,
            "chips": chips,
            "next": self._next_best(),
            "nextReady": bool(profile),
            "uptimeSec": max(0, int(time.time() - self._boot_at)),
            "applied": applied,
            "total": len(compatible),
            "remaining": remaining,
            "cpuLogo": logo_data_uri("cpu"),
            "gpuLogo": logo_data_uri("gpu"),
            "ramLogo": logo_data_uri("ram"),
        }

    def _push(self):
        if self._ready:
            self._js(f"window.mx && window.mx.setData({json.dumps(self._payload())})")

    def _refresh(self):
        if self._ready:
            self._push_activity()
            self._push()

    # ------------------------------------------------------- actions
    def request_apply(self, tid):
        if self._busy:
            toast("A batch is already running — wait a moment.", "warning", self)
            return
        if not BY_ID.get(tid):
            toast(f"Unknown tweak {tid}", "error", self)
            return
        self._busy = True
        from engine.safety import preflight as _preflight
        pf = _preflight(BY_ID[tid], profile=self.ctx.profile)
        if not pf["allowed"]:
            self._busy = False
            toast(f"{BY_ID[tid]['name']} blocked — {pf['reason']}", "warning", self)
            self.ctx.invalidate_state()
            self.ctx.note_state_change()
            self._push()
            return
        if BY_ID[tid].get("confirm"):
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox()
            box.setWindowTitle("Apply tweak")
            box.setText(f"Apply \u201c{BY_ID[tid]['name']}\u201d?\n\n"
                        "This changes Windows registry, services or power "
                        "settings. Everything can be reverted.")
            box.setIcon(QMessageBox.Icon.Warning)
            yes = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                self._busy = False
                return
        toast(f"Applying {BY_ID[tid]['name']}…", "info", self)
        if self._worker and self._worker.isRunning():
            if hasattr(self._worker, "cancel"):
                self._worker.cancel()
            self._worker.wait(5000)
        self._worker = BatchWorker([tid], "apply", self, profile=self.ctx.profile)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.batch_error.connect(self._on_batch_error)
        self._worker.start()

    def _on_batch_done(self, result):
        self._busy = False
        results = result.get("results", {})
        ok_ids = [tid for tid, r in results.items()
                  if r.get("ok") and r.get("status") != "dry_run"]
        failed = len(results) - len(ok_ids)
        tid = next(iter(results), "")
        name = BY_ID.get(tid, {}).get("name", tid)
        if failed:
            toast(f"Couldn't apply {name} — {failed} failed or blocked.", "warning", self)
        else:
            toast(f"Applied {name}.", "success", self)
        self._post_batch(ok_ids)

    def _on_batch_error(self, msg):
        self._busy = False
        toast(f"Apply error — {msg}", "error", self)
        self.ctx.invalidate_state()
        self.ctx.note_state_change()
        self._push()

    def _post_batch(self, ids):
        with state_mgr.state_batch():
            for tid in self._worker.ids if self._worker else []:
                ok = tid in ids
                if not ok:
                    self.ctx.live.pop(tid, None)
                    continue
                state_mgr.mark_applied(tid)
                state_mgr.unmark_disabled(tid)
                self.ctx.live[tid] = True
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(ids)
        self.ctx.note_state_change()
        self._push()

    def request_clean(self):
        if self._clean_thread is not None and self._clean_thread.isRunning():
            return
        self._clean_thread = CleanupThread(self)
        self._clean_thread.done.connect(self._on_clean_done)
        self._clean_thread.start()
        toast("Cleaning system cache…", "info", self)

    def _on_clean_done(self, result: dict):
        from PySide6.QtWidgets import QPushButton
        files = result.get("files", 0)
        errors = result.get("errors", 0)
        if files:
            freed_mb = result.get("freed_bytes", 0) / 2**20
            toast(f"Cleaned {files} files · {result.get('folders', 0)} folders"
                  f" · freed {freed_mb:.0f} MB",
                  "warning" if errors else "success", self)
        else:
            toast("Temporary files are already clean.", "success", self)
        invalidate_disk_cache()
        self._web.page().runJavaScript(
            "var b=document.getElementById('clean-btn');"
            "if(b) b.disabled=false;")

    def request_join_email(self, email):
        if self._join_busy:
            return
        if self._busy:
            self._js("window.mx && window.mx.joinResult("
                     + json.dumps({"ok": False, "status": "error",
                                   "message": "A batch is already running — "
                                              "wait a moment and try again."})
                     + ")")
            return
        self._join_busy = True
        if self._join_worker is not None and self._join_worker.isRunning():
            self._join_worker.wait(5000)
        self._join_worker = _JoinWorker(email, self)
        self._join_worker.done.connect(self._on_join_done)
        self._join_worker.start()

    def _on_join_done(self, result):
        self._join_busy = False
        self._js(
            f"window.mx && window.mx.joinResult({json.dumps(result)})")

    def set_busy(self, busy: bool):
        self._busy = busy