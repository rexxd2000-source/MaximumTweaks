"""Optimize page: one-click presets of curated tweaks."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from database import BY_ID
from engine import bundles as bundles_mod
from ui.categories import DB_AFFECTS
from ui.widgets import ProgressDialog, risk_badge

STATE_COLORS = {
    "ready": T["green"],
    "optional": T["amber"],
    "incompatible": T["red"],
    "not_for_you": T["text_dim"],
    "warning": T["orange"],
}


class BundleCard(QFrame):
    def __init__(self, ctx, bundle, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.bundle = bundles_mod.resolve_bundle(bundle["id"])
        self.setObjectName("Card")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        head = QHBoxLayout()
        name = QLabel(self.bundle["name"])
        name.setStyleSheet("font-size: 18px; font-weight: 800;")
        head.addWidget(name)
        head.addWidget(risk_badge(self.bundle["risk"]))
        head.addStretch()
        outer.addLayout(head)

        tag = QLabel(self.bundle["tagline"])
        tag.setStyleSheet(f"color: {T['accent']}; font-weight: 700;")
        outer.addWidget(tag)

        desc = QLabel(self.bundle["description"])
        desc.setObjectName("PageSub")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        self.preview_lbl = QLabel("")
        self.preview_lbl.setWordWrap(True)
        self.preview_lbl.setStyleSheet(f"color: {T['text_dim']};")
        outer.addWidget(self.preview_lbl)

        foot = QHBoxLayout()
        btn_apply = QPushButton("Apply Preset")
        btn_apply.setObjectName("Primary")
        btn_apply.clicked.connect(self._confirm_and_apply)
        btn_detail = QPushButton("Preview Tweaks")
        btn_detail.clicked.connect(self._show_detail)
        foot.addWidget(btn_apply)
        foot.addWidget(btn_detail)
        foot.addStretch()
        outer.addLayout(foot)

        self.ctx.state_changed.connect(self._update_preview)
        self._update_preview()

    def _states(self):
        """Return (applyable, skipped) lists of tweak dicts."""
        applyable, skipped = [], []
        for tid in self.bundle["tweaks"]:
            tweak = BY_ID.get(tid)
            if not tweak:
                continue
            state = self.ctx.state_of(tid)
            if state in ("ready",):
                applyable.append(tweak)
            else:
                skipped.append((tweak, state))
        return applyable, skipped

    def _update_preview(self):
        applyable, skipped = self._states()
        text = f"• {len(applyable)} compatible tweaks will be applied"
        if skipped:
            text += f" · {len(skipped)} skipped (incompatible with this PC)"
        self.preview_lbl.setText(text)

    def _show_detail(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.bundle['name']} — included tweaks")
        dlg.resize(560, 480)
        lay = QVBoxLayout(dlg)
        box = QPlainTextEdit()
        box.setReadOnly(True)
        for tid in self.bundle["tweaks"]:
            tweak = BY_ID.get(tid)
            if not tweak:
                continue
            state = self.ctx.state_of(tid)
            color = STATE_COLORS.get(state, T["text_dim"])
            box.appendHtml(
                f"<span style='color:{T['accent']}'>{tid}</span> "
                f"<b>{tweak['name']}</b>  "
                f"<span style='color:{color}'>{state.upper()}</span>"
                f"<br/><span style='color:{T['text_dim']}'>  {tweak.get('desc','')}</span>")
        box.appendHtml("<br/><b>Legend:</b> READY = will apply · OPTIONAL = advanced · INCOMPATIBLE = skipped")
        lay.addWidget(box)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, alignment=Qt.AlignHCenter)
        dlg.exec()

    def _confirm_and_apply(self):
        applyable, skipped = self._states()
        if not applyable:
            return
        include_advanced = QCheckBox("Include advanced/optional tweaks (may affect security)")
        restore_point = QCheckBox("Create a System Restore Point first")
        restore_point.setChecked(self.bundle["risk"] in ("moderate", "advanced"))

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Apply {self.bundle['name']} preset")
        dlg.resize(560, 420)
        lay = QVBoxLayout(dlg)
        head = QLabel(
            f"<b>Apply {len(applyable)} tweak(s)</b>"
            f"{f' — {len(skipped)} skipped (incompatible)' if skipped else ''}")
        lay.addWidget(head)

        box = QPlainTextEdit()
        box.setReadOnly(True)
        for t in applyable:
            mark = "ADMIN " if t.get("admin") else ""
            cat = DB_AFFECTS.get(t["category"], t["category"])
            box.appendPlainText(f"  {t['id']}  [{mark}{cat}]  {t['name']}")
        if skipped:
            box.appendPlainText("")
            box.appendPlainText("Skipped:")
            for t, state in skipped:
                box.appendPlainText(f"  {t['id']}  {state}: {t['name']}")
        lay.addWidget(box)

        warn = QLabel("")
        warn.setObjectName("PageSub")
        warn.setWordWrap(True)
        n_admin = sum(1 for t in applyable if t.get("admin"))
        notes = []
        if n_admin:
            notes.append(
                f"{n_admin} tweak(s) require administrator privileges. Run Maximum Tweaks "
                "as Administrator for those to take effect; otherwise they are skipped.")
        risky = [t for t in applyable if t.get("confirm")]
        if risky:
            names = ", ".join(t["name"] for t in risky[:4])
            more = f" and {len(risky) - 4} more" if len(risky) > 4 else ""
            notes.append(
                f"\u26a0\ufe0f {len(risky)} tweak(s) adjust low-level CPU boost "
                f"or power-management settings. These are ordinary Windows "
                f"settings, and everything can be turned back off in the app "
                f"at any time ({names}{more}).")
        if notes:
            warn.setText("\n\n".join(notes))
        lay.addWidget(warn)

        opts = QVBoxLayout()
        opts.addWidget(include_advanced)
        opts.addWidget(restore_point)
        lay.addLayout(opts)

        row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(dlg.reject)
        btn_go = QPushButton(f"Apply {len(applyable)} Tweak(s)")
        btn_go.setObjectName("Primary")
        btn_go.clicked.connect(dlg.accept)
        row.addWidget(btn_cancel)
        row.addWidget(btn_go)
        lay.addLayout(row)

        if not dlg.exec():
            return

        ids = [t["id"] for t in applyable]
        if include_advanced.isChecked():
            for t, state in skipped:
                if state == "optional":
                    ids.append(t["id"])
        if restore_point.isChecked() and "rep-008" in BY_ID and "rep-008" not in ids:
            ids.insert(0, "rep-008")

        self._run(ids)

    def _run(self, ids):
        dlg = ProgressDialog(self, ids, "apply",
                             f"Applying {self.bundle['name']}…",
                             profile=self.ctx.profile)
        dlg.exec()
        self.ctx.note_state_change()
        self._update_preview()


class OptimizePage(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        title = QLabel("One-Click Optimize")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        sub = QLabel(
            "Curated presets of compatible tweaks. Only tweaks that work on this "
            "hardware are applied — everything else is skipped automatically. "
            "Run Hardware Detection first for full results.")
        sub.setObjectName("PageSub")
        sub.setWordWrap(True)
        root.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 0, 12, 0)
        lay.setSpacing(14)
        for bundle_id in ("balanced", "competitive", "maximum"):
            lay.addWidget(BundleCard(ctx, bundles_mod.BUNDLES[bundle_id]))
        lay.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.ctx.profile_changed.connect(self._note)
        self._note()

    def _note(self):
        pass
