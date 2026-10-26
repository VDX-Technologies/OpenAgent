"""
VDX OpenAgent — desktop app
=======================
Opens VDX in its own native macOS window (WebKit via pywebview), like a
regular app. The agent backend runs inside the same process and stops when
the window closes — unless a background instance (launchd / ``main.py``) is
already running, in which case the window simply attaches to it.

    python3 desktop.py
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from pathlib import Path

HOST, PORT = "127.0.0.1", 8741
URL = f"http://{HOST}:{PORT}"
ICON = Path(__file__).parent / "ui" / "static" / "brand" / "vdx-dock.png"  # padded like a macOS app icon


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
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initWithContentsOfFile_(str(ICON))
            )
    except Exception:
        pass


def _wait_ready(window) -> None:
    """Swap the splash for the real UI once the backend answers."""
    for _ in range(120):
        if _healthy():
            window.load_url(f"{URL}/?desktop")
            return
        time.sleep(0.25)
    window.load_html(_SPLASH.replace("Starting…", "Could not start the agent — see data/vdx.log"))


_SPLASH = """<!doctype html><html><body style="margin:0;height:100vh;display:flex;flex-direction:column;
align-items:center;justify-content:center;background:#07080a;color:#a3a9b2;font:13px -apple-system,system-ui">
<div style="font-weight:700;letter-spacing:.06em;font-size:34px;color:#fff;margin-bottom:10px">VDX</div>
<div style="animation:p 1.4s ease-in-out infinite">Starting…</div>
<style>@keyframes p{50%{opacity:.35}}</style></body></html>"""


def main() -> None:
    """Launch the native VDX window."""
    import webview

    if not _healthy() and not _port_busy():
        _start_backend()

    _brand_process()
    window = webview.create_window(
        "VDX",
        html=_SPLASH,
        width=1280,
        height=820,
        min_size=(900, 600),
        background_color="#07080A",
        text_select=True,
    )
    window.events.shown += lambda: _hide_titlebar(window)
    webview.start(_wait_ready, window)


def _hide_titlebar(window) -> None:
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
