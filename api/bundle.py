"""
macOS app bundle (~/Applications/VDX OpenAgent.app)
==================================================
Builds the bundle the first time (``scripts/install.sh``) and keeps it in step
with the code afterwards: the app calls :func:`refresh` on every start and the
updater after installing a release, so a release that changes the bundle
(Info.plist permissions, the launcher, the icon, the Python version) never
needs a reinstall.

The bundle runs a copy of the venv's Python interpreter (``Contents/MacOS/
vdx-python``) through a small compiled launcher (``scripts/launcher.c``), so
macOS sees the process as VDX OpenAgent: its Dock name and icon, and its own
privacy permissions (microphone, calendars…).

Updating in place while the app runs is safe: the running process is the
Python copy, which is only ever *replaced* (new file, then rename), never
rewritten. A rebuild happens only when the expected bundle differs from the
installed one (a hash is stored in the bundle); note that macOS may then ask
again for permissions it had granted, since they are tied to the signature.

    python -m api.bundle            # create or update the bundle
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
APP = Path.home() / "Applications" / "VDX OpenAgent.app"
EXE_NAME = "VDX OpenAgent"
MARKER = "vdx-bundle.json"
ICON_SRC = ROOT / "ui" / "static" / "brand" / "vdx-dock.png"
LAUNCHER_SRC = ROOT / "scripts" / "launcher.c"

INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>VDX OpenAgent</string>
  <key>CFBundleDisplayName</key><string>VDX OpenAgent</string>
  <key>CFBundleIdentifier</key><string>ai.vdx.agent.app</string>
  <key>CFBundleExecutable</key><string>VDX OpenAgent</string>
  <key>CFBundleIconFile</key><string>vdx</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppleEventsUsageDescription</key><string>VDX controls Calendar, Reminders and Mail on your behalf.</string>
  <key>NSMicrophoneUsageDescription</key><string>VDX listens when you press the mic button, to turn your voice into text on this Mac.</string>
  <key>NSCalendarsUsageDescription</key><string>VDX reads and creates your calendar events when you ask it to.</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>VDX reads and creates your calendar events when you ask it to.</string>
  <key>NSRemindersUsageDescription</key><string>VDX reads and creates your reminders when you ask it to.</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>VDX reads and creates your reminders when you ask it to.</string>
</dict></plist>
"""

LAUNCH_SH = """#!/bin/bash
# Fallback launcher (used when the compiled one can't be built). Starts Ollama if it is not running.
# Launch errors go to ~/Library/Logs/VDX.log (readable even if Desktop access is denied).
exec >>"$HOME/Library/Logs/VDX.log" 2>&1
echo "--- $(date) launching"
pgrep -x ollama >/dev/null || open -ga Ollama 2>/dev/null || (nohup ollama serve >/dev/null 2>&1 &)
cd "{root}" || {{ echo "cannot access {root} (grant Files & Folders access)"; exit 1; }}
exec "{root}/.venv/bin/python" desktop.py
"""

# Run with the venv's interpreter: where the real Python lives (framework builds ship a Python.app
# whose binary must be the one copied), its home, and the venv's site-packages.
_PY_INFO = r"""
import os, sys, sysconfig
app = os.path.join(sys.base_prefix, "Resources/Python.app/Contents/MacOS/Python")
exe = app if os.path.exists(app) else os.path.realpath(sys._base_executable)
print(exe); print(sys.base_prefix); print(sysconfig.get_paths()["purelib"])
"""


def _run(*cmd: str, env: dict[str, str] | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, env=env)


def _python() -> tuple[str, str, str]:
    venv = ROOT / ".venv" / "bin" / "python"
    out = _run(str(venv if venv.exists() else sys.executable), "-c", _PY_INFO).stdout.split("\n")
    if len(out) < 3 or not out[0]:
        raise RuntimeError("could not inspect the project's Python (.venv)")
    return out[0], out[1], out[2]


def _file_sig(p: Path) -> str:
    try:
        st = p.stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return "missing"


def _spec() -> dict[str, str]:
    """Everything the bundle is built from; its hash tells whether the installed bundle is current.

    The app version is deliberately not part of it: a release that doesn't change the bundle must
    not re-sign it, or macOS could ask again for permissions it already granted.
    """
    py_bin, py_home, py_site = _python()
    return {
        "root": str(ROOT),
        "plist": INFO_PLIST,
        "launch_sh": LAUNCH_SH.format(root=ROOT),
        "launcher": hashlib.sha256(LAUNCHER_SRC.read_bytes()).hexdigest() if LAUNCHER_SRC.exists() else "",
        "icon": hashlib.sha256(ICON_SRC.read_bytes()).hexdigest() if ICON_SRC.exists() else "",
        "py_bin": py_bin, "py_bin_sig": _file_sig(Path(py_bin)), "py_home": py_home, "py_site": py_site,
    }


def _digest(spec: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def _installed() -> dict[str, str]:
    try:
        return json.loads((APP / "Contents" / "Resources" / MARKER).read_text())
    except (OSError, ValueError):
        return {}


def _same_dir(path: str | None) -> bool:
    """*path* is this project — compared as files: macOS paths are case-insensitive ("desktop" = "Desktop")."""
    try:
        return bool(path) and os.path.samefile(str(path), ROOT)
    except OSError:
        return False


def _owned_by_this_clone() -> bool:
    """The installed bundle launches this project (not another clone of it)."""
    root = _installed().get("root")
    if root:
        return _same_dir(root)
    try:  # bundles made before the marker existed: the project path is in launch.sh
        import re

        m = re.search(r'^cd "([^"]+)"', (APP / "Contents" / "Resources" / "launch.sh").read_text(), re.M)
        return _same_dir(m.group(1) if m else None)
    except OSError:
        return False


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    tmp = path.with_name(f".{path.name}.new")
    tmp.write_text(text, encoding="utf-8")
    tmp.chmod(mode)
    os.replace(tmp, path)


def _icon(res: Path, notes: list[str]) -> None:
    if not ICON_SRC.exists():
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "vdx.iconset"
        iconset.mkdir()
        for s in (16, 32, 128, 256, 512):
            _run("sips", "-z", str(s), str(s), str(ICON_SRC), "--out", str(iconset / f"icon_{s}x{s}.png"))
            _run("sips", "-z", str(s * 2), str(s * 2), str(ICON_SRC), "--out", str(iconset / f"icon_{s}x{s}@2x.png"))
        out = Path(tmp) / "vdx.icns"
        if _run("iconutil", "-c", "icns", str(iconset), "-o", str(out)).returncode == 0:
            shutil.move(str(out), res / "vdx.icns")
        else:
            notes.append("couldn't build the app icon")


def _python_copy(macos: Path, py_bin: str, py_home: str, notes: list[str]) -> bool:
    """Copy and sign the interpreter next to the launcher; the running copy is replaced, never rewritten."""
    tmp = macos / ".vdx-python.new"
    try:
        shutil.copy2(py_bin, tmp)
    except OSError:
        notes.append(f"couldn't copy Python ({py_bin})")
        return False
    # a copied interpreter keeps a signature valid only in its original place, and macOS kills it
    # ("Killed: 9"): sign the copy for this Mac (ad hoc, like the rest of the bundle)
    if _run("codesign", "--force", "--sign", "-", str(tmp)).returncode:
        tmp.unlink(missing_ok=True)
        notes.append("couldn't sign the copy of Python (codesign failed)")
        return False
    # some Pythons (e.g. uv's) load their library relative to themselves and can't run from the bundle
    env = {**os.environ, "PYTHONHOME": py_home}
    if _run(str(tmp), "-c", "import encodings, ssl", env=env).returncode:
        tmp.unlink(missing_ok=True)
        notes.append(f"this Python ({py_bin}) can't run from inside the app bundle")
        return False
    os.replace(tmp, macos / "vdx-python")
    return True


def _launcher(macos: Path, spec: dict[str, str], notes: list[str]) -> bool:
    tmp = macos / ".launcher.new"
    defines = [f'-DVDX_ROOT="{spec["root"]}"', f'-DVDX_HOME="{spec["py_home"]}"', f'-DVDX_SITE="{spec["py_site"]}"']
    try:
        r = _run("cc", "-O2", "-o", str(tmp), str(LAUNCHER_SRC), *defines)
    except FileNotFoundError:
        r = None
    if r is None or r.returncode:
        tmp.unlink(missing_ok=True)
        notes.append("couldn't compile the app launcher (run: xcode-select --install)")
        return False
    exe = macos / EXE_NAME
    if exe.is_symlink():
        exe.unlink()
    os.replace(tmp, exe)
    return True


def build(spec: dict[str, str] | None = None) -> list[str]:
    """Create or update the bundle in place; returns warnings (empty when everything worked)."""
    spec = spec or _spec()
    old = _installed()
    contents, macos = APP / "Contents", APP / "Contents" / "MacOS"
    res = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    _write(contents / "Info.plist", spec["plist"])
    _write(res / "launch.sh", spec["launch_sh"], 0o755)
    if old.get("icon") != spec["icon"] or not (res / "vdx.icns").exists():
        _icon(res, notes)

    python_changed = any(old.get(k) != spec[k] for k in ("py_bin", "py_bin_sig", "py_home"))
    have_python = (macos / "vdx-python").exists()
    if python_changed or not have_python:
        have_python = _python_copy(macos, spec["py_bin"], spec["py_home"], notes) or (have_python and not python_changed)
    launcher_changed = python_changed or any(old.get(k) != spec[k] for k in ("launcher", "py_site", "root"))
    exe = macos / EXE_NAME
    have_launcher = exe.exists() and not exe.is_symlink()
    if have_python and (launcher_changed or not have_launcher):
        have_launcher = _launcher(macos, spec, notes)
    if not (have_python and have_launcher):
        # fallback: the app still works, but the Dock shows Python and voice input can't use the microphone
        (macos / "vdx-python").unlink(missing_ok=True)
        exe.unlink(missing_ok=True)
        exe.symlink_to("../Resources/launch.sh")
        notes.append("using the shell launcher: the Dock shows Python and the microphone can't be used")

    # the marker is sealed by the signature, so it is written before signing
    _write(res / MARKER, json.dumps({**{k: v for k, v in spec.items() if k not in ("plist", "launch_sh")},
                                     "hash": _digest(spec)}, indent=1))
    # sign the bundle (the Python copy is already signed: no --deep, so the running copy isn't touched)
    if _run("codesign", "--force", "--sign", "-", str(APP)).returncode:
        notes.append("couldn't sign the app bundle")
    _run("xattr", "-dr", "com.apple.quarantine", str(APP))
    os.utime(APP)
    return notes


def refresh(force: bool = False) -> str:
    """Bring the installed bundle up to date with this code (no-op when it already is).

    Without *force* it only touches a bundle that exists and launches this project.
    """
    if sys.platform != "darwin":
        return "skipped: not macOS"
    if not force and not (APP.exists() and _owned_by_this_clone()):
        return "skipped: no app bundle for this project"
    try:
        spec = _spec()
        if not force and _installed().get("hash") == _digest(spec):
            return "up to date"
        notes = build(spec)
    except Exception as exc:
        logger.warning("Could not update the app bundle: %s", exc, exc_info=True)
        return f"failed: {exc}"
    for n in notes:
        logger.warning("App bundle: %s", n)
    logger.info("App bundle updated (%s)", APP)
    return "updated" + (f" with warnings: {'; '.join(notes)}" if notes else "")


if __name__ == "__main__":
    print(f"▸ App bundle → {APP}")
    result = refresh(force=True)
    print(f"  {result}")
    sys.exit(1 if result.startswith("failed") else 0)
