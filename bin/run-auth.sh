#!/bin/bash
# auth_subhandler 启动脚本 (被 launchd 调用)
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/tmnb123"
cd /Users/tmnb123/Projects/yield-analyzer
exec ./.venv/bin/python auth_subhandler.py
