#!/usr/bin/env bash
# Remove the VDX OpenAgent app bundle and login item (keeps your data and .env).
PLIST="$HOME/Library/LaunchAgents/ai.vdx.agent.plist"
[ -f "$PLIST" ] && launchctl unload "$PLIST" 2>/dev/null; rm -f "$PLIST"
rm -rf "$HOME/Applications/VDX OpenAgent.app" "$HOME/Applications/VDX Agent.app"
pkill -f "vdx-agent.*(main|desktop).py" 2>/dev/null || true
echo "✓ VDX OpenAgent removed (data/ and .env kept)"
