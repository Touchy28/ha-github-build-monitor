# Changelog

## 0.1.5 — geplant, PR #2 (noch nicht veröffentlicht)

- Home-Assistant-Ingress-Weboberfläche zum Anzeigen lokaler Lernzeiten pro Repository und Workflow.
- GitHub-Token liest die autorisierten Repositories über `GET /user/repos` ein; Checkbox-Auswahl statt manueller Repository-Eingabe in der Weboberfläche.
- Server-seitige Repository-Liste, Cache und CSRF-geschützte Auswahl; bestehende Konfiguration bleibt beim Upgrade erhalten.
- Darstellung der Gesamt- und Wartezeiten, Runner-Familien und gelernten GitHub-Schritte.
- Bestätigtes Zurücksetzen einzelner Repositories oder aller Lerndaten, ohne Zugangsdaten und App-Konfiguration zu verändern.
- Zurücksetzungen werden im Monitor-Thread ausgeführt und stören aktive GitHub-Überwachung nicht.
- Wiederanlernen alter GitHub-Runs nach Reset wird durch Zeitstempelgrenzen unterbunden.
- Admin-only Ingress über HA, CSRF-Schutz, keine öffentlichen Ports oder zusätzliche Rechte.


## 0.1.4 — Planned (review before merge)

- Learning by GitHub workflow identity, not one average over all builds.
- Record full workflow durations including idle/queue time between jobs (including parallel jobs).
- Recognize known runner families HA, NEWMAJOR, Synology and GitHub-hosted; prefer same-runner timing when enough examples exist.
- Publish a conservative remaining-time range and forecast confidence only after at least three comparable completed successful runs.
- Backfill at most one recent completed run per repository and polling cycle to seed history without large API bursts.
- Keep all original Home Assistant entity IDs and live notification tags unchanged.
- Changes are staged in a Pull Request to avoid triggering the running HA auto-update before review.


## 0.1.3 — 2026-10-12

- Fix: the original v0.1.0 Dynamic Island Live Activity could remain stuck on `queued` after installing the GitHub repository version because the previous HA add-on stores its notification state in a separate volume.
- Deterministically clear legacy `ghrunner_*` tags for every configured repository once the iPhone notify service is configured; preserve the new per-run tags.
- Add regression tests for the scenario when no original state file is accessible.

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
