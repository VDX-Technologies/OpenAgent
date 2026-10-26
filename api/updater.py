"""
Self-update from the git remote
===============================
The app is installed from a git clone, so a release is an ``X.Y.Z`` (or
``vX.Y.Z``) tag on ``origin`` — publishing a GitHub release creates one.

``check()`` compares the newest tag with the installed version and fetches the
release notes. ``apply()`` installs it without ever leaving a half-updated app:

1. the new release is checked out into a temporary worktree and its UI is built
   there, while the running app is untouched (a failure stops here);
2. the clone is force-checked-out to the tag, Python dependencies are synced
   (packages the release dropped are uninstalled) and the new UI build replaces
   the old one; if this step fails the previous version is restored;
3. the temporary worktree is deleted.

``restart()`` then re-executes the process so the new code runs.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from api import __version__

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".update"  # temporary worktree for building a release
CHECK_TTL = 600  # seconds between remote checks
_state = {"running": False, "done": False, "error": "", "step": ""}
_cache: dict = {"at": 0.0, "tag": None, "error": "", "notes": {}}

# Apps opened from Finder get a minimal PATH, without Homebrew / pnpm / nvm.
_EXTRA_PATH = [
    "/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / "Library/pnpm"),
    str(Path.home() / ".local/share/pnpm"), str(Path.home() / ".npm-global/bin"), str(Path.home() / ".volta/bin"),
]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    parts = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(parts + [p for p in _EXTRA_PATH if p not in parts])
    env["GIT_TERMINAL_PROMPT"] = "0"  # never hang on a credentials prompt
    return env


def _v(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", tag)[:3])


def _token() -> str:
    try:
        from config.settings import get_settings
        return get_settings().github.token
    except Exception:
        return ""


def _git(*args: str, cwd: Path = ROOT, timeout: int = 120) -> str:
    """Run git; for a private GitHub repo the token from Settings is sent as auth."""
    auth: list[str] = []
    if (tok := _token()):
        basic = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
        auth = ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
    return _run("git", *auth, *args, cwd=cwd, timeout=timeout)


def _run(*cmd: str, cwd: Path = ROOT, timeout: int = 900) -> str:
    env = _env()
    exe = shutil.which(cmd[0], path=env["PATH"])
    if not exe:
        raise RuntimeError(f"{cmd[0]} not found — install it, then retry")
    r = subprocess.run([exe, *cmd[1:]], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode:
        lines = [l.strip() for l in (r.stderr or r.stdout).splitlines() if l.strip()]
        i = next((i for i, l in enumerate(lines) if re.search(r"\berror\b", l, re.I)), max(len(lines) - 1, 0))
        msg = " ".join(lines[i:i + 3])  # the error line and the detail under it
        raise RuntimeError(msg[:300] or f"{cmd[0]} failed")
    return r.stdout


def latest_tag() -> str | None:
    """Newest release tag on origin, or None if there is no remote/tag."""
    out = _git("ls-remote", "--tags", "--refs", "origin", timeout=20)
    tags = [l.rsplit("/", 1)[-1] for l in out.splitlines()]
    tags = [t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+", t)]
    return max(tags, key=_v) if tags else None


def _repo() -> str | None:
    """``owner/name`` of a GitHub origin."""
    try:
        url = _git("remote", "get-url", "origin", timeout=5).strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def _notes(tag: str) -> str:
    """Release notes of *tag* from GitHub (empty if it has no release or GitHub is unreachable)."""
    if tag in _cache["notes"]:
        return _cache["notes"][tag]
    notes = ""
    if (repo := _repo()):
        try:
            import httpx

            headers = {"Accept": "application/vnd.github+json"}
            if (tok := _token()):
                headers["Authorization"] = f"Bearer {tok}"
            r = httpx.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=headers, timeout=5)
            if r.status_code == 200:
                notes = (r.json().get("body") or "").strip()[:2000]
        except Exception:
            logger.debug("Could not fetch release notes", exc_info=True)
    _cache["notes"][tag] = notes
    return notes


def _latest(force: bool = False) -> str | None:
    """Cached :func:`latest_tag` so polling the status doesn't hit the network."""
    if force or time.time() - _cache["at"] > CHECK_TTL:
        try:
            _cache.update(tag=latest_tag(), error="")
        except Exception as e:  # no git, no remote, offline
            _cache["error"] = str(e)
        _cache["at"] = time.time()
    return _cache["tag"]


def check(force: bool = False) -> dict:
    """Current version, latest release (with notes), and the state of a running/finished update."""
    info = {"current": __version__, "latest": None, "available": False, "notes": "", **_state}
    tag = _latest(force and not _state["running"])
    if _cache["error"]:
        info["check_error"] = _cache["error"]
    if tag:
        info["latest"] = tag.lstrip("v")
        info["available"] = _v(tag) > _v(__version__)
        if info["available"] or _state["done"]:
            info["notes"] = _notes(tag)
    return info


def _req_names(text: str) -> set[str]:
    names = (re.match(r"[A-Za-z0-9_.-]+", l.strip()) for l in text.splitlines() if l.strip() and not l.lstrip().startswith(("#", "-")))
    return {re.sub(r"[-_.]+", "-", m.group(0)).lower() for m in names if m}


def _unused(names: set[str]) -> list[str]:
    """The installed packages among *names* that no other installed package depends on."""
    from importlib import metadata

    norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()  # noqa: E731
    needed: set[str] = set()
    installed: set[str] = set()
    for d in metadata.distributions():
        name = norm(d.metadata["Name"] or "")
        installed.add(name)
        for req in d.requires or []:
            if "extra ==" in req:  # optional extras aren't installed dependencies
                continue
            if (m := re.match(r"[A-Za-z0-9_.-]+", req)) and name not in names:
                needed.add(norm(m.group(0)))
    return sorted(n for n in map(norm, names) if n in installed and n not in needed)


def _drop_worktree() -> None:
    try:
        _git("worktree", "remove", "--force", str(WORK), timeout=60)
    except Exception:
        pass
    shutil.rmtree(WORK, ignore_errors=True)
    try:
        _git("worktree", "prune", timeout=30)
    except Exception:
        pass


def _pip(*args: str) -> None:
    _run(sys.executable, "-m", "pip", *args)


def _apply(tag: str) -> None:
    step = lambda s: _state.update(step=s)  # noqa: E731
    try:
        step("Downloading")
        _git("fetch", "--force", "--tags", "origin")
        _drop_worktree()
        _git("worktree", "add", "--force", "--detach", str(WORK), tag)

        step("Building")
        _run("pnpm", "install", "--frozen-lockfile", "--silent", cwd=WORK / "ui")
        _run("pnpm", "build", cwd=WORK / "ui")

        step("Installing")
        prev = _git("rev-parse", "HEAD").strip()
        old_reqs = (ROOT / "requirements.txt").read_text()
        _git("checkout", "--force", "--quiet", tag)  # also discards local edits to tracked files
        try:
            _pip("install", "-q", "-r", str(ROOT / "requirements.txt"))
        except Exception:
            _git("checkout", "--force", "--quiet", prev)
            try:
                _pip("install", "-q", "-r", str(ROOT / "requirements.txt"))
            except Exception:
                logger.exception("Could not restore dependencies after a failed update")
            raise
        dropped = _unused(_req_names(old_reqs) - _req_names((ROOT / "requirements.txt").read_text()))
        if dropped:
            try:
                _pip("uninstall", "-y", "-q", *dropped)
            except Exception:
                logger.warning("Could not uninstall %s", dropped)

        build, old = ROOT / "ui" / "build", ROOT / "ui" / "build.old"
        shutil.rmtree(old, ignore_errors=True)
        if build.exists():
            build.rename(old)
        shutil.move(str(WORK / "ui" / "build"), str(build))
        shutil.rmtree(old, ignore_errors=True)
        try:  # keep the clone's node_modules in sync for `pnpm dev`; not needed to run the app
            _run("pnpm", "install", "--frozen-lockfile", "--silent", cwd=ROOT / "ui")
        except Exception:
            pass
        _state["done"] = True
    except Exception as e:
        logger.exception("Update to %s failed", tag)
        _state["error"] = f"{_state['step']} failed: {e}"
    finally:
        _drop_worktree()
        _state.update(running=False, step="")


def apply() -> dict:
    """Start installing the latest release in the background."""
    if _state["running"] or _state["done"]:
        return check()
    tag = _latest(force=True)
    if not tag or _v(tag) <= _v(__version__):
        return check()
    _state.update(running=True, done=False, error="", step="Starting")
    threading.Thread(target=_apply, args=(tag,), name="vdx-update", daemon=True).start()
    return check()


def restart() -> dict:
    """Re-execute this process (API server or desktop app) so an installed update takes effect."""
    def go() -> None:
        time.sleep(0.5)  # let the HTTP response go out first
        os.chdir(ROOT)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=go, name="vdx-restart", daemon=True).start()
    return {"restarting": True}
