"""Register the exact Google Fonts used by the reference HTMLs.

These are STATIC instance TTFs (one per weight, glyf outlines, no fvar
variable-table) — the earlier scribble problem came from variable font
files which Qt rasterizes incorrectly.
"""
from __future__ import annotations

from PySide6.QtGui import QFontDatabase

from config.app_config import DIRS


def register_fonts() -> list[str]:
    """Load every bundled font; returns the families actually registered."""
    families: list[str] = []
    d = DIRS["assets"] / "fonts"
    if not d.is_dir():
        return families
    for f in sorted(d.glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid < 0:
            continue
        for fam in QFontDatabase.applicationFontFamilies(fid):
            if fam not in families:
                families.append(fam)
    return sorted(families)
