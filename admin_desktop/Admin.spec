# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for "Maximum Tweaks Admin" (desktop license panel).
# Build (repo root):  pyinstaller admin_desktop/Admin.spec --noconfirm
# Produces:           dist\\MaximumTweaksAdmin.exe  (one-file, windowed)

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICON = ROOT / "assets" / "app.ico"
FONT_DIR = ROOT / "admin_desktop" / "assets" / "fonts"

block_cipher = None

# icon -> _MEIPASS/assets/app.ico ; fonts -> _MEIPASS/admin_desktop/assets/fonts
_datas = [(str(ICON), ".")]
if FONT_DIR.is_dir():
    _datas += [(str(FONT_DIR / f.name), "admin_desktop/assets/fonts")
               for f in sorted(FONT_DIR.iterdir())
               if f.suffix.lower() == ".ttf"]

a = Analysis(
    [str(ROOT / "admin_desktop" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=_datas,
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