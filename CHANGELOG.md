# Changelog

## 0.1.2 — 2026-10-12

- Compared against original functioning v0.1.0 archive.
- Preserve v0.1.0 Home Assistant sensor entity IDs, states and attributes for existing dashboards.
- Import historical step durations where the original /data directory is still available.
- Restore settings reload each poll, stale queued-run protection and preserving last valid status on API failures.
- Only interpolate running steps with at least two historical measurements of that workflow step.
- Keep parallel run Live Activities; clean up old per-repository notification tags when prior state is accessible.
- Restore original dashboard examples and add upgrade regression tests.

## 0.1.1 — 2026-10-12

- Repository initialized for standalone Home Assistant GitHub Actions monitoring.
- Read-only API polling, native HA status sensors and mobile Live Activities.
- Isolated from existing self-hosted runners and Docker permissions.
- Independent CI/unit tests.
- IMPORTANT: The code has been reconstructed from the earlier prototype specification because the exact previous ZIP is not available in the current workspace; compare with the currently installed local HA App before changing its update source.
