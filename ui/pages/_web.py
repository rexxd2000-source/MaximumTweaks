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

Pages also get smooth inertial scrolling, injected here the same way so every
HTML page shares one implementation (see ``_SMOOTH_SCROLL_JS``).
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

# Smooth inertial scrolling, ported from the reference demo's loop()/wheel()/
# keydown()/scroll() handlers. The demo eases a container's scrollTop toward a
# wheel/keyboard-driven target; the same idea runs here against whichever
# element owns the page's scroll: the document when the body scrolls (most
# pages), or the largest inner scrollable pane when the layout is fixed (the
# diagnostics rail). Inner scrollers under the cursor keep native behaviour so
# a page's own scroll boxes are not hijacked. Reduced motion applies the target
# directly, matching the demo's reduced-motion path.
_SMOOTH_SCROLL_JS = (
    "(function(){"
    "try{"
    "if(window.__mxSmooth){return;}window.__mxSmooth=true;"
    "var mq=window.matchMedia?window.matchMedia('(prefers-reduced-motion:reduce)'):null;"
    "var reduce=mq?mq.matches:false;"
    "var doc=document.scrollingElement||document.documentElement;"
    "var scroller=null,target=0,pos=0,last=0,raf=0,maxScroll=0,rzPend=0;"
    "function winY(){return (window.pageYOffset!=null?window.pageYOffset:(doc.scrollTop||0));}"
    "function pick(){"
    "if(doc&&doc.scrollHeight>doc.clientHeight+4){scroller=null;return;}"
    "var best=null,bestH=0,all=document.querySelectorAll('*');"
    "for(var i=0;i<all.length;i++){var el=all[i],st=getComputedStyle(el);"
    "if((st.overflowY==='auto'||st.overflowY==='scroll')&&"
    "el.scrollHeight>el.clientHeight+4&&el.clientHeight>bestH){best=el;bestH=el.clientHeight;}}"
    "scroller=best;}"
    "function curY(){return scroller?scroller.scrollTop:winY();}"
    # maxScroll is cached, never read from the DOM inside the wheel handler:
    # reading scrollHeight after writing scrollTop forces a synchronous layout
    # on every notch. It is refreshed on resize and when the page's content box
    # changes (ResizeObserver), which is when a long page actually grows.
    "function measure(){var e=scroller||doc;return Math.max(0,e.scrollHeight-e.clientHeight);}"
    "function refreshMax(){maxScroll=measure();}"
    "function maxY(){return maxScroll;}"
    "function setY(y){if(scroller){scroller.scrollTop=y;}else{window.scrollTo(0,y);}}"
    "function clamp(v,a,b){return v<a?a:(v>b?b:v);}"
    "function frame(now){"
    "var dt=(now-last)/1000;last=now;if(!(dt>0)||dt>0.05){dt=0.016;}"
    "var prev=pos;"
    "pos=reduce?target:pos+(target-pos)*(1-Math.exp(-dt*7));"
    "if(Math.abs(target-pos)<0.1){pos=target;}"
    "if(pos!==prev){setY(pos);}"
    "if(Math.abs(target-pos)>0.1){raf=requestAnimationFrame(frame);}else{raf=0;}}"
    "function start(){if(!raf){last=performance.now();raf=requestAnimationFrame(frame);}}"
    "function sync(){var y=curY();if(Math.abs(y-pos)>2){pos=target=y;}}"
    "function nearest(node){"
    "while(node&&node!==document.body&&node.nodeType===1){"
    "var st=getComputedStyle(node);"
    "if((st.overflowY==='auto'||st.overflowY==='scroll')&&"
    "node.scrollHeight>node.clientHeight+1){return node;}"
    "node=node.parentElement;}return null;}"
    "pick();refreshMax();"
    # Keep the cached maximum fresh without polling. A debounced resize handler
    # (pick() walks every element and is far too heavy to run per resize event)
    # plus a ResizeObserver on the body covers late content (the tools page is
    # filled in by JS after load).
    "if(window.ResizeObserver){"
    "window.__mxRO=new ResizeObserver(function(){"
    "if(rzPend){return;}rzPend=requestAnimationFrame(function(){rzPend=0;refreshMax();});});"
    "try{window.__mxRO.observe(document.body||document.documentElement);}catch(e){}}"
    "window.addEventListener('resize',function(){"
    "if(rzPend){return;}rzPend=requestAnimationFrame(function(){"
    "rzPend=0;pick();refreshMax();pos=target=curY();});},{passive:true});"
    "window.addEventListener('wheel',function(e){"
    "if(e.ctrlKey){return;}"
    "var near=nearest(e.target);"
    "if(near&&near!==scroller){return;}"
    "e.preventDefault();"
    "var d=(e.deltaMode===1)?e.deltaY*34:e.deltaY;"
    "target=clamp(target+d,0,maxY());start();},{passive:false});"
    "document.addEventListener('keydown',function(e){"
    "var t=e.target,n=t&&t.tagName?t.tagName.toUpperCase():'';"
    "if(n==='INPUT'||n==='TEXTAREA'||(t&&t.isContentEditable)){return;}"
    "var k=e.key,h=(scroller?scroller.clientHeight:window.innerHeight)*0.85,s=null;"
    "if(k==='ArrowDown'){s=120;}else if(k==='ArrowUp'){s=-120;}"
    "else if(k==='PageDown'){s=h;}else if(k==='PageUp'){s=-h;}"
    "else if(k===' '){s=e.shiftKey?-h:h;}"
    "else if(k==='Home'){e.preventDefault();target=0;start();return;}"
    "else if(k==='End'){e.preventDefault();target=maxY();start();return;}"
    "if(s!==null){e.preventDefault();target=clamp(target+s,0,maxY());start();}"
    "},{passive:false});"
    "var host=scroller||window;"
    "host.addEventListener('scroll',sync,{passive:true});"
    "if(host!==window){window.addEventListener('scroll',sync,{passive:true});}"
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
                     view.page().runJavaScript(_NO_COPY_JS),
                     view.page().runJavaScript(_SMOOTH_SCROLL_JS)))
    return view