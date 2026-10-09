# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Maximum Tweaks.
# Build:  pyinstaller MaximumTweaks.spec  (run from the project root)

import os

from config.app_config import APP_NAME, APP_VERSION, ROOT

block_cipher = None

# Runtime data: the tweak database + assets are bundled so frozen builds keep
# their database and logos. config/ is deliberately NOT bundled either as data
# or as a _secrets module — app_config is pulled in as a hidden import below
# but reads secrets only from the process environment or a runtime sidecar
# .txt the operator places after install (neither is shipped).
datas = []
for rel in ("database", "assets"):
    src = ROOT / rel
    datas.append((str(src), rel))
# Provider-published IP range snapshot (GCP gstatic + AWS ip-ranges) used by
# engine/netmonitor/cloudmap.py for geo overrides.
datas.append((str(ROOT / "engine/netmonitor/cloud_regions.json"), "engine/netmonitor"))
# Smart Debloater screen HTML + its locally-bundled fonts (Bricolage Grotesque
# woff2; JetBrains Mono comes from assets/fonts bundled above).
datas.append((str(ROOT / "ui/smart_debloater.html"), "ui"))
datas.append((str(ROOT / "ui/tweak_cards.html"), "ui"))
datas.append((str(ROOT / "ui/tools.html"), "ui"))
datas.append((str(ROOT / "ui/diagnostics.html"), "ui"))
datas.append((str(ROOT / "ui/dock_nav.html"), "ui"))
datas.append((str(ROOT / "ui/controller.html"), "ui"))
datas.append((str(ROOT / "ui/dashboard.html"), "ui"))
datas.append((str(ROOT / "ui/qos.html"), "ui"))
datas.append((str(ROOT / "ui/app_optimizers.html"), "ui"))
datas.append((str(ROOT / "ui/fonts"), "ui/fonts"))
# Full-bleed step-1 Updater screen (updater_fullscreen.html); fonts come from
# assets/fonts bundled above.
datas.append((str(ROOT / "ui/updater_fullscreen.html"), "ui"))

# Nothing from auth_backend/ is bundled; the app talks to the hosted license
# backend over HTTPS and holds no secrets in the EXE.

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "database.executor",
        # Loaded via importlib at runtime (database/tweaks/__init__.py), so the
        # static analysis pass cannot see the reference.
        "database.tiers",
        # Subscription system. config.checkout and ui.pages.pricing are reached
        # through __import__ / deferred imports, so they must be named here or
        # the frozen app raises ImportError on the pricing route.
        "config.plans",
        "config.checkout",
        "engine.entitlements",
        "ui.pages.pricing",
        "hardware.detector",
        "engine.applier",
        "engine.bundles",
        "engine.recommender",
        "engine.state",
        "engine.activity",
        "engine.audit",
        "engine.state_checker",
        "engine.chat",
        "engine.troubleshooter",
        "engine.nvprofile",
        "engine.nvprofiles",
        "engine.nip_parser",
        "engine.game_config",
        "engine.tools_runner",
        "engine.updater",
        "engine.optimizer",
        "engine.optimizer.base",
        "engine.optimizer.registry",
        "engine.optimizer.applicability",
        "engine.delay_destroyer",
        "engine.delay_destroyer.engine",
        "engine.delay_destroyer.scanner",
        "engine.delay_destroyer.baseline",
        "engine.delay_destroyer.diagnoser",
        "engine.delay_destroyer.fixes",
        "engine.delay_destroyer.executor",
        "engine.delay_destroyer.reporter",
        "engine.delay_destroyer.risk",
        "engine.delay_destroyer.backup",
        "engine.delay_destroyer.correlator",
        "engine.debloat",
        "engine.debloat.engine",
        "engine.debloat.scanner",
        "engine.debloat.backup",
        "engine.debloat.smart",
        "engine.app_optimizer",
        "engine.app_optimizer.core",
        "engine.app_optimizer.apps",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "ui.main_window",
        "ui.categories",
        "ui.updater_dialog",
        "ui.updater_screen",
        "ui.pages.tweaks",
        "ui.pages.dashboard",
        "ui.pages.detect",
        "ui.pages.logs",
        "ui.pages.optimize",
        "ui.pages.profiles",
        "ui.pages.tools",
        "ui.pages.settings",
        "ui.pages.controller",
        "ui.pages.qos",
        "ui.pages.diagnostics",
        "engine.controller",
        "engine.qos",
        "engine.diagnostics",
        "ui.pages.chat",
        "ui.pages.ram_selector",
        "ui.pages.delay_destroyer",
        "ui.pages.debloat",
        "ui.pages.app_optimizers",
        "ui.widgets",
        "ui.dock_nav",
        "ui.premium_widgets",
        "ui.context",
        "ui.styles",
        "config.app_config",
        "maxlog",
        "psutil",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME.replace(" ", ""),
    icon=str(ROOT / "assets" / "app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windowed: no console window may ever appear when the GUI opens (a
    # console=True build pops one for the whole onefile extraction before any
    # Python code can hide it). The CLI keeps working: --cli launched from a
    # terminal attaches to the caller's console (main.py) and exit codes are
    # unaffected by the subsystem.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
