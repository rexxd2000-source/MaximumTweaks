# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for "Maximum Tweaks Admin" (desktop license panel).
# Build (repo root):  pyinstaller admin_desktop/Admin.spec --noconfirm
# Produces:           dist\\MaximumTweaksAdmin.exe  (one-file, windowed)

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICON = ROOT / "assets" / "app.ico"

block_cipher = None

a = Analysis(
    [str(ROOT / "admin_desktop" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ICON), ".")],
    hiddenimports=[
        "admin_desktop",
        "admin_desktop.main",
        "admin_desktop.api",
        "admin_desktop.theme",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtMultimedia",
        "PySide6.QtNetworkAuth",
        "PySide6.QtPdf",
        "psutil",
        "database",
        "engine",
        "hardware",
        "tweaks",
        "ui",
        "config",
        "maxlog",
    ],
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
    name="MaximumTweaksAdmin",
    icon=str(ICON),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)