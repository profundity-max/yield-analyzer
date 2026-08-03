# CLAUDE.md — yield-analyzer

This file provides guidance to AI agents working in this repository.

## Agent skills

### Issue tracker

GitHub Issues via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: `CONTEXT.md` at root + `docs/adr/`. See `docs/agents/domain.md`.

---

## Quick start

```bash
python3 run.py              # Start dashboard
python3 run.py import        # Import Excel/CSV data
python3 run.py judge         # Run FAI judging
python3 run.py report export # Export daily yield report
```

## Key modules

- `src/importer/` — Excel/CSV → Parquet
- `src/judge/` — FAI measurement → OK/NG verdict
- `src/aggregator/` — DuckDB SQL aggregation (yield, top defects, regression)
- `src/dashboard/` — Streamlit web UI
- `src/spec_manager/` — Spec version management

## Data flow

```
Excel/CSV → importer → raw.parquet → judge → judged.parquet → DuckDB SQL → dashboard/export
```
