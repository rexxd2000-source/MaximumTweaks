"""Tweak cards page — the redesign.

The page renders ``ui/tweak_cards.html`` — an exact clone of the FPS Boost
mockup (same design tokens, card grid, conic gauge, tilt effect) — inside an
embedded QtWebEngine view, and exposes a QWebChannel bridge under
``window.pywebview.api`` with the same call style as the debloat page.

Only three things are driven by real data per category:

  * hero title + blurb (per ``tweak:`` sidebar key, from CATEGORY_GROUPS),
  * the conic gauge ("N of M rec." = applied-recommended / recommended),
  * the card list (real DB tweaks for the group).

Interactions are real, not cosmetic:

  * APPLY / APPLIED toggles run the real snapshot -> apply -> verify/revert
    pipeline through ``BatchWorker`` -> ``engine.applier.run``.
  * Apply all applies every visible recommended tweak that isn't already
    active and passes the safety preflight.
  * Live audit results stream back into the cards via ``setActive``.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget
from PySide6.QtWebChannel import QWebChannel  # noqa: F401 - registers qtwebchannel.js

from config.app_config import APP_VERSION, DISCORD_INVITE_URL, ROOT
from config.plans import PLAN_LABEL, allows, normalize_tier
from database import BY_ID
from database.tweaks._base import is_new_tweak, is_updated_tweak
from engine import state as state_mgr
from engine.entitlements import current_tier
from engine.license import session as license_session
from maxlog import logger
from ui.pages._web import make_webview
from ui.categories import (
    ALL_TWEAK_KEYS,
    CATEGORY_GROUPS,
    CPU_FAMILIES,
    CPU_FAMILY_KEYS,
    cpu_filter_tweaks,
    gpu_filter_tweaks,
    group_tweaks,
    logo_data_uri,
)
from ui.pages.tweaks import HEADER_TITLES
from ui.widgets import BatchWorker, toast

HTML_REL = "ui/tweak_cards.html"

IMPACT_KEYS = {"verylow", "low", "moderate", "high", "extreme"}


def _html_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else ROOT
    return base / HTML_REL


def _norm_impact(value) -> str:
    impact = (value or "low").strip().lower().replace(" ", "")
    return impact if impact in IMPACT_KEYS else "low"


# ---------------------------------------------------------------- bridge

class _TweakCardsBridge(QObject):
    """Registered as ``window.pywebview.api`` on the page's QWebChannel."""

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page

    @Slot(str)
    def apply(self, tid):
        self._page.request_apply(tid)

    @Slot(str)
    def revert(self, tid):
        self._page.request_apply(tid, mode="revert")

    @Slot()
    def applyAll(self):
        self._page.request_apply_all()

    @Slot()
    def revertAll(self):
        self._page.request_revert_all()

    @Slot(str)
    def selectVendor(self, vendor):
        self._page.select_gpu_vendor(vendor)

    @Slot(str)
    def selectCpuFamily(self, family):
        self._page.select_cpu_family(family)

    @Slot()
    def retry(self):
        self._page.retry_load()

    @Slot(str)
    def openUpgrade(self, tier):
        """A locked card's "Unlock with <Tier>" button: go to the pricing page.

        The label is echoed in the toast so the button names the plan it is
        actually asking about, rather than a generic "upgrade".
        """
        self._page.open_upgrade(tier)


# ---------------------------------------------------------------- page

class TweakCardsPage(QWidget):
    """Per-category tweak cards rendered from the exact mockup design."""

    def __init__(self, ctx, navigate=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.key = "cpu"
        # Set by main_window. Kept optional so the page still constructs for
        # tests and for any caller that doesn't wire navigation - the button
        # then says what it would have done instead of silently doing nothing.
        self._navigate = navigate
        self._ready = False
        self._busy = False
        self._worker = None
        self._in_flight: set[str] = set()
        self._batch_ids: list[str] = []
        self._batch_mode = "apply"
        # UI-facing label for the running batch. It equals _batch_mode except for
        # "revert_all", which is a revert batch that reports differently. The
        # engine only ever sees _batch_mode ("apply" / "revert").
        self._batch_kind = "apply"
        self._last_results: dict = {}
        self._gpu_selected_vendor: str = state_mgr.get_gpu_selection() or ""
        self._gpu_picker_open = False
        # CPU is the same pattern: the category picker owns the first entry,
        # and with no category chosen there are no cards to show.
        self._cpu_selected_family: str = state_mgr.get_cpu_selection() or ""
        self._cpu_picker_open = False
        # Monotonic id of the current category-load run. Every push and every
        # audit completion is stamped with it, so a category switch mid-load
        # can never be overwritten by the run it replaced.
        self._load_run = 0
        # Host-side backstop for a renderer that stops running its timers.
        # Generous: it only matters when the page is already stuck.
        self.LOAD_WATCHDOG_MS = 4000
        self._load_watchdog: QTimer | None = None

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

        self._bridge = _TweakCardsBridge(self, self)
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
                f"tweak_cards.html not found at<br><code>{html}</code>"
                "</body>")
        self._web.loadFinished.connect(self._on_load_finished)

        self.ctx.state_changed.connect(self._refresh)
        self.ctx.live_state_changed.connect(self._on_live_state)
        self.ctx.auditor.batch_done.connect(self._on_audit_batch_done)

    # ------------------------------------------------------- JS transport
    def _js(self, script: str):
        self._web.page().runJavaScript(script)

    def _on_load_finished(self, ok):
        self._ready = True
        # Opening the page is itself a category open, so the first render
        # gets the same sequence as every later entry.
        source = self._load_source()
        if source is not None:
            self._begin_load(source, audit=bool(self.ctx.auditing))
            self._push(source)

    # ------------------------------------------------- category load run
    def _load_source(self) -> list[dict] | None:
        """The real, filtered tweak list for the current category.

        Read once and reused for both the placeholder count and the payload,
        so the number in "1 of N" can never disagree with the cards that
        actually land. Returns None if the read fails.
        """
        try:
            return self._source_tweaks()
        except Exception as exc:  # noqa: BLE001 - surfaced in the page
            # Same run id, not a new one: the page is told the run it is
            # already on failed, and opening a fresh run here would leave the
            # pill of the failed one behind.
            self._load_error(self._load_run, f"{exc}")
            return None

    def _begin_load(self, source: list[dict], audit: bool):
        """Open a loading run for the category now on screen.

        ``gated`` is passed rather than re-derived in the page because the
        page only learns the key/vendor from the payload that arrives *after*
        this call - deriving it there would test the previous category.
        """
        self._load_run += 1
        run = self._load_run
        title, _ = self._header()
        gated = ((self.key == "gpu" and not self._gpu_selected_vendor)
                 or (self.key == "cpu" and not self._cpu_selected_family))
        self._js("window.mxBeginLoad({}, {}, {}, {})".format(
            run, len(source), json.dumps(title),
            "true" if gated else "false"))
        if not audit:
            # No applied-state check is running, so there is nothing real to
            # wait for. Say so instead of making the page time out.
            self._js(f"window.mxAuditDone({run})")
        self._arm_watchdog(run)

    def _arm_watchdog(self, run: int):
        """Backstop against a renderer too busy to run its own timers.

        The page paces the reveal with setTimeout, and a renderer that is
        saturated will not run them - measured: a bare 450ms setTimeout did
        not fire at all while a 158-card category was still settling and the
        next one was picked, leaving the page on "Loading database..." with
        every card covered. This timer lives in Qt, so it still fires, and it
        only does anything while the page still believes the run is open.
        """
        self._stop_watchdog()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda r=run: self._force_ready(r))
        self._load_watchdog = timer
        timer.start(self.LOAD_WATCHDOG_MS)

    def _stop_watchdog(self):
        timer = getattr(self, "_load_watchdog", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
            self._load_watchdog = None

    def _force_ready(self, run: int):
        """Hand the cards over from the host side. Results keep streaming
        into setActive() afterwards, so the page still ends up truthful."""
        self._stop_watchdog()
        if run != self._load_run:
            return
        self._js(f"window.mxForceReady({run})")

    def _load_error(self, run: int, msg: str):
        self._stop_watchdog()
        self._js("window.mxLoadError({}, {})".format(run, json.dumps(msg)))

    def _on_audit_batch_done(self):
        """The real applied-state batch finished. Release the page's
        "Checking what's applied..." phase so APPLIED reflects a real
        result rather than a fixed delay."""
        if self._ready:
            self._js(f"window.mxAuditDone({self._load_run})")

    def retry_load(self):
        """Retry button in the error pill: re-run the real path (DB read,
        payload, applied-state audit) rather than replaying the animation.
        """
        if not self._ready:
            return
        source = self._load_source()
        if source is None:
            return
        self.ctx.request_audit(source)
        self._begin_load(source, audit=True)
        self._push(source)

    # ------------------------------------------------------- navigation
    def select(self, key):
        if key not in ALL_TWEAK_KEYS:
            key = "cpu"
        changed = key != self.key
        self.key = key
        # The vendor picker is owned by the app: every entry into the GPU
        # category (including re-clicking the row) marks the upcoming push so
        # the page raises the overlay. It stays up across the follow-up
        # audit/refresh pushes and only closes when the user picks a vendor
        # or leaves the category. The flag is cleared right after the entry
        # push so nothing later re-raises it.
        self._gpu_picker_open = (key == "gpu")
        # Same contract for the CPU category picker: every entry into the CPU
        # category marks the upcoming push so the page raises the picker, and
        # the flag is cleared right after so later pushes cannot re-raise it.
        self._cpu_picker_open = (key == "cpu")
        if key == "cpu":
            # Re-read on entry: the remembered category may have been changed
            # elsewhere (or the page may predate the stored value), and the
            # picker must reflect what is actually persisted.
            stored = state_mgr.get_cpu_selection() or ""
            if stored in CPU_FAMILY_KEYS:
                self._cpu_selected_family = stored
        if (changed or key in ("gpu", "cpu")) and self._ready:
            self._js("window.mx && window.mx.reset()")
        source = None
        if changed and self._ready:
            # Deliberately after the CPU re-read above, so the audit covers
            # the category about to be rendered and not the previous pick.
            source = self._load_source()
            if source is not None:
                self.ctx.request_audit(source)
                self._begin_load(source, audit=True)
        self._push(source)
        self._gpu_picker_open = False
        self._cpu_picker_open = False

    def select_gpu_vendor(self, vendor):
        """Vendor chosen in the GPU selector popup: persist it and push the
        filtered payload back to the page (the page replays its reveal)."""
        if self.key != "gpu" or vendor not in ("nvidia", "amd", "integrated"):
            return
        self._gpu_picker_open = False
        self._gpu_selected_vendor = vendor
        state_mgr.set_gpu_selection(vendor)
        source = self._load_source()
        if source is not None:
            self.ctx.request_audit(source)
            self._begin_load(source, audit=True)
            self._push(source)

    def select_cpu_family(self, family):
        """CPU category chosen in the picker: persist it and push the cards
        that belong to it.

        The value is validated against the real category list, so a stale or
        hand-crafted payload cannot put the page into an unknown state.
        """
        if self.key != "cpu":
            return
        if family not in CPU_FAMILY_KEYS:
            return
        self._cpu_picker_open = False
        self._cpu_selected_family = family
        state_mgr.set_cpu_selection(family)
        source = self._load_source()
        if source is not None:
            self.ctx.request_audit(source)
            self._begin_load(source, audit=True)
            self._push(source)

    def _refresh(self):
        if self._ready:
            self._push()

    # ------------------------------------------------------- data payload
    def _source_tweaks(self) -> list[dict]:
        key = self.key
        if key == "gpu":
            # GPU cards are gated by the vendor selector: with no vendor there
            # is nothing to show, with a vendor the real DB filter applies.
            if self._gpu_selected_vendor:
                out = gpu_filter_tweaks("gpu", self._gpu_selected_vendor)
            else:
                out = []
        elif key == "cpu":
            # CPU cards are gated by the category picker, exactly like the GPU
            # vendor gate: with no category chosen there is nothing to show, so
            # the page can never present a flat list before a pick.
            if self._cpu_selected_family:
                profile = self.ctx.profile or {}
                out = cpu_filter_tweaks(
                    "cpu",
                    cpu_vendor=profile.get("cpu_vendor"),
                    is_laptop=profile.get("laptop"),
                    cpu_family=self._cpu_selected_family)
            else:
                out = []
        else:
            out = group_tweaks(key)
        # Guidance-only tweaks are informational (never applicable) and have
        # their own badge in the native list; the cards page hides them.
        return [t for t in out if not t.get("guidance")]

    def _header(self) -> tuple[str, str]:
        # In the CPU category view the header names the chosen category, so the
        # active selection stays visible above its own cards.
        if self.key == "cpu" and self._cpu_selected_family:
            fams = {f["key"]: f for f in CPU_FAMILIES}
            fam = fams.get(self._cpu_selected_family)
            if fam:
                return (f"{fam['label']} CPU",
                        f"Only the tweaks that apply to {fam['label']} are "
                        "listed here. This is your manual selection, not "
                        "hardware-verified - change it at any time.")
        meta = CATEGORY_GROUPS.get(self.key)
        if meta:
            return (HEADER_TITLES.get(self.key, meta["title"]), meta["blurb"])
        return ("Tweaks", "")

    def _payload(self, source: list[dict] | None = None) -> dict:
        title, blurb = self._header()
        rec_total = 0
        applied_rec = 0
        applied_total = 0
        items = []
        if source is None:
            source = self._source_tweaks()
        held = current_tier()
        for t in source:
            rec = t.get("recommended") == "recommended"
            active = bool(self.ctx.live_active(t["id"]))
            if active:
                applied_total += 1
            if rec:
                rec_total += 1
                if active:
                    applied_rec += 1
            # The tier decision is made HERE, once, by the same code that
            # enforces it at apply time (engine.entitlements). The page only
            # renders what it is told, so a card can never look unlocked and
            # then be refused by the applier.
            required = normalize_tier(t.get("tier"))
            items.append({
                "id": t["id"],
                "name": t["name"],
                "desc": t.get("desc", ""),
                "impact": _norm_impact(t.get("impact")),
                "rec": rec,
                "active": active,
                "updated": is_updated_tweak(t),
                "new": is_new_tweak(t),
                "tier": required,
                "locked": not allows(held, required),
            })
        return {
            "key": self.key,
            "heldTier": held,
            "tierLabels": {t: PLAN_LABEL[t] for t in ("performance", "maximum")},
            "gpuVendor": self._gpu_selected_vendor if self.key == "gpu" else "",
            "gpuPicker": self._gpu_picker_open,
            "cpuFamily": self._cpu_selected_family if self.key == "cpu" else "",
            "cpuPicker": self._cpu_picker_open,
            "title": title,
            "blurb": blurb,
            "logo": logo_data_uri(self.key),
            "recTotal": rec_total,
            "appliedRec": applied_rec,
            # Drives the Revert-all confirm dialog's count, so it is sent for
            # the whole category rather than derived from the rendered cards.
            "appliedCount": applied_total,
            "tweaks": items,
        }

    def _push(self, source: list[dict] | None = None):
        try:
            payload = self._payload(source)
        except Exception as exc:  # noqa: BLE001 - surfaced in the page
            logger.warn(f"tweak cards: payload for {self.key} failed: {exc}")
            self._load_error(self._load_run, f"{exc}")
            return
        self._js(f"window.mx && window.mx.setData({json.dumps(payload)})")

    # ------------------------------------------------------- live state
    def _on_live_state(self, tid, value):
        # A fresh audit result streams in. Apply batches re-push the whole
        # payload when they finish, so only forward independent results here.
        if value is None or tid in self._in_flight:
            return
        self._js(f"window.mx && window.mx.setActive({json.dumps(tid)}, {json.dumps(bool(value))})")

    # ------------------------------------------------------- actions
    def open_upgrade(self, tier):
        """Send the user to Discord from a locked card.

        Purchase is handled by hand on Discord for now; the website checkout
        replaces this later. The invite opens the server and the prefilled
        ticket text is copied to the clipboard so all they have to do is paste
        it into a new ticket.
        """
        label = PLAN_LABEL.get(tier) or "a higher plan"
        ticket = self._upgrade_ticket(tier, label)
        QApplication.clipboard().setText(ticket)
        if DISCORD_INVITE_URL:
            QDesktopServices.openUrl(QUrl(DISCORD_INVITE_URL))
        toast(f"Opening Discord to unlock {label}.",
              "info", self, "Your ticket message is copied - just paste it in.")

    def _upgrade_ticket(self, tier: str, label: str) -> str:
        """Prefilled Discord ticket: who they are and what they want.

        Carries the identifiers support needs to act without a back-and-forth
        (licence key, current tier, wanted tier, app version).
        """
        sess = license_session() or {}
        key = sess.get("license") or "not signed in"
        device = sess.get("device_id") or "unknown device"
        lines = [
            "Upgrade request",
            "",
            f"Plan wanted: {label}",
            f"Current plan: {PLAN_LABEL[current_tier()]}",
            f"Licence key: {key}",
            f"Device ID: {device}",
            f"App version: {APP_VERSION}",
            "",
            "I've been told this tweak needs a higher plan. Please help me upgrade.",
        ]
        return "\n".join(lines)

    def request_apply(self, tid, mode="apply"):
        if self._busy:
            toast("A batch is already running \u2014 wait a moment.", "warning", self)
            return
        self._run_batch([tid], mode)

    def request_apply_all(self):
        if self._busy:
            return
        from engine.safety import preflight as _preflight
        profile = self.ctx.profile or None
        ids, skipped, unverified = [], [], []
        for t in self._source_tweaks():
            if t.get("guidance"):
                continue
            if t.get("recommended") != "recommended":
                continue
            if self.ctx.live_active(t["id"]):
                continue
            pf = _preflight(t, profile=profile)
            if not pf["allowed"]:
                skipped.append((t["id"], pf["reason"]))
            elif pf.get("requires_confirmation"):
                # Unverified tweaks are allowed one at a time, after the user
                # reads the reason, but they are never applied unattended. Keeping
                # them out of this list is what stops Apply All from quietly
                # becoming a force-apply path.
                unverified.append((t["id"], pf["reason"]))
            else:
                ids.append(t["id"])
        if not ids:
            msg = ("every visible recommended tweak is already active "
                   "on your system.")
            if skipped:
                msg = "every visible tweak is already active or blocked " \
                      "(see the first blocked reason in the log)."
            toast(f"Nothing to apply \u2014 {msg}", "info", self)
            return
        block_note = ""
        if skipped:
            block_note = (f"\n\nSkipping {len(skipped)} tweak(s) that are blocked "
                          f"(validation status, wrong Windows version, undetected "
                          f"hardware, tier not included in your plan, or conflicting "
                          f"with an applied tweak).")
        unverified_note = ""
        if unverified:
            unverified_note = (
                f"\n\n\u26a0\ufe0f Skipping {len(unverified)} tweak(s) not verified "
                f"by the safety audit. They are not in this batch because a "
                f"one-click action is not the place to accept an unverified "
                f"change \u2014 open each card to read why and apply it yourself.")
        risky_ids = [i for i in ids if BY_ID.get(i, {}).get("confirm")]
        risk_note = ""
        if risky_ids:
            risk_note = (
                f"\n\n\u26a0\ufe0f {len(risky_ids)} of these tweaks adjust low-level "
                f"CPU boost or power-management settings. These are ordinary "
                f"Windows settings, and everything can be reverted with the "
                f"card buttons.")
        if not self._confirm(
                "Apply All",
                f"Apply {len(ids)} visible recommended tweak(s) to your "
                f"system?\n\nThis changes registry, services and power "
                f"settings. Everything can be reverted." + block_note
                + unverified_note + risk_note):
            return
        toast(f"Applying {len(ids)} tweaks\u2026", "info", self)
        self._run_batch(ids, "apply")

    def request_revert_all(self):
        """Undo every tweak currently applied in this category.

        The page owns the confirm dialog and only calls this once the user has
        confirmed. The id list is rebuilt here from live state, so a page that
        went stale while the dialog was open cannot make the app revert a tweak
        that is not actually applied.
        """
        if self._busy:
            return
        ids = [t["id"] for t in self._source_tweaks()
               if self.ctx.live_active(t["id"])]
        if not ids:
            self._show_toast(
                "warn", "Nothing to revert yet - apply some tweaks first")
            return
        self._run_batch(ids, "revert", kind="revert_all")

    @staticmethod
    def _confirm(title, text) -> bool:
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning)
        yes = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _run_batch(self, ids, mode, kind=None):
        self._busy = True
        self._in_flight.update(ids)
        self._batch_ids = list(ids)
        self._batch_mode = mode
        self._batch_kind = kind or mode
        self._last_results = {}
        self._js("window.mx && window.mx.setBusy(true)")
        if self._worker and self._worker.isRunning():
            if hasattr(self._worker, "cancel"):
                self._worker.cancel()
            self._worker.wait(5000)
        self._worker = BatchWorker(ids, mode, self, profile=self.ctx.profile)
        self._worker.batch_done.connect(self._on_batch_done)
        self._worker.batch_error.connect(self._on_batch_error)
        self._worker.start()

    @staticmethod
    def _needs_reboot(tid) -> bool:
        return "reboot" in ((BY_ID.get(tid) or {}).get("tags") or [])

    def _show_toast(self, stype, title, sub=None, delay_ms=0):
        """Fire an accent-bar toast inside the page (window.mx.showToast).
        Delaying is queued in the app so multi-outcome batches read as separate
        toasts stacked bottom-up, matching the reference preview."""
        script = ("window.mx && window.mx.showToast({}, {}, {})".format(
            json.dumps(stype, ensure_ascii=False),
            json.dumps(title, ensure_ascii=False),
            json.dumps(sub or "", ensure_ascii=False)))
        if delay_ms:
            QTimer.singleShot(delay_ms, lambda s=script: self._js(s))
        else:
            self._js(script)

    def _on_batch_done(self, result):
        self._busy = False
        results = result.get("results", {})
        self._last_results = results
        ok_ids = [tid for tid, r in results.items()
                  if r.get("ok") and r.get("status") != "dry_run"]
        failed = {tid: r for tid, r in results.items() if tid not in ok_ids}
        ids = self._batch_ids
        names = {tid: (BY_ID.get(tid) or {}).get("name", tid) for tid in ids}
        mode = self._batch_kind

        # A blocked tweak is not a failure. Reporting it as one teaches users that
        # the app tried to do something dangerous and failed, when in fact it
        # correctly refused. Each blocked class gets its own outcome line with
        # the concrete reason, so "why did this not apply?" is always answered.
        locked = {tid: r for tid, r in failed.items() if r.get("status") == "locked"}
        not_compatible = {
            tid: r for tid, r in failed.items()
            if r.get("status") == "not_compatible"}
        blocked = {tid: r for tid, r in failed.items()
                   if tid not in locked and tid not in not_compatible}

        if mode == "apply" and locked:
            # Entitlement denial: name the plan, since that is the actionable step.
            need = ""
            for tid, r in locked.items():
                m = re.search(r"part of the ([A-Za-z]+) plan", r.get("detail") or "")
                if m:
                    need = m.group(1)
                    break
            subs = "; ".join(
                (locked[tid].get("detail") or names[tid]) for tid in ids if tid in locked)
            self._show_toast(
                "warn",
                f"LOCKED \u2014 {len(locked)} tweak"
                f"{'s' if len(locked) > 1 else ''} not in your plan.",
                subs + (f" Upgrade to {need} to unlock." if need else ""))

        if mode == "apply" and not_compatible:
            self._show_toast(
                "warn",
                f"FAIL \u2014 NOT COMPATIBLE ({len(not_compatible)} tweak"
                f"{'s' if len(not_compatible) > 1 else ''}).",
                "; ".join((not_compatible[tid].get("detail") or names[tid])
                          for tid in ids if tid in not_compatible),
                delay_ms=300 if locked else 0)

        if mode == "apply" and blocked:
            self._show_toast(
                "error",
                f"Could not apply {len(blocked)} tweak"
                f"{'s' if len(blocked) > 1 else ''}.",
                "; ".join((blocked[tid].get("detail") or names[tid])
                          for tid in ids if tid in blocked),
                delay_ms=600 if (locked or not_compatible) else 300)

        # Every non-success outcome for an apply was already reported above with
        # its own class and reason, so only real successes are handled from here.
        if mode == "apply" and len(ids) == 1:
            # Single-tweak apply: success, plus a stacked reboot warning ~450ms
            # later when the change needs a restart. A single tweak that was
            # blocked produced its toast above and nothing more here, so one
            # refused apply never renders as both a warning and an error.
            tid = ids[0]
            if tid in ok_ids:
                self._show_toast("success", "Applied 1 tweak successfully.",
                                 names[tid])
                if self._needs_reboot(tid):
                    self._show_toast("warn", "Reboot required.",
                                     "Some changes need a restart",
                                     delay_ms=450)
        elif mode == "apply":
            # Apply-all: success and reboot toasts only. Blocked/failed lines
            # were emitted above, staggered so each outcome reads as its own
            # result instead of one blob.
            succeeded = [tid for tid in ids if tid in ok_ids]
            if succeeded:
                n = len(succeeded)
                subs = ", ".join(names[tid] for tid in succeeded)
                self._show_toast(
                    "success",
                    f"Applied {n} tweak{'s' if n > 1 else ''} successfully.",
                    subs)
            needs_reboot = next(
                (tid for tid in succeeded if self._needs_reboot(tid)), None)
            if needs_reboot:
                self._show_toast("warn", "Reboot required.",
                                 "Some changes need a restart", delay_ms=600)
        elif mode == "revert_all":
            # Revert-all: one confirmation, one summary line. Failures are
            # still reported on their own so a partial revert is never hidden
            # behind the success toast.
            reverted = [tid for tid in ids if tid in ok_ids]
            if reverted:
                self._show_toast("success", "All tweaks reverted")
            failed_ids = [tid for tid in ids if tid in failed]
            if failed_ids:
                n = len(failed_ids)
                subs = ", ".join(
                    (failed[tid].get("detail") or names[tid])
                    for tid in failed_ids)
                self._show_toast(
                    "error",
                    f"Could not revert {n} tweak{'s' if n > 1 else ''}.",
                    subs, delay_ms=300)
        else:
            # Revert: same separation, no reboot warning (reverting a
            # reboot-tagged tweak clears the restart requirement).
            reverted = [tid for tid in ids if tid in ok_ids]
            if reverted:
                n = len(reverted)
                subs = ", ".join(names[tid] for tid in reverted)
                self._show_toast(
                    "success",
                    f"Reverted {n} tweak{'s' if n > 1 else ''} successfully.",
                    subs)
            failed_ids = [tid for tid in ids if tid in failed]
            if failed_ids:
                n = len(failed_ids)
                subs = ", ".join(
                    (failed[tid].get("detail") or names[tid])
                    for tid in failed_ids)
                self._show_toast(
                    "error",
                    f"Could not revert {n} tweak{'s' if n > 1 else ''}.",
                    subs, delay_ms=300)
        self._post_batch(ok_ids)

    def _on_batch_error(self, msg):
        self._busy = False
        self._in_flight.clear()
        self._js("window.mx && window.mx.setBusy(false)")
        self._show_toast("error", "Could not apply tweaks.",
                         msg or "Batch failed")
        self.ctx.invalidate_state()
        self.ctx.note_state_change()
        self._push()

    def _post_batch(self, ids):
        """Record the user's choice in state.json (decisions win over stale
        live audits), the same as the native TweaksPage."""
        results = getattr(self, "_last_results", {})
        with state_mgr.state_batch():
            for tid in self._batch_ids:
                r = results.get(tid) or {}
                ok = r.get("ok") and r.get("status") != "dry_run"
                if not ok:
                    self.ctx.live.pop(tid, None)
                    continue
                if self._batch_mode == "revert":
                    state_mgr.unmark_applied(tid)
                    state_mgr.mark_disabled(tid)
                    self.ctx.live[tid] = False
                else:
                    state_mgr.mark_applied(tid)
                    state_mgr.unmark_disabled(tid)
                    self.ctx.live[tid] = True
        self._in_flight.clear()
        self.ctx.invalidate_state()
        self.ctx.force_audit_ids(ids)
        self.ctx.note_state_change()
        self._js("window.mx && window.mx.setBusy(false)")
        self._push()