# GitHub Build Monitor for Home Assistant

A standalone **read-only GitHub Actions monitor** for Home Assistant with native HA sensors, estimated build progress and iPhone Live Activities / Android Live Updates. No runner registration or Docker socket permissions.

> **Version 0.1.7**. GitHub-hosted Home Assistant app with read-only monitoring, repository picker and compact timing dashboard. Stop the previous local app if you have not already done so.

## Capabilities

- Multiple repositories, including Touchy28/DSO-Optimizer and Touchy28/more-tents
- GitHub Actions workflows, job and step states, success/failure/cancelled results
- Native entity for each repository with progress, completed/total steps, current job, runner name, URL and optional ETA
- Weighted progress using previous successful step execution durations; percentages within a running step are **estimates**, not GitHub-reported metrics
- One Live Activity per concurrently active run (up to six active runs per repository), status updates and automatic removal after completion
- Persistent learning history and notification state across app restarts
- Works regardless of whether runs execute on Windows, Synology, HA or GitHub-hosted runners

## Security

- GitHub fine-grained personal access token: select repositories, **Actions: Read-only**; Metadata read is implicit. No Secrets, Contents write, Webhooks or Admin permission.
- Home Assistant app uses only **homeassistant_api: true** for its entities and mobile notifications. It does not request host Docker APIs or privileged access.
- Token is stored in **Home Assistant app options only** and never committed here. All runtime history is kept in the app's private data volume.
- If your repository is public, unauthenticated API reads may work, but authenticated requests have higher rate limits and are necessary for private repositories.

## Important: installation and migration

**When migrating from the local v0.1.0 app, stop the old installation first.** Installing and running two instances in parallel is not recommended, because both can update the same sensors and notifications. When the old v0.1.0 data directory is **available inside the new add-on's same /data volume**, learned durations are imported automatically. **Important:** switching from a local add-on to a repository add-on may change the Supervisor add-on ID and its private storage volume; in that case automatic migration cannot access old history. Back up the old app data before switching.

For a new installation on Home Assistant OS / Supervisor:

1. In **Settings → Apps → App Store → ⋮ → Repositories**, add:
   https://github.com/Touchy28/ha-github-build-monitor
2. Refresh the store, select **GitHub Build Monitor**, then install it.
3. In app configuration, enter a GitHub Actions **read-only** token, select repositories, and leave mobile notifications off for the initial sensor check.
4. Start the app; inspect **Log** and look for sensors with the prefix sensor.github_runner_ under Developer Tools → States.
5. Once the sensor check succeeds, enable Live Activities and set **live_activity_notify_service** to e.g. notify.mobile_app_iphone (use your actual mobile service).

### Options

| Setting | Example | Meaning |
| --- | --- | --- |
| repositories | Touchy28/DSO-Optimizer, Touchy28/more-tents | GitHub repositories to monitor |
| github_api_token | (secret) | GitHub fine-grained token: Actions Read |
| live_activity_enabled | false | Enable mobile push Live Activities |
| live_activity_notify_service | notify.mobile_app_iphone | Actual Home Assistant phone notifier |
| poll_interval_seconds | 60 | 30–300 seconds; higher interval saves API calls |

### Eine zentrale Weboberfläche (ab v0.1.6)

**Info → Weboberfläche öffnen**, alternativ über den neuen **GitHub Build Monitor**-Eintrag in der Home-Assistant-Seitenleiste. Die Webansicht besitzt einen **← Zurück zu Apps**-Knopf. Das GitHub-Logo wird sowohl in der Seitenleiste als auch als App-Kachel dargestellt.

Die Webansicht vereint Repository-Auswahl, Einstellungen-Übersicht und Lernstatistik. Die Statistik ist von Beginn an eingeklappt: **Repository → Workflow → Gesamtzeiten / Runner / Job → Schrittzeiten**. Jede Ebene lässt sich unabhängig öffnen.

**Einschränkung der Home-Assistant-Oberfläche:** Die native **Konfiguration**-Registerkarte lässt sich von einer App nicht auf ihre eigene Ingress-Webansicht umleiten. Die Tokens und Basisoptionen verbleiben daher in der normalen HA-Konfiguration; die Weboberfläche zeigt deren Status sowie einen Link zurück zur App-Übersicht. Das vermeidet zusätzliche Supervisor-Rechte und hält bestehende Einstellungen kompatibel.

### iPhone-Zielgerät auswählen (ab v0.1.7)

Unter **GitHub Build Monitor → Weboberfläche → Einstellungen** gibt es ein
Dropdown **Zielgerät für Live-Aktivitäten**. Die App liest mit ihrer vorhandenen
Home-Assistant-API-Berechtigung die bereits registrierten
`notify.mobile_app_*`-Dienste aus `GET /api/services` ein.
Die Liste kann über **Geräte aus Home Assistant neu einlesen**
aktualisiert werden.

- Die vorhandene Einstellung bleibt erhalten, bis du ein anderes Gerät auswählst.
- Nach dem Speichern wechselt der Monitor beim nächsten Abfragezyklus; laufende
  Live-Aktivitäten werden zunächst auf dem **vorherigen** Gerät entfernt.
- Bei einem Fehler beim Entfernen versucht die App den Wechsel später erneut,
  statt eine verwaiste Aktivität zu riskieren.
- Die Dropdown-Auswahl wird in einer eigenen Datei in `/data` gesichert,
  nicht in die vom Supervisor verwalteten Optionen zurückgeschrieben.
- Im nativen HA-Konfigurationsformular bleibt das bisherige Eingabefeld aus
  Kompatibilitätsgründen sichtbar. Die Webauswahl hat Vorrang.
  Mit **Wert aus HA-App-Konfiguration verwenden** kannst du die Webauswahl
  wieder zurücknehmen.
- Voraussetzung: Companion App auf dem gewünschten Gerät registriert und
  Push-Benachrichtigungen erlaubt. Die Auswahl selbst verschickt noch keine
  Test-Benachrichtigung.

### Repository-Auswahl per GitHub-Token (ab v0.1.5)

Statt Repository-Namen manuell einzutippen: Unter **Info → OPEN WEB UI**
lädt die App die mit dem bereits gespeicherten GitHub-Token sichtbaren
Repositories über die GitHub-REST-API. In der Liste können beliebig viele
Projekte per Checkbox ein- und ausgeschaltet und mit **Auswahl speichern**
zur Überwachung vorgemerkt werden. Der Token bleibt serverseitig in den
Home-Assistant-App-Optionen; die Auswahldatei speichert ausschließlich Namen.

- Ein Fine-Grained-Token benötigt für die **Auswahlliste** `Metadata: Read`
  (standardmäßig enthalten), und für das **Monitoring** `Actions: Read`
  für die autorisierten Repositories.
- Die GitHub-Auswahlliste umfasst nur Repositories, die mit dem Token
  zugänglich sind. Private Repositories werden entsprechend gekennzeichnet.
- Bereits gespeicherte Repositories aus den alten App-Optionen bleiben beim
  Upgrade zunächst aktiv. **Erst nach dem ersten Speichern der Webauswahl**
  übernimmt die neue Auswahl die Kontrolle. Eine leere Auswahl stoppt das
  Monitoring vollständig.
- Der alte App-Konfigurationseintrag `repositories` bleibt für die
  Kompatibilität vorhanden und dient nach einer gespeicherten Webauswahl
  nur noch als Fallback bei deren Entfernung.
- Neue Auswahl wird automatisch beim nächsten Poll übernommen. Die
  bisher gesammelten Laufzeiten für abgewählte Projekte bleiben erhalten;
  laufende Live-Aktivitäten für abgewählte Projekte werden beendet.
- Die Liste wird serverseitig maximal 10 Minuten zwischengespeichert,
  kann über **Repository-Liste von GitHub aktualisieren** neu geladen
  werden und wird bei Tokenwechsel automatisch ungültig.
- Bei API-Fehlern oder einem ungültigen Token bleibt die bisherige
  Auswahl bestehen. Token oder GitHub-Zugangsdaten werden niemals
  an den Browser übertragen.

### Lernstatistik und Zurücksetzen (ab v0.1.5)

Die normale **Konfiguration** zeigt statische Supervisor-App-Optionen wie Token und Repository-Liste. Laufende Lerndaten können dort nicht automatisch als Tabelle angezeigt werden. Für die neue Statistik öffne in der App unter **Info → OPEN WEB UI** die integrierte Home-Assistant-Oberfläche **Build-Lernstatistik**. Es ist kein separater Webserver-Zugang, Passwort oder Router-Port erforderlich (Home Assistant Ingress, Admin-Panel).

- Pro konfiguriertem Repository: Anzahl vollständiger Workflow-Durchläufe, Schrittmessungen und verschiedener Schritte.
- Pro Workflow: typische Gesamtdauer, Wartezeit, bisheriges Minimum und Maximum sowie genutzte Runner-Familien.
- Erste Gesamtzeit-Prognosen können ab drei passenden Messungen entstehen; die Genauigkeit hängt weiterhin von Job-Topologie und Runner ab.
- **Zurücksetzen:** Entweder nur ein Repository oder alle Lerndaten. Eine Bestätigung ist notwendig. Änderungen wirken beim nächsten Poll (normalerweise innerhalb von 60 Sekunden).
- Beim Reset werden historische GitHub-Runs vor dem Reset-Zeitpunkt **nicht wieder automatisch eingelesen**; erst später fertiggestellte erfolgreiche Runs werden neu gelernt.
- Der Reset verändert **nicht** den GitHub-Token, die konfigurierten Repositories, die Sensor-Entitäten oder laufende iPhone-Live-Aktivitäten.
- Die Informationen verbleiben im privaten App-Datenverzeichnis; der Webzugriff wird über Home Assistant authentifiziert.

### Entities

Each repository retains its **v0.1.0 entity ID**, for example **sensor.github_runner_touchy28_more_tents_18b499**. Sensor states retain running/queued/success/failure/cancelled/idle. The original attributes progress, steps_done, steps_total, job, step, runner, eta_seconds, active_runs and url remain available. New attributes include progress_percent, progress_is_estimate, workflow, run_id, run_url, current_job, current_step, completed_steps, total_steps, estimated_remaining_seconds, active_run_count and runner_name.

Home Assistant REST-created sensor entities are **not persistent** across an HA restart until the monitor posts them again. They are not Config Entries.

### iPhone Live Activities

When enabled, notifications use the Companion App live_update setting with a unique tag per run. Updates modify the same activity; after a completed run, the monitor publishes the final result and removes the notification on a subsequent poll. Requires HA Core 2026.7+, iOS 17.2+ and working Companion App push notifications.

### Known limits

- At most six active Live Activities per repository and first 20 runs / up to 500 jobs per workflow.
- Percentage and ETA are **approximations**. Active steps are interpolated only after at least two historical measurements of the same workflow/job/step. Progress is clamped to avoid decreases when jobs appear.
- GitHub API authentication errors and rate limits show up in the HA app log; previous sensor and Live Activity remain unchanged on transient failures. The monitor retries on the next cycle.
- Service calls update live notifications only while Home Assistant/Companion App push transport is available.
- The new code intentionally differs from v0.1.0: it supports multiple parallel Live Activities and a completed failed run reports 100% execution with the failure conclusion clearly shown. Its notification tag format changes. **Since 0.1.3, deterministic v0.1.0 per-repository tags are cleared automatically once even if the original add-on data is unavailable**, provided a mobile notify service is configured. Keep the old local app stopped.

The options and the saved Ingress checkbox selection are re-read on every polling cycle; changes do not normally require a restart.

The original examples for two HA gauge cards are in [examples/ha-template.yaml](examples/ha-template.yaml) and [examples/ha-dashboard.yaml](examples/ha-dashboard.yaml).

## Development and tests

Unit tests use the Python standard library; no third-party runtime dependencies.

    python -m unittest discover -s tests -v

GitHub Actions runs the tests and syntax checks on each push and pull request.

## Attribution

Inspired by the experience of using separate GitHub Actions runners on Home Assistant. Existing runner projects such as [dchote/github-runner-addon](https://github.com/dchote/github-runner-addon) remain independent; this monitor can observe jobs they run.
