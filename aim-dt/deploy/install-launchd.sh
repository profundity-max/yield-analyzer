#!/bin/bash
set -euo pipefail
ROOT="${AIM_DT_ROOT:-/Users/quality/yield-analyzer/aim-dt}"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS" "$HOME/Library/Logs"
cp "$ROOT/deploy/com.aim-dt.api.plist" "$LAUNCH_AGENTS/com.aim-dt.api.plist"
cp "$ROOT/deploy/com.aim-dt.worker.plist" "$LAUNCH_AGENTS/com.aim-dt.worker.plist"
launchctl bootout "gui/$(id -u)/com.aim-dt.api" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.aim-dt.worker" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/com.aim-dt.api.plist"
launchctl bootstrap "gui/$(id -u)" "$LAUNCH_AGENTS/com.aim-dt.worker.plist"
echo "Installed com.aim-dt.api and com.aim-dt.worker"
