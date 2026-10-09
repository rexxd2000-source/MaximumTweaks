"""Shared QWebEngineView factory for the HTML pages.

Enforces three page-level look-and-feel rules across every embedded view:

  * no stock Chromium right-click menu — QtWebEngine's DefaultContextMenu
    offers Back/Forward/Reload/Pause-style actions that don't belong to the
    app shell and confuse users in the categories/pages area;
  * no stock Chromium scrollbar — the Windows v8-style grey thumb sitting on
    the page's full right edge reads as a stray "slider" next to the dark UI;
  * no text selection or copy — the app is a product surface, not a document:
    highlighting paragraphs and copying them out looks broken. Inputs and
    textareas stay selectable so pasting (license keys, chat) still works.

Scrollbars are only hidden, not disabled: wheel/touch/keyboard scrolling
still works. If a page later wants visible scrollbars, replace the injected
CSS rule here instead of going back to the stock thumb.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView

try:  # QtWebEngineCore carries the settings enum on every supported build
    from PySide6.QtWebEngineCore import QWebEngineSettings
except Exception:  # noqa: BLE001 - older/vendored builds expose it elsewhere
    QWebEngineSettings = None

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

# The app is a product surface, not a document: no selection, no copy, no
# right-click, no drag-out, and none of the browser shortcuts that could lift
# the page's text or open devtools. The same rule the HTML pages carry
# themselves is applied centrally here so pages that omit it — and any future
# page — cannot be highlighted, copied, dragged or inspected. Inputs, textareas
# and content-editable regions stay selectable (and keep Ctrl+A/C/X) so the
# license field and chat composer remain usable for pasting.
_NO_COPY_JS = (
    "(function(){"
    "try{"
    "if(document.__mxNoCopy){return;}"
    "document.__mxNoCopy=true;"
    "var css='html,body{-webkit-touch-callout:none}"
    "body,body *{-webkit-user-select:none!important;"
    "user-select:none!important}"
    "img,a{-webkit-user-drag:none}"
    "input,textarea,[contenteditable]{-webkit-user-select:text!important;"
    "user-select:text!important}';"
    "var el=document.getElementById('mx-no-copy');"
    "if(!el){el=document.createElement('style');el.id='mx-no-copy';"
    "document.head.appendChild(el);}"
    "el.textContent=css;"
    "function editable(t){"
    "if(!t){return false;}"
    "var n=(t.tagName||'').toUpperCase();"
    "return n==='INPUT'||n==='TEXTAREA'||t.isContentEditable===true;"
    "}"
    "['copy','cut','selectstart','dragstart','contextmenu'].forEach("
    "function(type){"
    "document.addEventListener(type,function(e){"
    "if(editable(e.target)){return;}"
    "e.preventDefault();"
    "},true);"
    "});"
    "document.addEventListener('keydown',function(e){"
    "var k=(e.key||'').toLowerCase();"
    "if(k==='f12'){e.preventDefault();return;}"
    "if(e.ctrlKey&&e.shiftKey&&!e.altKey&&(k==='i'||k==='j')){"
    "e.preventDefault();return;}"
    "if(e.ctrlKey&&!e.shiftKey&&!e.altKey"
    "&&['c','x','a','u','s'].indexOf(k)!==-1){"
    "if(editable(e.target)&&['a','c','x'].indexOf(k)!==-1){return;}"
    "e.preventDefault();return;}"
    "},true);"
    "}catch(e){}"
    "})();"
)


def make_webview(parent=None) -> QWebEngineView:
    """Build a QWebEngineView with shell-consistent context menu + scrollbar."""
    view = QWebEngineView(parent)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    view.page().setBackgroundColor(PAGE_BG)
    # Devtools are a developer affordance, never a product one: turn the
    # Chromium inspector off in the frozen (shipped) build. Left on in a dev
    # checkout so debugging the HTML pages still works.
    if getattr(sys, "frozen", False) and QWebEngineSettings is not None:
        try:
            view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.DeveloperExtrasEnabled, False)
        except Exception:  # noqa: BLE001 - never block view creation on this
            pass
    view.loadFinished.connect(
        lambda _ok: (view.page().runJavaScript(_HIDE_SCROLLBARS_JS),
                     view.page().runJavaScript(_NO_COPY_JS)))
    return view