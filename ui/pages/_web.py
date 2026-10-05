"""Shared QWebEngineView factory for the HTML pages.

Enforces two page-level look-and-feel rules across every embedded view:

  * no stock Chromium right-click menu — QtWebEngine's DefaultContextMenu
    offers Back/Forward/Reload/Pause-style actions that don't belong to the
    app shell and confuse users in the categories/pages area;
  * no stock Chromium scrollbar — the Windows v8-style grey thumb sitting on
    the page's full right edge reads as a stray "slider" next to the dark UI.

Scrollbars are only hidden, not disabled: wheel/touch/keyboard scrolling
still works. If a page later wants visible scrollbars, replace the injected
CSS rule here instead of going back to the stock thumb.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView

# The window's own base colour. Chromium paints this behind a document that has
# no background of its own, and it is what a page shows in the frame between
# being created and its first paint. Left at Chromium's default it flashes
# white; matching the shell means any such frame reads as dark instead.
PAGE_BG = QColor("#0b0a14")

_HIDE_SCROLLBARS_JS = (
    "(function(){"
    "try{"
    "var css='::-webkit-scrollbar{width:0!important;height:0!important;"
    "background:transparent!important;display:none!important}"
    "html,body{scrollbar-width:none!important}';"
    "var el=document.getElementById('mx-no-scrollbars');"
    "if(!el){el=document.createElement('style');el.id='mx-no-scrollbars';"
    "document.head.appendChild(el);}"
    "el.textContent=css;"
    "}catch(e){}"
    "})();"
)


def make_webview(parent=None) -> QWebEngineView:
    """Build a QWebEngineView with shell-consistent context menu + scrollbar."""
    view = QWebEngineView(parent)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    view.page().setBackgroundColor(PAGE_BG)
    view.loadFinished.connect(
        lambda _ok: view.page().runJavaScript(_HIDE_SCROLLBARS_JS))
    return view