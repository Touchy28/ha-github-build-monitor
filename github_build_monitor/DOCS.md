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
