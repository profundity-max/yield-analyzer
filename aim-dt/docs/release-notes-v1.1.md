# AIM D-T V1.1 Release Notes

Release date: 2026-10-14

## Summary

V1.1 is the first activated internal-network pilot release. It is deployed from the isolated worktree on the existing quality-server Mac.

## Changes

- HTTPS entry activated on `https://192.168.60.9:8502`.
- Nginx routes `/api` to the loopback FastAPI service on `127.0.0.1:8503`.
- launchd services `com.aim-dt.api` and `com.aim-dt.worker` are installed and running.
- Worker no longer creates database tables; Alembic remains the only schema owner.
- Worker waits for the migrated `users` table before claiming jobs, preventing the startup race found during activation.
- Isolated runtime storage, secret key and initial admin credential are configured outside Git.
- Initial admin login forces a password change.

## Activation Verification

- `https://192.168.60.9:8502/api/v1/health` returns version `1.1.0`.
- HTTPS admin login returns 200.
- `must_change_password` is true on first login.
- Alembic revision is `80de9f2d529e`.
- API and worker launchd processes are running.
- Backend tests: 6 passed.
- Frontend tests: 2 passed.
- Production frontend build: successful.

## Known Limitations

The provided sample still lacks Passing units, genuine retest sequences and complete Tester/Cell mapping. It is suitable for functional testing, not formal yield sign-off.
