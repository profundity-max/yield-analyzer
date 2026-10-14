#!/bin/bash
set -euo pipefail
ROOT="${AIM_DT_ROOT:-/Users/quality/yield-analyzer/aim-dt}"
cd "$ROOT/backend"
set -a
[ -f "$ROOT/.env" ] && source "$ROOT/.env"
set +a
exec "$ROOT/backend/.venv/bin/python" -m app.worker
