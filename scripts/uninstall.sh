#!/usr/bin/env bash
# Remove the VDX Agent app bundle and login item (keeps your data and .env).
PLIST="$HOME/Library/LaunchAgents/ai.vdx.agent.plist"
[ -f "$PLIST" ] && launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"
rm -rf "$HOME/Applications/VDX Agent.app"
pkill -f "vdx-agent.*(main|desktop).py" 2>/dev/null || true
echo "✓ VDX Agent removed (data/ and .env kept)"
