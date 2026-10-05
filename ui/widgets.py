"""Reusable UI widgets: premium cards, badges, dialogs and the launch screen.

Design rules (see config.app_config.THEME):
  * neutrals build the surface hierarchy (deep bg -> panels -> cards)
  * green = applied/enabled/success   red = disabled/reverted/error
  * yellow = warning/attention        accent = the only decorative color
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    QThread,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.app_config import THEME as T
from database import BY_ID
from database.tweaks._base import is_new_tweak, is_updated_tweak
from engine import activity, applier, state as state_mgr
from engine.probe import evaluate_support
from ui.categories import affects_for, group_key_for_category, logo_path


def tint_pixmap(pix: QPixmap, color: str) -> QPixmap:
    """Return a copy of *pix* recolored to *color*, preserving alpha."""
    if pix.isNull():
        return pix
    tinted = QPixmap(pix.size())
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.drawPixmap(0, 0, pix)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), QColor(color))
    p.end()
    return tinted


# Lucide line icons used by the color-coded sidebar. These are the exact
# 1.5-stroke SVG glyphs embedded in the reference design (lucide-static,
# ISC licensed). Rendered inline so the bundled app needs no external assets.
NAV_LUCIDE = {
    "home": '<path d="M3 11l9-7 9 7M5 10v9a1 1 0 001 1h4v-6h4v6h4a1 1 0 001-1v-9"/>',
    "cpu": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/>',
    "gpu": '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 7v10M17 7v10"/>',
    "ram": '<rect x="4" y="9" width="16" height="6" rx="1"/>',
    "games": '<rect x="3" y="7" width="18" height="10" rx="2"/>'
             '<circle cx="8" cy="12" r="1.3"/><circle cx="12" cy="12" r="1.3"/>',
    "fpsboost": '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
    "system": '<circle cx="12" cy="12" r="3"/>'
              '<path d="M19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 00-2-1.2L14 3h-4l-.4 2.6a7 7 0 00-2 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 005 12"/>',
    "storage": '<rect x="3" y="4" width="18" height="6" rx="1"/>'
               '<rect x="3" y="14" width="18" height="6" rx="1"/>',
    "audio": '<path d="M3 12h3l2-6 4 12 3-9 2 5h4"/>',
    "network": '<circle cx="6" cy="7" r="2"/><circle cx="18" cy="7" r="2"/>'
               '<circle cx="12" cy="17" r="2"/>'
               '<path d="M6 9v2a2 2 0 002 2h2M18 9v2a2 2 0 01-2 2h-2M12 15v-2"/>',
    "keyboard": '<rect x="2" y="6" width="20" height="12" rx="2"/>'
                '<path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>',
    "mouse": '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 3v7"/>',
    "input": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "tools": '<path d="M14.7 6.3a4 4 0 00-5.4 5.4L4 17v3h3l5.3-5.3a4 4 0 005.4-5.4l-2.6 2.6-2-2z"/>',
    "delay_destroyer": '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
    "debloat": '<path d="M11 2v2"/><path d="M12 3h-2"/><path d="M13.5 10.5 22 2"/>'
               '<path d="M14.734 13.841a2 2 0 00-.314-2.42L12.58 9.58a2 2 0 00-2.421-.314l-7.657 4.461A1 1 0 002.3 15.3l6.403 6.403a1 1 0 001.571-.204z"/>'
               '<path d="M20 15v4"/><path d="M22 17h-4"/><path d="M4 4v4"/>'
               '<path d="m5 18 2-2"/><path d="M6 6H2"/><path d="m7.699 10.7 5.602 5.601"/>',
    # Official lucide "app-window" glyph (window frame with title-bar marks).
    "app_optimizers": '<rect x="2" y="4" width="20" height="16" rx="2"/>'
                      '<path d="M2 8h20"/><path d="M6 4v4"/><path d="M10 4v4"/>',
    "route_analyzer": '<circle cx="12" cy="12" r="9"/>'
                     '<path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
    "profiles": '<rect x="2" y="7" width="20" height="10" rx="4"/>'
                '<circle cx="8" cy="12" r="1.3"/><circle cx="16" cy="12" r="1.3"/>',
    "controller": '<line x1="6" x2="10" y1="12" y2="12"/>'
                  '<line x1="8" x2="8" y1="10" y2="14"/>'
                  '<line x1="15" x2="15.01" y1="13" y2="13"/>'
                  '<line x1="18" x2="18.01" y1="11" y2="11"/>'
                  '<rect x="2" y="6" width="20" height="12" rx="2"/>',
    "fortnite": '<path d="M6 3v18M6 3h10l-3 4 3 4H6"/>',
    "chat": '<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>',
    "settings": '<circle cx="12" cy="12" r="3"/>'
                '<path d="M19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 00-2-1.2L14 3h-4l-.4 2.6a7 7 0 00-2 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 005 12"/>',
    # Added for the bottom dock, which needs a few glyphs the old sidebar
    # never drew. Same lucide geometry, same stroke-width, same family.
    # "monitor" is the dock's Windows/System category orb (distinct from the
    # gear used by the Settings category and the Windows/System tile), "gauge"
    # is the FPS boost page, and "activity" is the Diagnostics page.
    "monitor": '<rect width="20" height="14" x="2" y="3" rx="2"/>'
               '<line x1="8" x2="16" y1="21" y2="21"/>'
               '<line x1="12" x2="12" y1="17" y2="21"/>',
    "gauge": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
              '<path d="M12 9v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    "hourglass": '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.17a2 2 0 0 0-.59-1.42L12 12l-4.41 4.41A2 2 0 0 0 7 18.83V22"/>'
                 '<path d="M7 2v4.17a2 2 0 0 0 .59 1.42L12 12l4.41-4.41A2 2 0 0 0 17 5.83V2"/>',
    "ban": '<circle cx="12" cy="12" r="10"/><path d="m4.93 4.93 14.14 14.14"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/>'
              '<path d="M12 22s8-3.5 8-10V5l-8-3-8 3v7c0 6.5 8 10 8 10z"/>',
}


def _lucide_svg(kind: str) -> str:
    """Full lucide SVG document for *kind* (stroke-width 1.5)."""
    body = NAV_LUCIDE.get(kind)
    if not body:
        return ""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round">{}</svg>'.format(body)
    )


# Brand logos (Simple Icons, CC-0 licensed, bundled inline). Single-path
# monochrome glyphs on a 24x24 viewBox, rendered fill-colorable like lucide.
_BRAND_FILL = {
    "discord": "#5865F2",
    "steam": "#1B2838",
    "epicgames": "#313131",
    "riotgames": "#EB0029",
    "battledotnet": "#4381C3",
}

BRAND_SVGS = {
    "discord": ('M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 '
                '00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-'
                '.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 '
                '00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 '
                '00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 '
                '00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 '
                '00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 '
                '00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 '
                '01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 '
                '01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 '
                '01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 '
                '12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.'
                '7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 '
                '3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-'
                '.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 '
                '15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 '
                '2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 '
                '2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-'
                '2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 '
                '2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z'),
    "steam": ('M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 '
              '1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-'
              '2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 '
              '4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.'
              '004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-'
              '2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 '
              '11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.'
              '262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-'
              '.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-'
              '.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.'
              '957-1.497 1.41-2.454 1.012H7.54zm11.415-9.303c0-1.662-1.353-'
              '3.015-3.015-3.015-1.665 0-3.015 1.353-3.015 3.015 0 1.665 1.35 '
              '3.015 3.015 3.015 1.663 0 3.015-1.35 3.015-3.015zm-5.273-.005c0-'
              '1.252 1.013-2.266 2.265-2.266 1.249 0 2.266 1.014 2.266 2.266 0 '
              '1.251-1.017 2.265-2.266 2.265-1.253 0-2.265-1.014-2.265-2.265z'),
    "epicgames": ('M3.537 0C2.165 0 1.66.506 1.66 1.879V18.44a4.262 4.262 0 00.'
                  '02.433c.031.3.037.59.316.92.027.033.311.245.311.245.153.075.'
                  '258.13.43.2l8.335 3.491c.433.199.614.276.928.27h.002c.314.'
                  '006.495-.071.928-.27l8.335-3.492c.172-.07.277-.124.43-.2 0 0 '
                  '.284-.211.311-.243.28-.33.285-.621.316-.92a4.261 4.261 0 00.'
                  '02-.434V1.879c0-1.373-.506-1.88-1.878-1.88zm13.366 3.11h.68c1.'
                  '138 0 1.688.553 1.688 1.696v1.88h-1.374v-1.8c0-.369-.17-.54-'
                  '.523-.54h-.235c-.367 0-.537.17-.537.539v5.81c0 .369.17.54.'
                  '537.54h.262c.353 0 .523-.171.523-.54V8.619h1.373v2.143c0 '
                  '1.144-.562 1.71-1.7 1.71h-.694c-1.138 0-1.7-.566-1.7-1.71V4.'
                  '82c0-1.144.562-1.709 1.7-1.709zm-12.186.08h3.114v1.274H6.117v2.'
                  '603h1.648v1.275H6.117v2.774h1.74v1.275h-3.14zm3.816 0h2.198c1.'
                  '138 0 1.7.564 1.7 1.708v2.445c0 1.144-.562 1.71-1.7 1.71h-.799v3.'
                  '338h-1.4zm4.53 0h1.4v9.201h-1.4zm-3.13 1.235v3.392h.575c.354 0 '
                  '.523-.171.523-.54V4.965c0-.368-.17-.54-.523-.54zm-3.74 10.147a1.'
                  '708 1.708 0 01.591.108 1.745 1.745 0 01.49.299l-.452.546a1.247 '
                  '1.247 0 00-.308-.195.91.91 0 00-.363-.068.658.658 0 00-.28.06.'
                  '703.703 0 00-.224.163.783.783 0 00-.151.243.799.799 0 00-.056.'
                  '299v.008a.852.852 0 00.056.31.7.7 0 00.157.245.736.736 0 00.'
                  '238.16.774.774 0 00.303.058.79.79 0 00.445-.116v-.339h-.548v-'
                  '.565H7.37v1.255a2.019 2.019 0 01-.524.307 1.789 1.789 0 01-'
                  '.683.123 1.642 1.642 0 01-.602-.107 1.46 1.46 0 01-.478-.3 1.371 '
                  '1.371 0 01-.318-.455 1.438 1.438 0 01-.115-.58v-.008a1.426 1.426 0 '
                  '01.113-.57 1.449 1.449 0 01.312-.46 1.418 1.418 0 01.474-.309 '
                  '1.58 1.58 0 01.598-.111 1.708 1.708 0 01.045 0zm11.963.008a2.006 '
                  '2.006 0 01.612.094 1.61 1.61 0 01.507.277l-.386.546a1.562 1.562 '
                  '0 00-.39-.205 1.178 1.178 0 00-.388-.07.347.347 0 00-.208.052.'
                  '.154.154 0 00-.07.127v.008a.158.158 0 00.022.084.198.198 0 00.'
                  '076.066.831.831 0 00.147.06c.062.02.14.04.236.061a3.389 3.389 0 '
                  '01.43.122 1.292 1.292 0 01.328.17.678.678 0 01.207.24.739.739 0 '
                  '01.071.337v.008a.865.865 0 01-.081.382.82.82 0 01-.229.285 1.032 '
                  '1.032 0 01-.353.18 1.606 1.606 0 01-.46.061 2.16 2.16 0 01-.71-'
                  '.116 1.718 1.718 0 01-.593-.346l.43-.514c.277.223.578.335.9.'
                  '335a.457.457 0 00.236-.05.157.157 0 00.082-.142v-.008a.15.15 0 '
                  '00-.02-.077.204.204 0 00-.073-.066.753.753 0 00-.143-.062 2.45 '
                  '2.45 0 00-.233-.062 5.036 5.036 0 01-.413-.113 1.26 1.26 0 01-'
                  '.331-.16.72.72 0 01-.222-.243.73.73 0 01-.082-.36v-.008a.863.863 '
                  '0 01.074-.359.794.794 0 01.214-.283 1.007 1.007 0 01.34-.185 '
                  '1.423 1.423 0 01.448-.066 2.006 2.006 0 01.025 0zm-9.358.025h.'
                  '742l1.183 2.81h-.825l-.203-.499H8.623l-.198.498h-.81zm2.197.'
                  '02h.814l.663 1.08.663-1.08h.814v2.79h-.766v-1.602l-.711 1.091h-'
                  '.016l-.707-1.083v1.593h-.754zm3.469 0h2.235v.658h-1.473v.422h1.'
                  '334v.61h-1.334v.442h1.493v.658h-2.255zm-5.3.897l-.315.793h.'
                  '624zm-1.145 5.19h8.014l-4.09 1.348z'),
    "riotgames": ('M13.458.86 0 7.093l3.353 12.761 2.552-.313-.701-8.024.838-'
                  '.373 1.447 8.202 4.361-.535-.775-8.857.83-.37 1.591 9.025 '
                  '4.412-.542-.849-9.708.84-.374 1.74 9.87L24 17.318V3.5Zm.316 '
                  '19.356.222 1.256L24 23.14v-4.18l-10.22 1.256Z'),
    "battledotnet": ('M18.94 8.296C15.9 6.892 11.534 6 7.426 6.332c.206-1.36.'
                     '714-2.308 1.548-2.508 1.148-.275 2.4.48 3.594 1.854.'
                     '782.102 1.71.28 2.355.429C12.747 2.013 9.828-.282 7.607.'
                     '565c-1.688.644-2.553 2.97-2.448 6.094-2.2.468-3.915 1.3-'
                     '5.013 2.495-.056.065-.181.227-.137.305.034.058.146-.008.'
                     '194-.04 1.274-.89 2.904-1.373 5.027-1.676.303 3.333 1.713 '
                     '7.56 4.055 10.952-1.28.502-2.356.536-2.946-.087-.812-.856-'
                     '.784-2.318-.19-4.04a26.764 26.764 0 0 1-.807-2.254c-2.459 '
                     '3.934-2.986 7.61-1.143 9.11 1.402 1.14 3.847.725 6.502-'
                     '.926 1.505 1.672 3.083 2.74 4.667 3.094.084.015.287.043.'
                     '332-.034.034-.06-.08-.124-.131-.149-1.408-.657-2.64-1.828-'
                     '3.964-3.515 2.735-1.929 5.691-5.263 7.457-8.988 1.076.86 '
                     '1.64 1.773 1.398 2.595-.336 1.131-1.615 1.84-3.403 2.185a27.'
                     '697 27.697 0 0 1-1.548 1.826c4.634.16 8.08-1.22 8.458-'
                     '3.565.286-1.786-1.295-3.696-4.053-5.17.696-2.139.832-4.04.'
                     '346-5.588-.029-.08-.106-.27-.196-.27-.068 0-.067.13-.063.'
                     '187.135 1.547-.263 3.2-1.062 5.19zm-8.533 9.869c-1.96-'
                     '3.145-3.09-6.849-3.082-10.594 3.702-.124 7.474.748 10.714 '
                     '2.627-1.743 3.269-4.385 6.1-7.633 7.966h.001z'),
}


def brand_icon_pixmap(kind: str, color=None, size=16) -> QPixmap:
    """Brand glyph as a crisp QPixmap. Uses official brand color when
    *color* is None, otherwise tints to *color*."""
    path = BRAND_SVGS.get(kind)
    if not path:
        return QPixmap()
    fill = _BRAND_FILL.get(kind, "#8f93a6")
    fill = color or fill
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           'fill="{}">{}</svg>'.format(fill, path))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    renderer = QSvgRenderer()
    renderer.load(svg.encode("utf-8"))
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def nav_icon_pixmap(kind: str, color="#B6A3FF", size=16) -> QPixmap:
    """Lucide line icon as a crisp QPixmap tinted to *color*."""
    svg = _lucide_svg(kind)
    if not svg:
        return QPixmap()
    svg = svg.replace("currentColor", QColor(color).name())
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    renderer = QSvgRenderer()
    renderer.load(svg.encode("utf-8"))
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm
class NavDot(QWidget):
    """5px category dot with the reference's soft currentColor glow."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        glow = QRadialGradient(center, 7.0)
        core = QColor(self._color)
        core.setAlpha(90)
        glow.setColorAt(0.0, core)
        core.setAlpha(0)
        glow.setColorAt(0.6, core)
        p.fillRect(self.rect(), glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(center, 2.5, 2.5)
        p.end()


class NavRow(QFrame):
    """Sidebar navigation row (color-coded design).

    Renders as ``#NavRow`` with a ``#NavIcon`` pixmap + ``#NavText``.
    The active state is a QSS dynamic property and *clicked* is a signal.
    """

    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setObjectName("NavRow")
        self.setProperty("active", "false")
        self._src = QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 9, 11, 9)
        lay.setSpacing(12)

        self._icon = QLabel()
        self._icon.setObjectName("NavIcon")
        self._icon.setFixedSize(16, 16)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._opacity = QGraphicsOpacityEffect(self._icon)
        self._opacity.setOpacity(0.85)
        self._icon.setGraphicsEffect(self._opacity)
        lay.addWidget(self._icon)

        self._text = QLabel(text)
        self._text.setObjectName("NavText")
        self._text.setProperty("active", "false")
        self._text.setProperty("hovered", "false")
        self._text.setMinimumWidth(0)
        _sp = self._text.sizePolicy()
        _sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        self._text.setSizePolicy(_sp)
        lay.addWidget(self._text)

        lay.addStretch(1)

    def set_icon_pm(self, pix: QPixmap):
        self._src = pix if pix is not None else QPixmap()
        self._apply_icon()

    def _apply_icon(self):
        if self._src.isNull():
            self._icon.setPixmap(QPixmap())
            return
        pm = self._src
        if self.is_active():
            pm = tint_pixmap(pm, "#F6F4FC")
        self._icon.setPixmap(
            pm.scaled(
                self._icon.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def add_badge(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("SoonBadge")
        self.layout().addWidget(lbl)
        return lbl

    def is_active(self) -> bool:
        return self.property("active") == "true"

    def set_active(self, on: bool):
        self.setProperty("active", "true" if on else "false")
        self._text.setProperty("active", "true" if on else "false")
        self._apply_icon()
        repolish(self)
        repolish(self._text)

    def mousePressEvent(self, ev):
        self.clicked.emit()
        super().mousePressEvent(ev)

    def enterEvent(self, ev):
        self._text.setProperty("hovered", "true")
        repolish(self._text)
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._text.setProperty("hovered", "false")
        repolish(self._text)
        super().leaveEvent(ev)


def qss_rgba(color: str, alpha_byte: int) -> str:
    """QSS color with alpha.

    Qt Style Sheets parse 8-digit hex as ``#AARRGGBB`` (alpha FIRST), so
    appending two alpha digits to a ``#RRGGBB`` color (e.g. ``"#8B6BFF22"``)
    silently renders the WRONG hue. Build an explicit ``rgba(...)`` string
    instead.
    """
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha_byte / 255:.3f})"


RISK_COLORS = {
    "safe": T["success"],
    "low": T["text_dim"],
    "moderate": T["warning"],
    "advanced": T["danger"],
}
STATE_COLORS = {
    "ready": T["success"],
    "optional": T["text_dim"],
    "incompatible": T["danger"],
    "not_for_you": T["text_faint"],
    "warning": T["danger"],
}
IMPACT_COLORS = {
    "extreme": T["accent"],
    "high": T["accent"],
    "moderate": T["text_dim"],
    "low": T["text_faint"],
    "very low": T["text_faint"],
}

# Short tag labels used on premium game-profile cards.
TAG_SHORT = {
    "fps": "FPS",
    "input": "Input",
    "latency": "Latency",
    "network": "Network",
    "graphics": "Graphics",
    "performance": "Performance",
    "mouse": "Mouse",
    "audio": "Audio",
    "power": "Power",
    "game": "Game",
    "cpu": "CPU",
    "gpu": "GPU",
    "ram": "RAM",
    "storage": "SSD",
}


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def badge(text, color, filled=False):
    lbl = QLabel(text)
    lbl.setObjectName("Badge")
    if filled:
        lbl.setStyleSheet(
            f"background-color: {color}; color: {T['accent_dark']};"
            "border-radius: 8px; padding: 2px 8px; font-size: 11px;"
            "font-weight: 700; letter-spacing: 0.5px;")
    else:
        lbl.setStyleSheet(
            "color: #8B6BFF; background-color: rgba(139, 92, 246, 0.08);"
            "border: 1px solid rgba(139, 92, 246, 0.25);"
            "border-radius: 8px; padding: 2px 8px; font-size: 12px;"
            "font-weight: 500; letter-spacing: 0.5px;")
    return lbl


def chip(text, color=None):
    lbl = QLabel(text)
    lbl.setObjectName("Badge")
    if color:
        qc = QColor(color)
        lbl.setStyleSheet(
            f"color: {color};"
            f"background-color: rgba({qc.red()}, {qc.green()}, {qc.blue()}, 26);"
            f"border: 1px solid rgba({qc.red()}, {qc.green()}, {qc.blue()}, 90);"
            "border-radius: 8px; padding: 2px 8px; font-size: 12px;"
            "font-weight: 500; letter-spacing: 0.5px;")
    else:
        lbl.setStyleSheet(
            "color: #8B6BFF; background-color: rgba(139, 92, 246, 0.08);"
            "border: 1px solid rgba(139, 92, 246, 0.25);"
            "border-radius: 8px; padding: 2px 8px; font-size: 12px;"
            "font-weight: 500; letter-spacing: 0.5px;")
    return lbl


def pill(text, color, filled=True):
    """StatusPill — the bold applied/disabled/ready state label."""
    lbl = QLabel(text)
    lbl.setObjectName("StatusPill")
    if filled:
        ss = f"background-color: {color}; color: {T['accent_dark']};"
    else:
        ss = ("color: #8B6BFF; background-color: rgba(139, 92, 246, 0.08);"
              " border: 1px solid rgba(139, 92, 246, 0.25);")
    lbl.setStyleSheet(
        ss + "border-radius: 9px; padding: 3px 10px; font-size: 12px;"
        "font-weight: 500; letter-spacing: 0.6px;")
    return lbl


def risk_badge(risk):
    return badge(risk.capitalize(), RISK_COLORS.get(risk, T["text_dim"]))


def state_badge(state):
    return badge(state.replace("_", " ").upper(), STATE_COLORS.get(state, T["text_dim"]))


def admin_badge():
    return badge("ADMIN", T["accent"], filled=True)


def rec_badge(value):
    if value == "recommended":
        return badge("RECOMMENDED", T["success"], filled=True)
    if value == "optional":
        return badge("OPTIONAL", T["text_dim"])
    if value == "advanced":
        return badge("ADVANCED", T["accent"])
    if value == "guide":
        return badge("GUIDE", T["info"])
    if value == "not_recommended":
        return badge("NOT RECOMMENDED", T["danger"])
    return None


def section_label(text):
    """Small uppercase section heading (e.g. 'PC PERFORMANCE')."""
    lbl = QLabel(text.upper())
    lbl.setObjectName("SectionLabel")
    return lbl


def new_badge():
    """Prominent teal 'NEW' pill for recently added tweak cards.

    Mirrors the sidebar's teal 'SoonBadge' style but larger/more visible so it
    reads clearly in the top-right corner of a card.
    """
    lbl = QLabel("NEW")
    lbl.setObjectName("NewBadge")
    return lbl


def updated_badge():
    """Amber 'UPDATED' pill for tweak cards changed in a recent release."""
    lbl = QLabel("UPDATED")
    lbl.setObjectName("UpdatedBadge")
    return lbl


def stat_chip(value, label, color=None):
    """Header stat chip: bold colored value + uppercase label."""
    lbl = QLabel()
    lbl.setObjectName("StatChip")
    v = (f"<span style='color:{color or T['text']}; font-size:14px;"
         f"font-weight:700;'>{value}</span>")
    l = (f"<span style='color:{T['text_dim']}; font-size:11px;"
         f"font-weight:700;'>&nbsp;&nbsp;{label.upper()}</span>")
    lbl.setText(v + l)
    return lbl


def game_name(tweak) -> str:
    return (tweak.get("name") or "Profile").replace(" Profile", "").strip()


def clear_layout(layout):
    """Remove and immediately destroy every item in a layout.

    Widgets are hidden before being reparented so a repaint can never catch
    them mid-teardown as visible top-level windows overlapping the new
    content (the old clear_layout left them visible until the deferred
    delete ran, which showed stale cards on top of a freshly rebuilt grid).
    """
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                clear_layout(child)


def initials(name: str) -> str:
    words = [w for w in name.replace("-", " ").split() if w and w[0].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


class IconTile(QLabel):
    """Rounded icon tile. Shows a tinted logo pixmap when ``logo`` is given,
    otherwise falls back to the ``char`` glyph (both share the tinted-glass
    tile background + soft border)."""

    def __init__(self, char, color, size=40, font_scale=0.5, radius=None,
                 bg=None, fg=None, logo=None, lucide=None, parent=None):
        super().__init__(parent)
        self._char = char
        self._color = color
        self._size = size
        self._font_scale = font_scale
        self._radius = radius if radius is not None else size // 2 - 2
        self._bg = bg or qss_rgba(color, 0x22)
        self._fg = fg or color
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.set_logo(logo, lucide=lucide)

    def set_logo(self, logo=None, lucide=None):
        """Switch the tile to a tinted logo pixmap (path or lucide name) or
        back to the glyph."""
        self._logo = logo
        ss = (f"background-color: {self._bg};"
              f" border-radius: {self._radius}px;"
              f" border: 1px solid {qss_rgba(self._color, 0x33)};")
        if logo is None and lucide is not None:
            logo = nav_icon_pixmap(lucide, self._color,
                                   max(12, int(self._size * 0.55)))
        if logo is not None:
            if isinstance(logo, str):
                pix = QPixmap(str(logo))
                if pix.isNull():
                    pix = QPixmap()
            else:
                pix = QPixmap(logo)
            if not pix.isNull():
                if isinstance(logo, str):
                    pix = tint_pixmap(pix, self._color)
                pad = max(5, int(self._size * 0.3))
                side = self._size - pad * 2
                self.setPixmap(pix.scaled(side, side, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
                self.setToolTip(self._char)
                self.setStyleSheet(ss)
                return
        self.setText(self._char)
        ss += (f" color: {self._fg};"
               f" font-size: {max(10, int(self._size * self._font_scale))}px;"
               f" font-weight: 700;")
        self.setStyleSheet(ss)
        self.setToolTip(self._char)


class PillSwitch(QWidget):
    """The reference's .switch: a 32x18 glass pill; when ON the track turns
    category-green and the knob slides right with a soft glow. Non-clickable
    by default (the card owns the interaction)."""

    def __init__(self, color="#3FDC98", interactive=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 18)
        self._color = QColor(color)
        self._on = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not interactive)

    def set_on(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def is_on(self) -> bool:
        return self._on

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self._on:
            track = QColor(self._color)
            track.setAlpha(56)
            p.setPen(QPen(self._color.lighter(120), 1))
            p.setBrush(track)
        else:
            p.setPen(QPen(QColor(255, 255, 255, 23), 1))
            p.setBrush(QColor(255, 255, 255, 15))
        p.drawRoundedRect(QRectF(0.5, 0.5, 31, 17), 9, 9)
        knob = QRectF(3, 3, 12, 12) if not self._on else QRectF(17, 3, 12, 12)
        if self._on:
            glow = QColor(self._color)
            glow.setAlpha(90)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(knob.adjusted(-1.5, -1.5, 1.5, 1.5))
        p.setBrush(self._color if self._on else QColor("#514A70"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(knob)
        p.end()


class Avatar(QWidget):
    """Circular profile-picture widget.

    Paints the stored PFP clipped to a circle with a subtle accent ring.
    Falls back to the initials letter on a dark tile when no picture is set.
    """

    def __init__(self, size=40, letter="R", ring=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._letter = letter[:2]
        self._ring = QColor(ring or T["accent"])
        self._pixmap = None

    def set_avatar(self, path_or_none):
        if path_or_none:
            pix = QPixmap(str(path_or_none))
            if not pix.isNull():
                self._pixmap = pix
                self.update()
                return
        self._pixmap = None
        self.update()

    def set_letter(self, text: str):
        self._letter = (text or "?")[:2]
        self.update()

    def has_picture(self) -> bool:
        return self._pixmap is not None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        d = min(w, h)

        if self._pixmap is not None:
            # clip to a circle then draw the pixmap cover-fit
            path = QPainterPath()
            path.addEllipse(1, 1, d - 2, d - 2)
            p.setClipPath(path)
            src = self._pixmap
            if src.width() != src.height():
                side = min(src.width(), src.height())
                src = src.copy(
                    (src.width() - side) // 2, (src.height() - side) // 2,
                    side, side)
            p.drawPixmap(1, 1, d - 2, d - 2, src)
            p.setClipping(False)
            ring = QColor(self._ring)
            ring.setAlpha(130)
            pen = p.pen()
            pen.setColor(ring)
            pen.setWidthF(1.6)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(0.8, 0.8, d - 1.6, d - 1.6)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#141A22"))
            p.drawEllipse(0, 0, d, d)
            ring = QColor(self._ring)
            ring.setAlpha(110)
            pen = p.pen()
            pen.setColor(ring)
            pen.setWidthF(1.2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(0.8, 0.8, d - 1.6, d - 1.6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._ring))
            f = p.font()
            f.setPixelSize(max(9, int(d * 0.42)))
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._letter)


class ToggleSwitch(QAbstractButton):
    """iOS-style animated switch — cyan when checked, muted when off.

    Painted manually (QSS cannot express a knob + animated track), so it is
    unaffected by the global stylesheet.
    """

    TRACK_ON = QColor("#8B6BFF")
    TRACK_OFF = QColor("#232A35")
    TRACK_BORDER = QColor("#333B48")
    KNOB = QColor("#F6F4FC")
    KNOB_OFF = QColor("#8A94A5")
    TRACK_DISABLED = QColor("#161B22")
    KNOB_DISABLED = QColor("#3D4754")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.setFocusPolicy(Qt.StrongFocus)
        self._slide = 0.0
        self._anim = None
        self.toggled.connect(self._animate)

    # ---- animated "slide" property (0.0 off -> 1.0 on) ----
    def get_slide(self) -> float:
        return self._slide

    def set_slide(self, value: float):
        self._slide = max(0.0, min(1.0, float(value)))
        self.update()

    slide = Property(float, get_slide, set_slide)

    def _animate(self, checked: bool):
        target = 1.0 if checked else 0.0
        if self._anim is not None:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"slide", self)
        self._anim.setDuration(170)
        self._anim.setStartValue(self._slide)
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def sizeHint(self):
        return self.size()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        w, h = self.width(), self.height()
        on = self._slide
        r = h / 2.0

        if not self.isEnabled():
            track = ToggleSwitch.TRACK_DISABLED
            knob = ToggleSwitch.KNOB_DISABLED
            border = ToggleSwitch.TRACK_DISABLED.darker(115)
        else:
            track = ToggleSwitch._mix(ToggleSwitch.TRACK_OFF, ToggleSwitch.TRACK_ON, on)
            knob = ToggleSwitch.KNOB
            border = ToggleSwitch._mix(ToggleSwitch.TRACK_BORDER, ToggleSwitch.TRACK_ON, on)

        pen = QColor(border)
        pen.setAlpha(140)
        p.setPen(pen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, r, r)

        margin = 3.0
        knob_d = h - margin * 2
        x = margin + on * (w - margin * 2 - knob_d)
        y = margin
        if self.isEnabled():
            # subtle shadow under the knob
            shadow = QColor("#000000")
            shadow.setAlpha(int(90 * (1.0 - 0.0)))
            p.setBrush(shadow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(x + 0.5, y + 1.0, knob_d, knob_d)
        p.setPen(Qt.NoPen)
        p.setBrush(knob)
        p.drawEllipse(x, y, knob_d, knob_d)

    @staticmethod
    def _mix(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
            255,
        )


TOAST_COLORS = {
    "success": T["accent"],
    "error": T["danger"],
    "info": T["text_dim"],
    "warning": T["warning"],
}


class Toast(QFrame):
    """Lightweight slide-in notification pinned to the bottom-right corner.

    Created as a floating child of the host window so it overlays any page;
    mouse events pass straight through it.
    """

    def __init__(self, host, text, kind="info"):
        super().__init__(host)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        color = TOAST_COLORS.get(kind, TOAST_COLORS["info"])

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        dot = QLabel("\u25cf")
        dot.setStyleSheet(f"color: {color}; font-size: 11px;")
        lay.addWidget(dot)
        msg = QLabel(text)
        msg.setStyleSheet(
            f"color: {T['text']}; font-size: 13px; font-weight: 600;")
        msg.setWordWrap(True)
        lay.addWidget(msg, 1)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self.adjustSize()
        max_w = int(host.width() * 0.34)
        if self.width() > max_w:
            self.setFixedWidth(max_w)
            self.adjustSize()

    def show_anim(self):
        host = self.parentWidget()
        if host is None:
            return
        x = host.width() - self.width() - 24
        y = host.height() - self.height() - 24
        self.move(x, y)
        self.raise_()
        self.show()

        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        QTimer.singleShot(2600, self._dismiss)

    def _dismiss(self):
        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(320)
        fade.setStartValue(self._effect.opacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InCubic)
        fade.finished.connect(self.deleteLater)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        host = self.parentWidget()
        if host is not None:
            # Keep clear of the floating dock: sit just above its top edge so a
            # toast can never land on top of (or be hidden by) the navigation
            # bar, without reserving any space when no dock is present.
            bottom = 24
            dock = getattr(host, "dock", None)
            if dock is not None and dock.isVisible():
                bottom = max(24, host.height() - dock.top_edge() + 16)
            self.move(host.width() - self.width() - 24,
                      host.height() - self.height() - bottom)


def toast(text, kind="info", parent=None):
    """Show a bottom-right notification on the nearest top-level window."""
    from PySide6.QtWidgets import QApplication
    host = parent
    while host is not None and host.parentWidget() is not None:
        host = host.parentWidget()
    if host is None:
        host = QApplication.activeWindow()
    if host is None:
        host = QApplication.instance().activeWindow()
    if host is None:
        return
    Toast(host, text, kind).show_anim()


class StatCard(QFrame):
    def __init__(self, icon, title, value="--", sub="", accent=T["accent"], parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(12)
        lay.addWidget(IconTile(icon, accent, size=38, font_scale=0.5))
        box = QVBoxLayout()
        box.setSpacing(1)
        value_lbl = QLabel(str(value))
        value_lbl.setObjectName("StatValue")
        value_lbl.setStyleSheet(f"color: {accent};")
        title_lbl = QLabel(title)
        title_lbl.setObjectName("StatLabel")
        box.addWidget(value_lbl)
        box.addWidget(title_lbl)
        if sub:
            sub_lbl = QLabel(sub)
            sub_lbl.setObjectName("Tag")
            box.addWidget(sub_lbl)
        lay.addLayout(box, 1)


class SectionHeader(QFrame):
    """Section title with a small accent tick on the left."""

    def __init__(self, text):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        tick = QFrame()
        tick.setFixedSize(3, 16)
        tick.setStyleSheet(
            f"background-color: {T['accent']}; border-radius: 1.5px;")
        lay.addWidget(tick)
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        lay.addWidget(lbl)
        lay.addStretch()


class PageHeader(QFrame):
    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("Header")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("PageTitle")
        s = QLabel(subtitle)
        s.setObjectName("PageSub")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)


class GuideDialog(QDialog):
    """Step-by-step walkthrough for a guidance-only tweak.

    Shows the guide steps front and center (each guidance action becomes a
    numbered step) with the description and "why it matters" as context.
    """

    def __init__(self, tweak: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tweak["name"])
        self.resize(640, 520)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        head = QLabel(
            f"<b style='color:{T['accent']}'>{tweak['id']}</b> &nbsp;|&nbsp; "
            f"{tweak['category']}")
        lay.addWidget(head)

        desc = tweak.get("desc") or ""
        if desc:
            d = QLabel(desc)
            d.setObjectName("PageSub")
            d.setWordWrap(True)
            lay.addWidget(d)

        lay.addWidget(QLabel("<b>Steps</b>"))
        steps = QPlainTextEdit()
        steps.setReadOnly(True)
        steps.setMinimumHeight(180)
        n = 0
        for action in tweak.get("actions", []):
            if not isinstance(action, (list, tuple)) or not action:
                continue
            if action[0] != "guidance":
                continue
            n += 1
            text = action[1] if len(action) > 1 else ""
            steps.appendPlainText(f"{n}.  {text}")
        if n == 0:
            steps.appendPlainText("No manual steps are documented for this "
                                  "tweak \u2014 see the description above.")
        lay.addWidget(steps)

        why = tweak.get("why") or ""
        if why:
            lay.addWidget(QLabel("<b>Why it matters</b>"))
            w = QLabel(why)
            w.setObjectName("PageSub")
            w.setWordWrap(True)
            lay.addWidget(w)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class PreviewDialog(QDialog):
    """Shows the exact actions a tweak performs before applying."""
    def __init__(self, tweak, mode="actions", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Preview \u2014 {tweak['name']}")
        self.resize(680, 460)
        lay = QVBoxLayout(self)

        head = QLabel(
            f"<b style='color:{T['accent']}'>{tweak['id']}</b> &nbsp;|&nbsp; "
            f"{tweak['category']} &nbsp;|&nbsp; risk: <b>{tweak.get('risk', 'safe')}</b> "
            f"&nbsp;|&nbsp; impact: <b>{tweak.get('impact', 'low')}</b>")
        desc = QLabel(tweak.get("desc") or tweak.get("description") or "")
        desc.setObjectName("PageSub")
        desc.setWordWrap(True)
        lay.addWidget(head)
        lay.addWidget(desc)

        lay.addWidget(QLabel(""))
        actions = tweak.get(mode) or []
        if not actions:
            info = QLabel("This tweak has no direct actions (informational/guidance).")
            info.setObjectName("PageSub")
            lay.addWidget(info)
        else:
            lay.addWidget(QLabel(f"<b>{'Actions' if mode == 'actions' else 'Revert steps'}:</b>"))
            box = QPlainTextEdit()
            box.setReadOnly(True)
            for a in actions:
                box.appendPlainText(f"  \u2022 {format_action(a)}")
            lay.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


def format_action(action) -> str:
    """Render an action tuple/list as a readable one-liner."""
    if isinstance(action, dict):
        return (action.get("name") or "action") + f"  [{action.get('action_type', '?')}]"
    if not isinstance(action, (list, tuple)) or not action:
        return str(action)
    kind = action[0]
    if kind == "reg" and len(action) >= 5:
        return f"registry: {action[1]}\\{action[2]} = {action[3]}  ({action[4]})"
    if kind == "regall" and len(action) >= 5:
        return f"registry (all subkeys): {action[1]}\\{action[2]}\\* = {action[3]}  ({action[4]})"
    if kind == "regdel" and len(action) >= 3:
        return f"registry delete: {action[1]}\\{action[2]}"
    if kind == "regdelall" and len(action) >= 3:
        return f"registry delete (all subkeys): {action[1]}\\{action[2]}\\*"
    if kind == "regkeydel" and len(action) >= 2:
        return f"registry key delete: {action[1]}"
    if kind == "svc" and len(action) >= 3:
        return f"service: {action[1]} -> {action[2]}"
    if kind == "sc":
        return "service: " + " ".join(str(x) for x in action[1:])
    if kind in ("svcstart", "svcstop"):
        return f"service: {action[1]} -> {kind[3:].upper()}"
    if kind == "cmd":
        return f"command: {(action[1] if len(action) > 1 else '')[:120]}"
    if kind == "file" and len(action) >= 3:
        return f"file: {action[1]}"
    if kind == "power":
        return f"power: {action[1]} = {action[2]}" + (f"  ({action[3]})" if len(action) > 3 else "")
    if kind == "powerscheme":
        return "power scheme: " + " ".join(str(x) for x in action[1:])
    if kind == "sched":
        return f"scheduled task: {action[1]} -> {action[2]}"
    if kind == "appx":
        return f"appx: {action[1]} -> {action[2]}"
    if kind == "restart":
        return "restart explorer.exe"
    if kind == "mkdir":
        return f"create folder: {action[1]}"
    if kind == "guidance":
        return f"guidance: {(action[1] if len(action) > 1 else '')[:140]}"
    if kind == "netadp":
        return f"network adapter: {(action[1] if len(action) > 1 else '')}"
    return str(action)


class FlowLayout(QLayout):
    """Wrapping layout — items flow to a new line when they don't fit."""

    def __init__(self, parent=None, margin=0, hspacing=6, vspacing=6):
        super().__init__(parent)
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(margin, margin, margin, margin)
        self._items: list[QLayoutItem] = []

    def __del__(self):
        while self.count():
            self.takeAt(0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize(0, 0)
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test: bool):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for it in self._items:
            wid = it.widget()
            sh = it.sizeHint()
            hfw = wid.heightForWidth(sh.width()) if wid else -1
            w = sh.width()
            h = hfw if hfw >= 0 else sh.height()
            if x + w > right + 1 and line_h > 0:
                x = rect.x() + m.left()
                y = y + line_h + self._v
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x = x + w + self._h
            line_h = max(line_h, h)
        return y + line_h + m.bottom() - rect.y()


def _rec_badge(text="Recommended"):
    """Reference .rec-badge: tiny violet mono tag."""
    lbl = QLabel(text.upper())
    lbl.setStyleSheet(
        "font-family: \"JetBrains Mono\", \"Cascadia Mono\", monospace;"
        " font-size: 9px; color: #C9C0FF;"
        " background-color: rgba(139,107,255,0.12);"
        " border: 1px solid rgba(139,107,255,0.30);"
        " border-radius: 5px; padding: 3px 7px;")
    return lbl


class DotChip(QFrame):
    """Clean card marker: a category-tinted rounded chip holding a single
    glowing dot. Replaces the repeated per-category PNG logo so a page of 20+
    cards shows 20+ tidy dots instead of 20+ identical emblems. ``set_on``
    brightens the dot to the accent (applied) state."""

    def __init__(self, color, size=32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(color)
        self._size = size
        self._on = False

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def set_on(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self._size
        rect = QRectF(0.75, 0.75, s - 1.5, s - 1.5)
        tint = QColor(self._color)
        tint.setAlpha(26 if not self._on else 42)
        p.setPen(QPen(self._color.lighter(115), 1))
        p.setBrush(tint)
        p.drawRoundedRect(rect, 9, 9)
        dc = QColor(self._color) if not self._on else QColor("#4ADE80")
        # soft glow behind the dot
        glow = QColor(dc)
        glow.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(s / 2 - 7, s / 2 - 7, 14, 14))
        p.setBrush(dc)
        p.drawEllipse(QRectF(s / 2 - 4, s / 2 - 4, 8, 8))
        p.end()


#: Tweak ids are developer identifiers (apply/revert keys, state rows, catalogue
#: lookups) and are hidden from cards by default. Set ``mx.show_tweak_ids = True``
#: or the env var ``MX_SHOW_TWEAK_IDS=1`` to print them again when debugging.
SHOW_TWEAK_IDS = os.environ.get("MX_SHOW_TWEAK_IDS", "").strip() not in ("", "0", "false", "False")


def _card_title(tweak: dict) -> str:
    """Human-readable card title.

    ``name`` is the tweak's display title and ``title`` is accepted as an alias.
    Never falls back to ``id``: a record missing both would otherwise print a
    developer key where a title belongs.
    """
    for key in ("name", "title"):
        value = str(tweak.get(key) or "").strip()
        if value:
            return value
    return "Untitled tweak"


def _card_desc(tweak: dict) -> str:
    """Card body text, empty rather than the id when the record has none."""
    for key in ("desc", "description"):
        value = str(tweak.get(key) or "").strip()
        if value:
            return value
    return ""


class TweakCard(QFrame):
    """Clean click-to-toggle tweak card.

    Layout:  40px glassmorphic icon box | title + id.
             Below: concise slate description, then a row of muted chips.
    Interaction: clicking the card turns it ON (stays green); clicking again
             turns it OFF (neutral). No toggle switch.
    States:  applied      -> green glow + icon + ON badge (persistent)
             default      -> neutral card + OFF badge
             incompatible -> soft red border, INCOMPATIBLE badge, not clickable
    """

    GRID_HEIGHT = 180

    apply_requested = Signal(str)
    revert_requested = Signal(str)
    guide_requested = Signal(str)

    def __init__(self, ctx, tweak, parent=None, compact=False):
        super().__init__(parent)
        self.ctx = ctx
        self.tweak = tweak
        self.tid = tweak["id"]
        self.compact = compact
        self._syncing = False
        self._state = "default"
        self.setObjectName("tweak-card")
        self.setProperty("state", "default")

        group = group_key_for_category(tweak["category"], tweak)
        from ui.categories import CATEGORY_GROUPS
        self.meta = CATEGORY_GROUPS[group]

        # Reference card layout (.tweak):
        #   top row: category icon chip + RECOMMENDED badge (+ Guide)
        #   title -> mono id -> description -> hairline footer (meta + switch)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(0)

        cat_color = self.meta.get("color", "#3FDC98")

        # ---- tweak-top
        top = QHBoxLayout()
        top.setSpacing(8)
        self.icon_tile = DotChip(cat_color, size=32)
        top.addWidget(self.icon_tile, 0, Qt.AlignVCenter)
        top.addStretch()
        self._new_lbl = None
        if is_new_tweak(tweak):
            self._new_lbl = new_badge()
            top.addWidget(self._new_lbl, 0, Qt.AlignVCenter)
        self._upd_lbl = None
        if is_updated_tweak(tweak):
            self._upd_lbl = updated_badge()
            top.addWidget(self._upd_lbl, 0, Qt.AlignVCenter)
        self.state_badge = QLabel()
        self.state_badge.setObjectName("Badge")
        self.state_badge.hide()
        top.addWidget(self.state_badge, 0, Qt.AlignVCenter)
        if tweak.get("recommended") == "recommended":
            top.addWidget(_rec_badge(), 0, Qt.AlignVCenter)
        self.toggle = None
        if tweak.get("guidance"):
            self.btn_guide = QPushButton("\u2139  Guide")
            self.btn_guide.setObjectName("Ghost")
            self.btn_guide.setCursor(Qt.PointingHandCursor)
            self.btn_guide.setToolTip("Open the step-by-step guide")
            self.btn_guide.clicked.connect(lambda: self.guide_requested.emit(self.tid))
            top.addWidget(self.btn_guide, 0, Qt.AlignVCenter)
        outer.addLayout(top)
        outer.addSpacing(12)

        # ---- title
        # `name` is the human-readable title, so it stands on its own; the raw
        # tweak id used to be printed under it in mono, but that is a developer
        # identifier (apply/revert keys, state rows) and has no business in the
        # UI. Set mx.show_tweak_ids = True (or MX_SHOW_TWEAK_IDS=1 in the
        # environment) to bring it back for debugging.
        name_lbl = QLabel(_card_title(tweak))
        name_lbl.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: #F6F4FC;"
            " background: transparent;")
        name_lbl.setWordWrap(True)
        outer.addWidget(name_lbl)
        if SHOW_TWEAK_IDS:
            id_lbl = QLabel(tweak["id"])
            id_lbl.setStyleSheet(
                "font-family: \"JetBrains Mono\", \"Cascadia Mono\", monospace;"
                " font-size: 10px; color: #514A70; background: transparent;")
            outer.addWidget(id_lbl)
            outer.addSpacing(10)
        else:
            # One gap in place of the two the id line used to need, so the
            # title-to-description rhythm stays even with nothing printed.
            outer.addSpacing(8)

        # ---- description
        desc = QLabel(_card_desc(tweak))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            "color: #928AAD; font-size: 12px; background: transparent;")
        if not compact:
            desc.setMinimumHeight(34)
            outer.addWidget(desc, 1)
        else:
            outer.addWidget(desc)

        # ---- footer: hairline + meta (CPU \u00b7 impact) + switch
        foot_top = QFrame()
        foot_top.setFixedHeight(1)
        foot_top.setStyleSheet(
            "background-color: rgba(255,255,255,0.06); border: none;")
        outer.addSpacing(14)
        outer.addWidget(foot_top)
        outer.addSpacing(12)

        from ui.categories import CATEGORY_LABELS
        foot = QHBoxLayout()
        foot.setSpacing(8)
        impact = (tweak.get("impact") or "low").lower()
        impact_color = {"extreme": "#FF6F6F", "high": "#C9C0FF",
                        "moderate": "#E0A944"}.get(impact, "#928AAD")
        cat = CATEGORY_LABELS.get(group, self.meta["title"])
        meta_lbl = QLabel()
        meta_lbl.setTextFormat(Qt.TextFormat.RichText)
        crafted = (f" \u00b7 <span style='color:{T['accent']};'>"
                   f"\u2726 {tweak['crafted_for']}</span>"
                   if tweak.get("crafted_for") else "")
        meta_lbl.setText(
            f"<span style='color:#514A70;'>{cat} \u00b7 </span>"
            f"<span style='color:{impact_color};'>"
            f"{impact.capitalize()} impact</span>{crafted}")
        meta_lbl.setStyleSheet("font-size: 11px; background: transparent;")
        foot.addWidget(meta_lbl, 1)
        self.switch = PillSwitch(cat_color)
        foot.addWidget(self.switch, 0, Qt.AlignVCenter)
        outer.addLayout(foot)

        # ---- Soft glow painted natively in paintEvent (animated alpha).
        #
        # NOT an overlay QFrame: QGraphicsOpacityEffect composites into a
        # cached texture that lags behind the widget inside a QScrollArea,
        # leaving the border visibly "floating" at the old position while the
        # card scrolls. Painting in the card's own coordinates keeps the glow
        # glued to the card at every scroll position.
        self._glow_color = QColor("#4ADE80")
        self._glow_tint = QColor("#4ADE80")
        self._glow_tint.setAlphaF(0.12)
        self._glow_alpha = 0.0

        # Logical on/off so the first click does the right action; the card
        # shows its persistent state (green = ON, neutral = OFF).
        self.setCursor(Qt.PointingHandCursor)

        compat = ctx.state_of(self.tid)
        if compat in ("incompatible", "not_for_you"):
            self._apply_state("incompatible", reasons=(
                ctx.eval.get(self.tid, {}).get("reasons", [])))
        else:
            # Live support probes (e.g. "no Ethernet adapter"): a tweak whose
            # required hardware is absent shows INCOMPATIBLE here too, so the
            # card is honest before the user even clicks Apply. Probes only run
            # for tweaks that declare a ``support`` block and are cached.
            ok_support, support_reasons = evaluate_support(self.tweak)
            if not ok_support:
                self._apply_state("incompatible", reasons=support_reasons)
            else:
                self._apply_state(self._initial_state())
        self._make_children_click_through()

    # ---------------- State ----------------

    def _initial_state(self) -> str:
        """First paint: only the user's recorded decision paints the card.

        Live detection is deliberately not consulted (here or in
        ``set_detected``): several tweaks write the *same* Windows setting
        (e.g. network QoS keys), so detection would light a whole chain of
        related cards together. A card turns ON only when the user turns that
        card on.
        """
        if self.tid in state_mgr.applied_ids():
            return "applied"
        if self.tid in state_mgr.disabled_ids():
            return "default"
        return "default"

    def set_detected(self, value):
        """Live audit results never flip a card.

        Detection is still useful for the toolbar counter and Apply/Revert All,
        but showing a card as ON based on shared registry state is exactly what
        made related tweaks appear to turn on together.
        """
        return

    def _on_card_clicked(self):
        if self._state == "incompatible":
            return
        if self.tweak.get("guidance"):
            self.guide_requested.emit(self.tid)
            return
        if self._wanted_on:
            self._wanted_on = False
            self.revert_requested.emit(self.tid)
        else:
            if self.tweak.get("confirm") and not self._confirm_risky_apply():
                return  # user declined the warning; leave the card OFF
            self._wanted_on = True
            self.apply_requested.emit(self.tid)
        self._apply_state("applied" if self._wanted_on else "default")

    def _confirm_risky_apply(self) -> bool:
        """Warning gate for risky CPU/boost/hardware tweaks.

        The tweak's ``warn`` text (or a generic message) is shown before the
        tweak can be turned on, with a clear disclaimer that Maximum Tweaks
        is not responsible for any damage caused by applying the setting.
        """
        warn = (self.tweak.get("warn") or "").strip() or (
            "This tweak adjusts a low-level CPU, power-management, or hardware "
            "setting. These are ordinary Windows settings; if anything ever "
            "seems off, you can turn the tweak back off in the app at any time."
        )
        box = QMessageBox(self.window() or self)
        box.setWindowTitle("Quick check before applying")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"{warn}\n\n"
            "This tweak won't be applied until you confirm below. Nothing is "
            "permanent, and every tweak can be reverted from the app at any "
            "time.")
        yes = box.addButton("Yes, apply it",
                            QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _make_children_click_through(self):
        for child in self.findChildren(QWidget):
            if isinstance(child, QAbstractButton):
                continue  # keep the Guide button interactive
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            press = getattr(self, "_press_pos", None)
            if press is not None:
                delta = (event.position().toPoint() - press).manhattanLength()
                if delta <= 8:
                    self._on_card_clicked()
        super().mouseReleaseEvent(event)

    def _set_badge(self, text, color, filled=False):
        if filled:
            ss = (f"background-color: {color}; color: {T['accent_dark']};")
        else:
            ss = (f"color: {color}; border: 1px solid {color};"
                  f" background-color: {qss_rgba(color, 0x1f)};")
        self.state_badge.setStyleSheet(
            ss + "border-radius: 5px; padding: 3px 7px; font-size: 9px;"
            "font-weight: 700; letter-spacing: 0.5px;")
        self.state_badge.setText(text)
        self.state_badge.show()

    def _style_icon(self, on: bool, dim: bool = False):
        self.icon_tile.set_on(bool(on))
        self.icon_tile.setEnabled(not dim)
        self.icon_tile.update()

    def _apply_state(self, state, reasons=None):
        self.setProperty("state", state)
        self._state = state
        if state == "incompatible":
            self._set_badge("INCOMPATIBLE", T["danger"], filled=True)
            self._style_icon(False, dim=True)
            self.switch.set_on(False)
            self._hide_glow()
            self.setToolTip(
                "\n".join(reasons) if reasons else "Not compatible with this PC")
        elif state == "applied":
            self._wanted_on = True
            self.setToolTip("ON \u2014 click to turn off")
            self.state_badge.hide()
            self._style_icon(True)
            self.switch.set_on(True)
            self._fade_glow("#4ADE80", "rgba(74, 222, 128, 0.12)")
        else:
            self._wanted_on = False
            self.setToolTip("OFF \u2014 click to turn on")
            self.state_badge.hide()
            self._style_icon(False)
            self.switch.set_on(False)
            self._hide_glow()
        repolish(self)

    def _fade_glow(self, color, tint):
        self._glow_color = QColor(color)
        c = QColor(color)
        c.setAlphaF(0.12)
        self._glow_tint = c
        anim = QPropertyAnimation(self, b"glowAlpha", self)
        anim.setDuration(220)
        anim.setStartValue(self._glow_alpha)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._glow_anim = anim

    def _hide_glow(self):
        anim = QPropertyAnimation(self, b"glowAlpha", self)
        anim.setDuration(180)
        anim.setStartValue(self._glow_alpha)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._glow_anim = anim

    def _glow_alpha_value(self):
        return self._glow_alpha

    def _set_glow_alpha(self, value):
        self._glow_alpha = value
        self.update()

    glowAlpha = Property(
        float, _glow_alpha_value, _set_glow_alpha)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._glow_alpha <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        tint = QColor(self._glow_tint)
        tint.setAlphaF(tint.alphaF() * self._glow_alpha)
        p.fillPath(path, tint)
        pen = QPen(QColor(self._glow_color))
        pen.setWidthF(2.0)
        border = QColor(self._glow_color)
        border.setAlphaF(self._glow_alpha)
        pen.setColor(border)
        p.setPen(pen)
        p.drawPath(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def refresh(self):
        if self._state == "incompatible":
            return
        self._apply_state(self._initial_state())


class ProfileCard(QFrame):
    """Premium game-profile card with tags, launch and deactivate controls."""

    launch_requested = Signal(str)
    deactivate_requested = Signal(str)

    def __init__(self, ctx, tweak, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tweak = tweak
        self.tid = tweak["id"]
        self.game = game_name(tweak)
        self.setObjectName("ProfileCard")

        self.status_badge = None
        self.deactivate_btn = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(IconTile(initials(self.game), T["purple"], size=46, font_scale=0.45))
        box = QVBoxLayout()
        box.setSpacing(0)
        name = QLabel(self.game)
        name.setStyleSheet("font-size: 17px; font-weight: 700;")
        sub = QLabel("COMPETITIVE PERFORMANCE")
        sub.setStyleSheet(
            f"color: {T['accent']}; font-size: 11px; font-weight: 700;"
            "letter-spacing: 1.2px;")
        box.addWidget(name)
        box.addWidget(sub)
        head.addLayout(box, 1)
        self.status_badge = badge("READY", T["accent"])
        head.addWidget(self.status_badge)
        lay.addLayout(head)

        tags = profile_tags(tweak)
        tag_row = QHBoxLayout()
        tag_row.setSpacing(6)
        for tg in tags:
            tag_row.addWidget(chip(tg, T["purple"]))
        tag_row.addStretch()
        lay.addLayout(tag_row)

        desc = QLabel(tweak.get("desc", ""))
        desc.setObjectName("PageSub")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.btn_launch = QPushButton("LAUNCH PROFILE")
        self.btn_launch.setObjectName("Primary")
        self.btn_launch.setMinimumHeight(32)
        self.btn_launch.clicked.connect(lambda: self.launch_requested.emit(self.tid))
        foot.addWidget(self.btn_launch)
        self.deactivate_btn = QPushButton("Deactivate")
        self.deactivate_btn.setObjectName("Danger")
        self.deactivate_btn.clicked.connect(lambda: self.deactivate_requested.emit(self.tid))
        self.deactivate_btn.setVisible(False)
        foot.addWidget(self.deactivate_btn)
        foot.addStretch()
        lay.addLayout(foot)

        self.rebuild()

    def rebuild(self):
        active_now = state_mgr.get_active_profile() == self.game
        self.setProperty("active", "true" if active_now else "false")
        self.status_badge.setParent(None)
        self.status_badge = badge("ACTIVE" if active_now else "READY",
                                  T["success"] if active_now else T["accent"],
                                  filled=active_now)
        self.layout().itemAt(0).layout().addWidget(self.status_badge)
        self.deactivate_btn.setVisible(active_now)
        self.btn_launch.setText("RELAUNCH PROFILE" if active_now else "LAUNCH PROFILE")
        repolish(self)


def profile_tags(tweak) -> list[str]:
    tags = []
    for t in tweak.get("tags") or []:
        s = TAG_SHORT.get(str(t).lower())
        if s and s not in tags:
            tags.append(s)
        if len(tags) >= 3:
            break
    return tags or ["FPS", "Input", "Network"]


class BatchWorker(QThread):
    """Runs applier.run() off the UI thread with live progress signals."""

    progress = Signal(int, int, str, bool, str)  # done, total, tid, ok, summary
    batch_done = Signal(dict)
    batch_error = Signal(str)

    def __init__(self, ids, mode="apply", parent=None,
                 profile=None, force=False):
        super().__init__(parent)
        self.ids = ids
        self.mode = mode
        self.profile = profile
        self.force = force
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            result = applier.run(
                self.ids, self.mode, progress=self._on_progress,
                profile=self.profile, force=self.force,
                cancel_check=lambda: self._cancelled)
            self.batch_done.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.batch_error.emit(str(exc))

    def _on_progress(self, done, total, tid, ok, summary):
        self.progress.emit(done, total, tid, ok, summary)


class ProgressDialog(QDialog):
    """Modal dialog that runs a batch apply/revert and reports results."""

    def __init__(self, parent, ids, mode="apply", title=None, profile=None):
        super().__init__(parent)
        verb = "Applying" if mode == "apply" else "Reverting"
        self.setWindowTitle(title or f"{verb} tweaks\u2026")
        self.setModal(True)
        self.resize(560, 420)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{verb} {len(ids)} tweak(s)\u2026</b>"))

        self.bar = QProgressBar()
        self.bar.setRange(0, len(ids))
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        self.current = QLabel("Starting\u2026")
        self.current.setObjectName("PageSub")
        lay.addWidget(self.current)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log)

        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self._close_result)
        lay.addWidget(self.close_btn, alignment=Qt.AlignHCenter)

        self.worker = BatchWorker(ids, mode, self, profile=profile)
        self.worker.progress.connect(self._on_progress)
        self.worker.batch_done.connect(self._on_done)
        self.worker.batch_error.connect(self._on_error)
        self.worker.start()
        self.result = None

    def _on_progress(self, done, total, tid, ok, summary):
        self.bar.setValue(done)
        name = BY_ID.get(tid, {}).get("name", tid) if tid else ""
        if summary.startswith("Not supported on this PC:"):
            # Hardware-dependent tweak whose required device/driver is absent:
            # report it as a SKIP, never as a generic failure.
            mark = "SKIP"
            color = T["warning"]
        else:
            mark = "OK" if ok else "FAIL"
            color = T["success"] if ok else T["danger"]
        self.current.setText(f"({done}/{total}) {tid} \u2014 {name}")
        self.log.appendHtml(
            f"<span style='color:{color}'>{mark}</span>  {tid} \u2014 {name}<br/>"
            f"<span style='color:{T['text_dim']}'>  {summary}</span>")

    def _on_done(self, result):
        self.result = result
        results = result.get("results", {})
        applied = result.get("applied", [])
        ok_ids = [tid for tid, r in results.items()
                  if r.get("ok") and r.get("status") != "dry_run"]
        failed = len(results) - len(ok_ids)
        unsupported = [tid for tid, r in results.items()
                       if r.get("code") == "not_supported"]
        tail = (f" ({len(unsupported)} not supported on this PC)"
                if unsupported else "")
        self.current.setText(
            f"Done \u2014 {len(applied)} succeeded, {failed} failed/blocked{tail}.")
        self.log.appendHtml(
            f"<br/><b>{len(applied)} succeeded, {failed} failed{tail}.</b>")
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Close")

    def _on_error(self, msg):
        self.current.setText("Error")
        self.log.appendPlainText(f"ERROR: {msg}")
        self.close_btn.setEnabled(True)
        self.close_btn.setText("Close")

    def _close_result(self):
        if self.worker.isRunning():
            if hasattr(self.worker, "cancel"):
                self.worker.cancel()
            self.worker.wait(5000)
        self.accept()


class LaunchStepRow(QWidget):
    """One animated row in the profile-launch step list."""

    def __init__(self, text):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.dot = QLabel("\u25cb")
        self.dot.setFixedWidth(20)
        self.dot.setStyleSheet(
            f"color: {T['text_faint']}; font-size: 16px; font-weight: 700;")
        self.label = QLabel(text)
        self.label.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px;")
        lay.addWidget(self.dot)
        lay.addWidget(self.label, 1)

    def set_running(self):
        self.dot.setText("\u25cb")
        self.dot.setStyleSheet(
            f"color: {T['accent']}; font-size: 16px; font-weight: 700;")
        self.label.setStyleSheet(
            f"color: {T['text']}; font-size: 13px; font-weight: 600;")

    def set_done(self):
        self.dot.setText("\u2713")
        self.dot.setStyleSheet(
            f"color: {T['success']}; font-size: 16px; font-weight: 700;")
        self.label.setStyleSheet(f"color: {T['text_dim']}; font-size: 13px;")


class ProfileLaunchDialog(QDialog):
    """Animated 'LAUNCHING <GAME> PROFILE' screen that applies a profile."""

    def __init__(self, ctx, tweak, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.tweak = tweak
        self.game = game_name(tweak)
        self.setWindowTitle(f"Launching {self.game} Profile")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.resize(600, 540)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 28)
        lay.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(14)
        head.addWidget(IconTile(initials(self.game), T["purple"], size=56, font_scale=0.42))
        box = QVBoxLayout()
        box.setSpacing(1)
        self.title = QLabel(f"LAUNCHING {self.game.upper()} PROFILE")
        self.title.setStyleSheet("font-size: 19px; font-weight: 700; letter-spacing: 0.5px;")
        self.subtitle = QLabel(tweak.get("desc", ""))
        self.subtitle.setObjectName("PageSub")
        self.subtitle.setWordWrap(True)
        box.addWidget(self.title)
        box.addWidget(self.subtitle)
        head.addLayout(box, 1)
        lay.addLayout(head)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)

        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setStyleSheet(
            f"color: {T['accent']}; font-weight: 700; font-size: 12px;")
        self.pct_lbl.setAlignment(Qt.AlignRight)
        lay.addWidget(self.pct_lbl)

        steps_card = QFrame()
        steps_card.setObjectName("Card")
        self.steps_lay = QVBoxLayout(steps_card)
        self.steps_lay.setContentsMargins(18, 16, 18, 16)
        self.steps_lay.setSpacing(10)
        self.steps_rows = []
        for s in self._step_texts():
            row = LaunchStepRow(s)
            self.steps_lay.addWidget(row)
            self.steps_rows.append(row)
        self.steps_lay.addStretch()
        lay.addWidget(steps_card)

        self.status = QLabel("")
        self.status.setObjectName("PageSub")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        lay.addWidget(self.close_btn, alignment=Qt.AlignHCenter)

        self._step_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(430)
        self._timer.timeout.connect(self._next_step)
        self._timer.start()
        self._anim_tick = 0

    def _step_texts(self):
        return [
            "Loading profile\u2026",
            "Checking system\u2026",
            "Applying settings\u2026",
            "Optimizing configuration\u2026",
            "Finalizing\u2026",
        ]

    def _next_step(self):
        n = len(self.steps_rows)
        if self._step_idx < n:
            for i in range(self._step_idx):
                self.steps_rows[i].set_done()
            self.steps_rows[self._step_idx].set_running()
            self._step_idx += 1
            self.bar.setValue(int(self._step_idx / n * 100))
            self.pct_lbl.setText(f"{int(self._step_idx / n * 100)}%")
        else:
            self._timer.stop()
            for row in self.steps_rows:
                row.set_done()
            self.bar.setValue(100)
            self.pct_lbl.setText("100%")
            self._finish()

    def _finish(self):
        self.worker = BatchWorker([self.tweak["id"]], "apply", self,
                                  profile=self.ctx.profile)
        self.worker.batch_done.connect(self._done)
        self.worker.batch_error.connect(self._error)
        self.worker.start()

    def _done(self, result):
        ok = bool(result.get("applied"))
        if ok:
            state_mgr.set_active_profile(self.game)
            activity.emit("profile", f"Game profile launched: {self.game}")
            self.title.setText(f"\u2713 {self.game.upper()} PROFILE ACTIVE")
            self.title.setStyleSheet(
                f"font-size: 19px; font-weight: 700; color: {T['success']};")
            self.status.setText(
                f"{self.game} is now your active profile. All settings applied "
                "successfully \u2014 launch your game and enjoy the boost.")
        else:
            self.title.setText(f"\u2715 LAUNCH FAILED \u2014 {self.game.upper()}")
            self.title.setStyleSheet(
                f"font-size: 19px; font-weight: 700; color: {T['danger']};")
            self.status.setText("One or more steps could not be completed. See the logs.")
        self.close_btn.setEnabled(True)

    def _error(self, msg):
        self.title.setText(f"\u2715 LAUNCH FAILED \u2014 {self.game.upper()}")
        self.title.setStyleSheet(
            f"font-size: 19px; font-weight: 700; color: {T['danger']};")
        self.status.setText(f"Error: {msg}")
        self.close_btn.setEnabled(True)
