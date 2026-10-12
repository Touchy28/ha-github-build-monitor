# Changelog

## 0.2.0 — 2026-10-12

- Show remaining time for the **current running step / entire remaining workflow** (e.g. `B&B · ≈1/12m`), not elapsed time.
- Current-step ETA is calculated only when GitHub supplies the running step start time and at least **3** valid prior successful samples for the identical repo, workflow, job and step.
- Total remaining-time ETA comes from the existing workflow-level historical model (minimum 3 previous successful runs), retaining runner and queue-time learning.
- Unknown estimates show `–` (e.g. `B&B · ≈–/12m` or `B&B · Restzeit –`); queue delays and overdue steps are never shown as a fabricated `0m`.
- Keep finished runs concise (`✓`/error), retain the existing repo alias and per-device notification tags, and refresh as remaining minutes change.


## 0.1.9 — 2026-10-12

- iOS Live Activity: remove redundant "GitHub ·" title prefix; show repository name or custom short display name **with time in the title**.
- Show historical estimated remaining range (e.g. `B&B · ~3m–6m`) when available; otherwise show **elapsed** time (e.g. `more-tents · ⏱3m`). Never misrepresent elapsed time as a remaining-time forecast.
- Shorten second line to current step + completed/total steps; percentage is already visible as right-side Live Activity value.
- Individual repository display name/abbreviation (up to 32 characters) in web selection, learning statistic and Live Activity. Real repository URLs, IDs and learned histories remain unchanged.
- Make mobile devices their own collapsed **Geräte auswählen** section between **Repositories** and **Einstellungen**. Use the same selection row/card styling for repositories and devices.
- Existing device selection, GitHub token, repository monitoring, and learned timings are kept intact.


## 0.1.8 — 2026-10-12

- Verständliche Namen für mobile Benachrichtigungsdienste und frei vergebbare Anzeigenamen.
- Mehrfachauswahl von Companion-App-Geräten per Checkbox statt nur einem Empfänger.
- Getrenntes Monitoring der Live-Aktivitäten je Gerät: Start, Status, Abschluss und Entfernen.
- Übernahme alter v0.1.7-Einstellungen und noch laufender Live-Aktivitäten; kein erneutes Eingeben der bisherigen Geräte erforderlich.
- Gezielt nur abgewählte Empfänger bereinigen; Push-Fehler beim Entfernen werden später erneut versucht.
- Keine neuen HA- oder GitHub-Berechtigungen; Token und Supervisor-Optionen bleiben unverändert.
- Zusätzliche Unit-Tests für mehrere Telefone, Aliasnamen, Migration und Fehlerfälle.


## 0.1.7 — vorbereitet (PR)

- Mobile-Companion-App-Auswahlliste statt manueller Eingabe von `live_activity_notify_service`: Dienste serverseitig über die HA REST API entdecken.
- Zentraler Dropdown unter Einstellungen mit Cache/Refresh und sicherem Fallback zur nativen HA-Konfiguration.
- Gerätewechsel schließt bereits aktive Benachrichtigungen auf dem alten Ziel; bei Push-Fehlern wird der Wechsel später erneut versucht.
- CSRF-geschützte Auswahl, nur registrierte `notify.mobile_app_*`-Dienste, keine zusätzliche Netzwerkfreigabe.
- Sicherheits- und Regressionstests.


## 0.1.6 — 2026-10-12

- Added **← Zurück zu Apps** navigation from HA Ingress to the Home Assistant app overview.
- Updated sidebar icon to `mdi:github`; added bundled GitHub icon.png and logo.png assets.
- Unified entry page with repositories, settings overview and learning statistics.
- Collapsed statistics hierarchy by default: Repository → Workflow → time values/runner details/individual Job → Step durations. Reset controls are tucked away.
- Repository picker itself is collapsed for a more compact mobile view, but opens automatically for errors and save confirmations.
- Documented native Supervisor Configuration tab limitation and kept read-only Home Assistant options and GitHub credentials unchanged.


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
