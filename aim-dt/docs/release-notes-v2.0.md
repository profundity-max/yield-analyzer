# AIM D-T V2.0 Release Notes

Release date: 2026-10-14

## Highlights

- Uploading now automatically parses the file, creates an analysis and displays the chart workspace in the Analysis Center.
- The default standard Spec enables T1-T2, T1-T3, T1-T4 and T1-T5 with default LSL/USL of 0/2.
- Embedded USL/LSL values from the upload take priority over the system default.
- T1-T6 and other detected points remain visible but disabled unless explicitly enabled.
- Spec editing is now a version selector plus an enable/LSL/USL table; JSON editing was removed.
- Mapping editing now shows current mappings and unmatched source combinations with event counts.
- Mapping targets use Cell/Tester/QPL category dropdowns; JSON editing was removed.
- Cell-1..Cell-6, Tester 01..10 and QPL1..QPL3 are seeded and can be maintained.
- Saving a Spec, Mapping or enabled-point change creates a new active version and reruns the current analysis.
- Analysis Center keeps old result snapshots for traceability.

## Data Migration

- Added `categories` and `analysis_batches`.
- Backfilled existing analysis-to-batch relationships.
- Retired the previous five-point active Spec.
- Added a new active four-point Spec while preserving the old row and all historical summaries.
- Preserved the existing Slot-1 mapping rule unchanged.

## Verification

- Sample workbook with four default points: 90 inputs, 12 final passes, 78 final NG.
- Pareto counts: T1-T2 26, T1-T3 46, T1-T4 64, T1-T5 67.
- Backend tests and frontend build passed.
- Migration tested against a copy of the active V1.1 SQLite database.
- Browser flow tested: login -> upload -> automatic analysis -> inline charts -> Spec/Mapping editors.

## Known Limitations

The provided sample still lacks Pass and genuine retest records and a complete Slot mapping. General charts can be tested immediately; formal yield sign-off still requires complete production data and mappings.
