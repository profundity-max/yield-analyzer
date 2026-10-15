# AIM D-T V3.0 Release Notes

Release date: 2026-10-15

## Highlights

- All uploaded files now merge into one logical Master Data Source.
- Each uploaded file is represented as a stable data module.
- A module can be completely replaced by a new file.
- Current and previous module versions are retained for rollback; older versions retain logs only.
- Spec, Mapping, category, file upload, replacement and revert changes trigger one Master Data Source refresh.
- Analysis history is replaced by module and refresh logs, so repeated snapshots no longer clutter the main page.
- Active Spec and Active Mapping are always used for Master Data Source analysis.
- Distribution charts now use horizontal boxplots ordered top-to-bottom, with mean, minimum, maximum and sample sigma.
- Pass/Fail/Error chart colors are standardized as green/red/yellow.
- Time yield and Cell charts separate Fail from Error.

## Data Model

- Added `master_data_sources`.
- Added `data_modules`.
- Added `refresh_logs`.
- Added module revision, active-version, replacement and file-retention fields to `batches`.
- Existing batches are migrated as active V3 data modules.

## Verification

- Backend tests: 11 passed.
- Frontend tests: 2 passed.
- Production frontend build: successful.
- Browser verified: upload -> Master Data Source -> inline charts -> horizontal boxplots.
- Replacement, retention, revert, multi-upload merge, Spec refresh and Mapping refresh covered by regression tests.
