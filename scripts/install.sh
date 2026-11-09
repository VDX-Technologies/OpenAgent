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
rm -rf "$APP" "$HOME/Applications/VDX Agent.app"  # fresh install (also drops the pre-rename bundle)
# api/bundle.py builds the bundle; the app keeps it up to date by itself after every update
.venv/bin/python -m api.bundle
tccutil reset Microphone ai.vdx.agent.app >/dev/null 2>&1 || true  # forget a silent deny from older builds

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
