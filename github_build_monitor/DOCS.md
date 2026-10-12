# GitHub Build Monitor – Bedienung

**Zentrale Weboberfläche:** Öffne **Einstellungen → Apps → GitHub Build Monitor → Info → Weboberfläche öffnen**. Du kannst sie auch über den Eintrag **GitHub Build Monitor** in der Home-Assistant-Seitenleiste öffnen.

In der Weboberfläche findest du:

- **Repositories:** Mit deinem GitHub-Lese-Token verfügbare Projekte auswählen oder abwählen.
- **Einstellungen:** Überblick über Token-Status, Abfrageintervall und Live-Aktivitäten; Link zur HA-App-Übersicht.
- **Lernstatistik:** Zunächst eingeklappte Repositories. Nach dem Aufklappen eines Repositories folgen die Workflows. Darin kannst du **Gesamtzeit/Wartezeit**, **Job → Schrittzeiten** und **Runner** separat anzeigen.
- **Lerndaten zurücksetzen:** Pro Repository oder für alle mit ausdrücklicher Bestätigung.

**← Zurück zu Apps** führt dich aus der Webansicht wieder in die Home-Assistant-App-Übersicht.

## Warum gibt es zwei Einstellungsansichten?

Die Registerkarte **Konfiguration** wird von Home Assistant selbst dargestellt und lässt sich durch eine App nicht auf eine andere Seite umleiten. Daher sind GitHub-Token, Benachrichtigungsdienst und Abfrageintervall weiterhin sicher in der Home-Assistant-Konfiguration gespeichert. Die Weboberfläche ist der zentrale Einstieg für Repo-Auswahl, Laufzeitanalyse und Zurücksetzen und zeigt die übrigen Einstellungen als Übersicht an.

Die GitHub-Überwachung benötigt nur **Actions: Read** und **Metadata: Read** für die freigegebenen Repositories. Es werden keine Docker-Host- oder Runner-Verwaltungsrechte benötigt.


## Benachrichtigungsgerät auswählen (ab v0.1.7)

Unter **Einstellungen → Zielgerät für Live-Aktivitäten** zeigt die Weboberfläche ein Dropdown mit den aktuell von Home Assistant angebotenen Diensten `notify.mobile_app_*`. Die App fragt die Home Assistant REST API `GET /api/services` intern ab – ohne weiteres Token und ohne neue App-Berechtigungen.

- Ein Gerät wählen und auf **Gerät speichern** tippen. Die Auswahl wird beim nächsten Monitor-Poll wirksam.
- Die bisherige iPhone-Einstellung bleibt beim Upgrade unangetastet; bei einem Gerätewechsel versucht der Monitor, vorhandene Live-Aktivitäten zuerst auf dem alten Gerät zu schließen.
- Der alte String `live_activity_notify_service` bleibt in der nativen Supervisor-Konfiguration erhalten. Nach dem Speichern in der Weboberfläche hat die neue Auswahl Vorrang. Über **Wert aus HA-App-Konfiguration verwenden** kann diese Auswahl zurückgenommen werden.
- Es werden ausschließlich Dienste angezeigt, die mit `mobile_app_` beginnen; `notify.send_message` und andere Aktionen werden nicht angeboten.
- Home Assistant muss den Dienst über die Companion App registriert haben. Wenn kein Dienst gefunden wird, bleibt der bisherige Wert erhalten und es erscheint ein Hinweis.
- Die Liste wird alle 90 Sekunden neu ermittelt oder auf Wunsch per Knopfdruck aktualisiert.
