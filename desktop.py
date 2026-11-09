"""
VDX OpenAgent — desktop app
===========================
Opens VDX in its own native macOS window (WebKit via pywebview), like a
regular app. The agent backend runs inside the same process — unless a
background instance (launchd / ``main.py``) is already running, in which
case the windows attach to it.

* Closing the window keeps VDX running in the menu bar, so automations keep
  firing; quit from the menu bar icon (or ⌘Q).
* ⌥Space anywhere opens a small quick-ask panel.

    python3 desktop.py
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

HOST, PORT = "127.0.0.1", 8741
URL = f"http://{HOST}:{PORT}"
ICON = Path(__file__).parent / "ui" / "static" / "brand" / "vdx-dock.png"  # padded like a macOS app icon
MARK = Path(__file__).parent / "ui" / "static" / "brand" / "vdx-mark.png"
QUICK_W, QUICK_H = 680, 440
logger = logging.getLogger("vdx.desktop")


def _healthy() -> bool:
    try:
        urllib.request.urlopen(f"{URL}/api/health", timeout=1)
        return True
    except Exception:
        return False


def _port_busy() -> bool:
    with socket.socket() as s:
        return s.connect_ex((HOST, PORT)) == 0


def _start_backend() -> None:
    """Run the API + UI server on a daemon thread."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config("api.server:app", host=HOST, port=PORT, log_level="warning"))
    threading.Thread(target=server.run, name="vdx-api", daemon=True).start()


def _brand_process() -> None:
    """Show "VDX" and the VDX icon in the Dock/menu bar instead of "Python"."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle

        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = info["CFBundleDisplayName"] = "VDX"
        if ICON.exists():
            NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(ICON)))
    except Exception:
        pass


_SPLASH = """<!doctype html><html><body style="margin:0;height:100vh;display:flex;flex-direction:column;
align-items:center;justify-content:center;background:#07080a;color:#a3a9b2;font:13px -apple-system,system-ui">
<div style="font-weight:700;letter-spacing:.06em;font-size:34px;color:#fff;margin-bottom:10px">VDX</div>
<div style="animation:p 1.4s ease-in-out infinite">Starting…</div>
<style>@keyframes p{50%{opacity:.35}}</style></body></html>"""


class App:
    """The windows, the menu bar item and the global shortcut."""

    def __init__(self) -> None:
        import webview

        self.webview = webview
        self.main: Any = None
        self.quick: Any = None
        self.ready = False
        self._keep: list[Any] = []  # ObjC / ctypes objects that must stay alive

    # ── windows ──────────────────────────────────────────────────────

    def create_main(self, path: str = "/?desktop") -> Any:
        w = self.webview.create_window(
            "VDX", url=f"{URL}{path}" if self.ready else None, html=None if self.ready else _SPLASH,
            width=1280, height=820, min_size=(900, 600), background_color="#07080A", text_select=True,
        )
        w.events.shown += lambda: _hide_titlebar(w)
        w.events.closed += self._main_closed
        self.main = w
        return w

    def _main_closed(self) -> None:
        self.main = None  # VDX keeps running in the menu bar

    def open_main(self, cid: Any = None) -> None:
        path = f"/?c={int(cid)}" if cid else "/"
        if self.main is None:
            self.create_main(path)
        else:
            if cid:
                self.main.load_url(f"{URL}{path}")
            self.main.show()
            self.main.restore()
        _activate()

    def toggle_quick(self) -> None:
        if not self.ready or self.quick is None:
            return
        if getattr(self, "_quick_visible", False):
            self.hide_quick()
            return
        try:
            screen = self.webview.screens[0]
            self.quick.move(int((screen.width - QUICK_W) / 2), int(screen.height * 0.18))
        except Exception:
            pass
        self.quick.show()
        self._quick_visible = True
        _activate()
        self.quick.evaluate_js("window.dispatchEvent(new Event('focus'))")

    def hide_quick(self) -> None:
        if self.quick is not None:
            self.quick.hide()
        self._quick_visible = False

    def quit(self) -> None:
        try:
            from AppKit import NSApplication

            NSApplication.sharedApplication().terminate_(None)
        except Exception:
            for w in list(self.webview.windows):
                w.destroy()

    # ── startup ──────────────────────────────────────────────────────

    def on_start(self) -> None:
        """Runs once the GUI loop is up: wait for the backend, then load the real UI."""
        for _ in range(120):
            if _healthy():
                break
            time.sleep(0.25)
        else:
            if self.main:
                self.main.load_html(_SPLASH.replace("Starting…", "Could not start the agent — see data/vdx.log"))
            return
        self.ready = True
        if self.main:
            self.main.load_url(f"{URL}/?desktop")
        if self.quick:
            self.quick.load_url(f"{URL}/quick")
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(self._setup_native)
        except Exception:
            logger.warning("Menu bar / shortcut unavailable", exc_info=True)

    def _setup_native(self) -> None:
        _menu_bar(self)
        if not _carbon_hotkey(self):
            logger.warning("⌥Space shortcut unavailable")


class _JsApi:
    """Called by the quick-ask page (window.pywebview.api.*)."""

    def __init__(self, app: App) -> None:
        self._app = app

    def hide_quick(self) -> None:
        self._app.hide_quick()

    def open_main(self, cid: Any = None) -> None:
        self._app.hide_quick()
        threading.Thread(target=self._app.open_main, args=(cid,), daemon=True).start()


def _activate() -> None:
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def _menu_bar(app: App) -> None:
    """A VDX icon in the menu bar: open, quick ask, quit."""
    try:
        from AppKit import NSImage, NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
        from Foundation import NSObject, NSMakeSize
    except ImportError:
        return

    class VDXMenuTarget(NSObject):
        def openMain_(self, _sender: Any) -> None:
            threading.Thread(target=app.open_main, daemon=True).start()

        def quickAsk_(self, _sender: Any) -> None:
            threading.Thread(target=app.toggle_quick, daemon=True).start()

        def quitApp_(self, _sender: Any) -> None:
            app.quit()

    target = VDXMenuTarget.alloc().init()
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    button = item.button()
    if MARK.exists():
        img = NSImage.alloc().initWithContentsOfFile_(str(MARK))
        img.setSize_(NSMakeSize(18, 18))
        button.setImage_(img)
    else:
        button.setTitle_("VDX")
    button.setToolTip_("VDX OpenAgent")
    menu = NSMenu.alloc().init()
    for title, sel, key in (("Open VDX", "openMain:", ""), ("Quick ask   ⌥Space", "quickAsk:", ""), (None, None, None),
                            ("Quit VDX", "quitApp:", "q")):
        if title is None:
            menu.addItem_(NSMenuItem.separatorItem())
            continue
        mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key)
        mi.setTarget_(target)
        menu.addItem_(mi)
    item.setMenu_(menu)
    app._keep += [target, item, menu]


def _carbon_hotkey(app: App) -> bool:
    """Register ⌥Space system-wide (Carbon hot keys need no Accessibility permission)."""
    import ctypes
    import ctypes.util

    try:
        carbon = ctypes.CDLL(ctypes.util.find_library("Carbon") or "/System/Library/Frameworks/Carbon.framework/Carbon")
    except OSError:
        return False

    def fourcc(s: str) -> int:
        return int.from_bytes(s.encode(), "big")

    class EventTypeSpec(ctypes.Structure):
        _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

    class EventHotKeyID(ctypes.Structure):
        _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

    handler_t = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

    def on_hotkey(_call: Any, _event: Any, _data: Any) -> int:
        threading.Thread(target=app.toggle_quick, daemon=True).start()
        return 0

    handler = handler_t(on_hotkey)
    carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
    carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, handler_t, ctypes.c_uint32, ctypes.POINTER(EventTypeSpec),
                                           ctypes.c_void_p, ctypes.c_void_p]
    carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                           ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    target = carbon.GetApplicationEventTarget()
    spec = EventTypeSpec(fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
    if carbon.InstallEventHandler(target, handler, 1, ctypes.byref(spec), None, None) != 0:
        return False
    ref = ctypes.c_void_p()
    option_key, space = 0x0800, 49
    if carbon.RegisterEventHotKey(space, option_key, EventHotKeyID(fourcc("VDXq"), 1), target, 0, ctypes.byref(ref)) != 0:
        return False
    app._keep += [handler, spec, ref]
    return True


def main() -> None:
    """Launch the native VDX window (plus menu bar item and quick-ask panel)."""
    import webview

    if not _healthy() and not _port_busy():
        _start_backend()

    _brand_process()
    app = App()
    app.create_main()
    app.quick = webview.create_window(
        "VDX Quick Ask", html=_SPLASH, width=QUICK_W, height=QUICK_H, frameless=True, on_top=True, hidden=True,
        easy_drag=False, background_color="#171717", js_api=_JsApi(app),
    )
    # pywebview defaults to private mode, which forgets cookies/localStorage on quit
    # (the intro, consent and model choice would come back on every launch)
    data = Path.home() / ".vdx-agent" / "webview"
    data.mkdir(parents=True, exist_ok=True)
    webview.start(app.on_start, private_mode=False, storage_path=str(data))


def _hide_titlebar(window: Any) -> None:
    """Drop the "VDX" title bar but keep the traffic lights over the content (macOS)."""
    try:
        from PyObjCTools import AppHelper

        def apply() -> None:
            ns = window.native
            ns = ns.window() if hasattr(ns, "window") and callable(ns.window) else ns
            ns.setTitlebarAppearsTransparent_(True)
            ns.setTitleVisibility_(1)  # NSWindowTitleHidden
            ns.setStyleMask_(ns.styleMask() | (1 << 15))  # NSWindowStyleMaskFullSizeContentView
            ns.setMovableByWindowBackground_(True)

        AppHelper.callAfter(apply)
    except Exception:  # non-Cocoa backend: keep the default title bar
        pass


if __name__ == "__main__":
    main()
