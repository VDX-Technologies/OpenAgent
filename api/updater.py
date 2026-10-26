"""
Self-update from the git remote
===============================
The app is installed from a git clone, so a release is a ``vX.Y.Z`` tag on
``origin``. ``check()`` compares the newest tag with ``__version__``;
``apply()`` checks it out, reinstalls dependencies and rebuilds the UI.
"""

from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

from api import __version__

ROOT = Path(__file__).resolve().parent.parent
_state = {"running": False, "done": False, "error": ""}


def _v(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", tag)[:3])


def _run(*cmd: str, cwd: Path = ROOT, timeout: int = 600) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-400:] or f"{cmd[0]} failed")
    return r.stdout


def latest_tag() -> str | None:
    """Newest ``vX.Y.Z`` tag on origin, or None if there is no remote/tag."""
    out = _run("git", "ls-remote", "--tags", "--refs", "origin", timeout=20)
    tags = [l.rsplit("/", 1)[-1] for l in out.splitlines()]
    tags = [t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", t)]
    return max(tags, key=_v) if tags else None


def check() -> dict:
    """Current version, latest release, and whether an update is running/finished."""
    info = {"current": __version__, "latest": None, "available": False, **_state}
    try:
        tag = latest_tag()
    except Exception as e:  # no git, no remote, offline
        info["check_error"] = str(e)
        return info
    if tag:
        info["latest"] = tag.lstrip("v")
        info["available"] = _v(tag) > _v(__version__)
    return info


def _apply(tag: str) -> None:
    try:
        _run("git", "fetch", "--tags", "origin", timeout=120)
        _run("git", "checkout", "--quiet", tag)
        _run(str(ROOT / ".venv" / "bin" / "pip"), "install", "-q", "-r", "requirements.txt")
        _run("pnpm", "install", "--silent", cwd=ROOT / "ui")
        _run("pnpm", "build", cwd=ROOT / "ui")
        _state["done"] = True
    except Exception as e:
        _state["error"] = str(e)
    finally:
        _state["running"] = False


def apply() -> dict:
    """Start installing the latest release in the background."""
    if _state["running"]:
        return check()
    tag = latest_tag()
    if not tag or _v(tag) <= _v(__version__):
        return check()
    _state.update(running=True, done=False, error="")
    threading.Thread(target=_apply, args=(tag,), name="vdx-update", daemon=True).start()
    return check()
