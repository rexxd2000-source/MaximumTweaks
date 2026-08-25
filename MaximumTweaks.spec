# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Maximum Tweaks.
# Build:  pyinstaller MaximumTweaks.spec  (run from the project root)

import os

from config.app_config import APP_NAME, APP_VERSION, ROOT

block_cipher = None

# Runtime data: the tweak database + config live next to main.py; artwork
# (rex_logo.png, discord_logo.png) is bundled so frozen builds keep their logos.
datas = []
for rel in ("config", "database", "assets"):
    src = ROOT / rel
    datas.append((str(src), rel))

# Ensure route_visualization widget is available
# (no globe.html needed — 3D globe removed, replaced with 2D route comparison)

# SECURITY: nothing from auth_backend/ is bundled. The desktop app talks to the
# hosted license backend over HTTPS and holds no secrets — LICENSE_SECRET,
# ADMIN_TOKEN and the license DB must never end up inside the EXE.

# Bundle the Npcap installer so end-users never have to install it manually.
# It gets auto-installed silently on first run when capture is needed.
import glob as _glob
_npcap_files = _glob.glob(str(ROOT / "assets" / "npcap-*.exe"))
for _nf in _npcap_files:
    datas.append((_nf, "assets"))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "database.executor",
        "hardware.detector",
        "engine.applier",
        "engine.bundles",
        "engine.recommender",
        "engine.state",
        "engine.activity",
        "engine.audit",
        "engine.state_checker",
        "engine.nvprofile",
        "engine.nvprofiles",
        "engine.game_detector",
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
        "engine.delay_destroyer.network_measure",
        "engine.delay_destroyer.gaming",
        "engine.delay_destroyer.scoring",
        "engine.debloat",
        "engine.debloat.engine",
        "engine.debloat.scanner",
        "engine.debloat.backup",
        "ui.main_window",
        "ui.categories",
        "ui.updater_dialog",
        "ui.pages.tweaks",
        "ui.pages.dashboard",
        "ui.pages.detect",
        "ui.pages.logs",
        "ui.pages.optimize",
        "ui.pages.profiles",
        "ui.pages.tools",
        "ui.pages.settings",
        "ui.pages.chat",
        "ui.pages.ram_selector",
        "ui.pages.delay_destroyer",
        "ui.pages.debloat",
        "ui.perf",
        "ui.widgets",
        "ui.pc_3d",
        "ui.premium_widgets",
        "ui.context",
        "ui.styles",
        "config.app_config",
        "rexlog",
        "psutil",
        "ui.pages.network_monitor",
        "ui.pages.home",
        "ui.pages.backups",
        "ui.pages.fixes",
        "ui.pages.general",
        "ui.pages.hardware",
        "ui.pages.network_page",
        "ui.pages.gamemode",
        "ui.pages.advanced",
        "ui.pages.bios",
        "ui.pages.premium",
        "ui.panels",
        "ui.panels.ai_bar",
        "ui.panels.telemetry_panel",
        "ui.panels.actions_panel",
        "engine.intel",
        "engine.intel.process_detector",
        "engine.intel.network_observer",
        "engine.intel.game_state_machine",
        "engine.intel.lobby_baseline",
        "engine.intel.endpoint_scorer",
        "engine.intel.session_manager",
        "engine.intel.optimized_route",
        "engine.intel.orchestrator",
        "engine.intel.enrichment",
        "engine.intel.traceroute",
        "engine.intel.udp_capture",
        "engine.intel.npcap_installer",
        "scapy",
        "scapy.all",
        "scapy.config",
        "scapy.arch.windows",
        "scapy.arch",
        "scapy.error",
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
    icon=str(ROOT / "assets" / "rex_app.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # keep console so --cli still works; set False for a windowed build
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
