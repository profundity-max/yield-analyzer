# AIM D-T V1.0 Architecture

## Runtime topology

```text
Browser
  -> Nginx HTTPS :8502
      -> React static assets
      -> /api/* -> FastAPI 127.0.0.1:8503
FastAPI -> SQLite (users, rules, jobs, audit)
Worker  -> XLSX/CSV parser -> Parquet -> DuckDB in-memory aggregate -> snapshots
```

The API and worker are separate launchd services. One worker processes one heavy job at a time to avoid memory and DuckDB write contention. Jobs use SQLite heartbeat/status fields so an interrupted `running` job can be queued again.

## Data lifecycle

```text
upload -> immutable original file
       -> validated rows
       -> canonical Parquet events
       -> rolling logical merge
       -> analysis run pinned to spec + mapping + batch files
       -> immutable summary.json + events.parquet snapshot
```

Deleting a batch removes only its original file and Parquet. Existing analysis snapshots remain reproducible and traceable.

## Security boundaries

- Password hashes use Argon2id.
- Sessions are opaque random tokens stored as SHA-256 hashes in SQLite.
- Cookies are `HttpOnly`, `Secure` in production, `SameSite=Lax`.
- Mutating requests require the per-session CSRF token.
- Roles: `admin`, `analyst`, `viewer`.
- HTTPS is terminated by Nginx; the API binds only to loopback.

## Failure handling

- Missing columns or malformed USL/LSL abort the batch with an actionable error.
- Missing measurements or sentinel values become `ERROR` and are included in final NG.
- Missing Cell/Tester mapping produces `Unassigned` and a `completed_with_warnings` analysis.
- Original final result and recomputed result mismatches are retained as quality evidence; recomputation is authoritative.
- Analysis cancellation is checked at heartbeat intervals. Failed or cancelled jobs can be retried without changing the original data.
