#!/usr/bin/env bash
# VDX OpenAgent — one-shot installer (macOS)
# Creates a venv, builds the web UI, and installs the native "VDX OpenAgent.app"
# window in ~/Applications. Pass --autostart to also launch VDX at login (launchd).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/VDX OpenAgent.app"
PLIST="$HOME/Library/LaunchAgents/ai.vdx.agent.plist"
PORT=8741
cd "$ROOT"

echo "▸ Python environment"
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env

echo "▸ Web UI"
command -v pnpm >/dev/null || { echo "pnpm not found (npm i -g pnpm)"; exit 1; }
(cd ui && pnpm install --silent && pnpm build >/dev/null)

echo "▸ Ollama"
if ! command -v ollama >/dev/null; then
  echo "  Ollama not found — install it from https://ollama.com/download (then: ollama pull qwen2.5:7b)"
fi

echo "▸ App bundle → $APP"
mkdir -p "$HOME/Applications" data
rm -rf "$APP" "$HOME/Applications/VDX Agent.app"  # also drop the pre-rename bundle
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
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
</dict></plist>
PL
cat > "$APP/Contents/Resources/launch.sh" <<SH
#!/bin/bash
# Native VDX window (pywebview). Starts Ollama if it is not running.
# Launch errors go to ~/Library/Logs/VDX.log (readable even if Desktop access is denied).
exec >>"\$HOME/Library/Logs/VDX.log" 2>&1
echo "--- \$(date) launching"
pgrep -x ollama >/dev/null || open -ga Ollama 2>/dev/null || (nohup ollama serve >/dev/null 2>&1 &)
cd "$ROOT" || { echo "cannot access $ROOT (grant Files & Folders access)"; exit 1; }
exec "$ROOT/.venv/bin/python" desktop.py
SH
chmod +x "$APP/Contents/Resources/launch.sh"
# The app runs a copy of the Python interpreter inside the bundle, through a small compiled launcher
# (scripts/launcher.c): macOS then sees the process as VDX OpenAgent — its name and icon in the Dock, and
# its own microphone permission. launch.sh is the fallback when there is no C compiler.
PY_INFO="$(.venv/bin/python - <<'PY'
import os, sys, sysconfig
app = os.path.join(sys.base_prefix, "Resources/Python.app/Contents/MacOS/Python")  # framework builds
exe = app if os.path.exists(app) else os.path.realpath(sys._base_executable)
print(exe); print(sys.base_prefix); print(sysconfig.get_paths()["purelib"])
PY
)"
PY_BIN="$(sed -n 1p <<<"$PY_INFO")"; PY_HOME="$(sed -n 2p <<<"$PY_INFO")"; PY_SITE="$(sed -n 3p <<<"$PY_INFO")"
# (the copy must run from inside the bundle: some Pythons, e.g. uv's, load their library relative to themselves)
if cp "$PY_BIN" "$APP/Contents/MacOS/vdx-python" 2>/dev/null &&
   PYTHONHOME="$PY_HOME" "$APP/Contents/MacOS/vdx-python" -c "import encodings, ssl" 2>/dev/null &&
   cc -O2 -o "$APP/Contents/MacOS/VDX OpenAgent" scripts/launcher.c \
     -DVDX_ROOT="\"$ROOT\"" -DVDX_HOME="\"$PY_HOME\"" -DVDX_SITE="\"$PY_SITE\"" 2>/dev/null; then
  :
else
  echo "  ! couldn't build the app launcher (no C compiler? run: xcode-select --install, then this script again)"
  echo "    the app still works, but the Dock shows Python and voice input can't use the microphone"
  rm -f "$APP/Contents/MacOS/vdx-python"
  ln -sf ../Resources/launch.sh "$APP/Contents/MacOS/VDX OpenAgent"
fi
ICON_SRC="ui/static/brand/vdx-dock.png"
if [ -f "$ICON_SRC" ]; then
  SET="$(mktemp -d)/vdx.iconset"; mkdir -p "$SET"
  for s in 16 32 128 256 512; do
    sips -z $s $s "$ICON_SRC" --out "$SET/icon_${s}x${s}.png" >/dev/null 2>&1
    sips -z $((s*2)) $((s*2)) "$ICON_SRC" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$SET" -o "$APP/Contents/Resources/vdx.icns" 2>/dev/null || true
fi
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
tccutil reset Microphone ai.vdx.agent.app >/dev/null 2>&1 || true  # forget a silent deny from older builds
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
touch "$APP"

if [[ "${1:-}" == "--autostart" ]]; then
  echo "▸ Launch at login → $PLIST"
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ai.vdx.agent</string>
  <key>ProgramArguments</key><array><string>$ROOT/.venv/bin/python</string><string>main.py</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$ROOT/data/vdx.log</string>
  <key>StandardErrorPath</key><string>$ROOT/data/vdx.log</string>
</dict></plist>
PL
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
fi

echo "✓ Done — open \"VDX OpenAgent\" from ~/Applications (or Spotlight) — it opens its own window."
