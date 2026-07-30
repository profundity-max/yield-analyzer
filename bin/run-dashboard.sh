#!/bin/bash
# Streamlit Dashboard 启动脚本

set -e
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="/Users/tmnb123"
export LANG="en_US.UTF-8"
export PYTHONUNBUFFERED=1

# 提升文件描述符上限（launchd 限制是 65536，bash 也要同步）
ulimit -n 65536 2>/dev/null || true

cd /Users/tmnb123/Projects/yield-analyzer
exec ./.venv/bin/streamlit run src/dashboard/app.py \
    --server.headless true \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --browser.gatherUsageStats false
