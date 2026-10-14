# AIM D-T V1.0 Release Notes

Release date: 2026-10-14

## Highlights

- Added an isolated AIM D-T web application under `aim-dt/`.
- Added XLSX/CSV ingestion, USL/LSL extraction, five-point rule defaults, rolling de-duplication and background processing.
- Added first-pass, retest-pass, final-pass and Error/NG calculations with a fixed 08:00 production-day cutoff.
- Added the PPT-equivalent overview, hourly yield, Pareto, Cell, Tester, distribution and event-detail views.
- Added PNG chart downloads plus summary XLSX and event CSV exports.
- Added admin/analyst/viewer roles, Argon2id passwords, server-side sessions, CSRF protection and audit logs.
- Added HTTPS Nginx configuration, launchd API/worker files and an internal certificate generator.

## Verification

- Backend: 6 passed.
- Frontend: 2 passed.
- Production frontend build: successful.
- Sample workbook: 182 raw rows -> 91 de-duplicated events / 90 SN; average processing time 8.99 ms.
- 1,000,000-row CSV benchmark: 16.05 s parse/Parquet, 12.08 s analysis.
- 5,000,000-row CSV benchmark: 82.49 s parse/Parquet, 61.45 s analysis.
- Real API + worker + Chrome flow: upload -> ready -> analysis -> summary -> exports.

## Known Inputs Required For Business Sign-off

The provided sample has no passing units, no true retest sequence and incomplete Tester/Cell mapping. Functionality is verified, but formal yield sign-off remains blocked until production data provides those fields.
