"""Render a clean ring-less Maximum Tweaks logo (dark tile, gradient M).

Style follows the splash/updater monogram: a rounded dark tile with a
violet gradient "M". No gauge ring / progress-looking arcs.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication

FONT = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "SpaceGrotesk-Bold.ttf"
OUT = Path(__file__).resolve().parents[1] / "assets" / "logo.png"


def render(size: int = 512, out: Path = OUT) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    s = size
    pad = int(s * 0.04)
    tile = QRectF(pad, pad, s - 2 * pad, s - 2 * pad)
    radius = s * 0.19

    path = QPainterPath()
    path.addRoundedRect(tile, radius, radius)

    # tile fill — near-black with a soft violet core
    core = QRadialGradient(
        QPointF(tile.left() + tile.width() * 0.5, tile.top() + tile.height() * 0.42),
        tile.width() * 0.75)
    core.setColorAt(0.0, QColor(36, 28, 58, 255))
    core.setColorAt(1.0, QColor(9, 7, 16, 255))
    p.fillPath(path, core)

    # hairline border (violet tint)
    p.setPen(QPen(QColor(150, 130, 235, 90), max(1, int(s * 0.012))))
    p.setBrush(Qt.NoBrush)
    border = QPainterPath()
    border.addRoundedRect(tile.adjusted(pad / 2, pad / 2, -pad / 2, -pad / 2), radius, radius)
    p.drawPath(border)

    # gradient "M" rendered as a path so the fill can be a gradient
    fid = QFontDatabase.addApplicationFont(str(FONT))
    f = QFont()
    if fid >= 0:
        fam = QFontDatabase.applicationFontFamilies(fid)[0]
        f = QFont(fam, 1)
    f.setPixelSize(int(s * 0.60))
    f.setWeight(QFont.Weight.Bold)

    tp = QPainterPath()
    tp.addText(0, 0, f, "M")
    tr = tp.boundingRect()
    tx = tile.center().x() - tr.width() / 2.0
    ty = tile.center().y() + tr.height() / 2.0
    tp.translate(tx - tr.left(), ty - tr.bottom())

    p.setClipPath(path)
    grad = QLinearGradient(0, tile.top(), 0, tile.bottom())
    grad.setColorAt(0.0, QColor("#C9C0FF"))
    grad.setColorAt(0.55, QColor("#9B8CFF"))
    grad.setColorAt(1.0, QColor("#6D4FE0"))
    p.fillPath(tp, grad)
    p.setClipping(False)
    p.end()

    pm.save(str(out), "PNG")
    print(f"wrote {out} ({size}x{size})")


if __name__ == "__main__":
    render()