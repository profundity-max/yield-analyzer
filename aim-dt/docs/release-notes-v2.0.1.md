# AIM D-T V2.0.1 Release Notes

Release date: 2026-10-15

## Fixes

- Fixed Mapping editor saves producing a new active Mapping but failing to refresh the chart.
- Fixed Spec editor saves producing a new active Spec but failing to refresh the chart.
- `rerun-with` now accepts explicitly selected historical or retired Spec and Mapping versions.
- Analysis worker now processes pinned historical versions instead of rejecting them.
- Version selectors include active and retired versions so an existing analysis always shows its current selection.
- Added visible rerun error feedback instead of silently leaving the old chart in place.
- Added regression tests covering retired Spec + retired Mapping recalculation.

## Verified Scenario

1. Open an existing analysis bound to a retired Spec and Mapping.
2. Confirm a mapping change and save.
3. Create a new analysis snapshot.
4. The worker recalculates using the saved Mapping and the chart changes.
5. The same flow is tested for Spec changes.
