#!/bin/bash
set -euo pipefail
ROOT="${AIM_DT_ROOT:-/Users/quality/yield-analyzer/aim-dt}"
cd "$ROOT/backend"
set -a
[ -f "$ROOT/.env" ] && source "$ROOT/.env"
set +a
"$ROOT/backend/.venv/bin/alembic" -c "$ROOT/backend/alembic.ini" upgrade head
exec "$ROOT/backend/.venv/bin/uvicorn" app.main:app \
  --host 127.0.0.1 \
  --port 8503 \
  --proxy-headers \
  --forwarded-allow-ips 127.0.0.1
