"""
VDX OpenAgent — entry point
=======================
Runs the API and (if built) the web UI on http://127.0.0.1:8741.

    python3 main.py            # serve
    python3 main.py --open     # serve and open the browser
    python3 main.py --port N   # custom port
"""

from __future__ import annotations

import argparse
import threading
import time
import urllib.request
import webbrowser


def _wait_and_open(url: str) -> None:
    """Open *url* in the browser once the server answers."""
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    webbrowser.open(url)


def main() -> None:
    """Run the VDX OpenAgent API (+ bundled web UI)."""
    import uvicorn

    parser = argparse.ArgumentParser(description="VDX OpenAgent — local macOS assistant")
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--open", action="store_true", help="open the UI in the browser")
    args = parser.parse_args()

    if args.open:
        threading.Thread(target=_wait_and_open, args=(f"http://{args.host}:{args.port}",), daemon=True).start()

    uvicorn.run("api.server:app", host=args.host, port=args.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
