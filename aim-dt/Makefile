.PHONY: backend-install backend-test backend-api backend-worker frontend-install frontend-test frontend-build verify

backend-install:
	cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e '.[test]'

backend-test:
	cd backend && .venv/bin/pytest -q

backend-api:
	cd backend && AIM_COOKIE_SECURE=false .venv/bin/uvicorn app.main:app --reload --port 8503

backend-worker:
	cd backend && AIM_COOKIE_SECURE=false .venv/bin/python -m app.worker

frontend-install:
	cd frontend && pnpm install

frontend-test:
	cd frontend && pnpm test

frontend-build:
	cd frontend && pnpm build

verify: backend-test frontend-test frontend-build
