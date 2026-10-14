#!/bin/bash
set -euo pipefail
ROOT="${AIM_DT_ROOT:-/Users/quality/yield-analyzer/aim-dt}"
PYTHON="${AIM_DT_PYTHON:-python3.12}"
PNPM="${AIM_DT_PNPM:-pnpm}"
cd "$ROOT/backend"
"$PYTHON" -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[test]'
if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created $ROOT/.env; review secrets and paths before production."
fi
cd "$ROOT/frontend"
"$PNPM" install
"$PNPM" build
cd "$ROOT/backend"
set -a
source "$ROOT/.env"
set +a
.venv/bin/alembic -c "$ROOT/backend/alembic.ini" upgrade head
echo "AIM D-T bootstrap complete."
