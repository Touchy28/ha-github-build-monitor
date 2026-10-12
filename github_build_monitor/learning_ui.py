"""Read-only learning dashboard with CSRF-protected reset requests via HA Ingress.

No published host port, no authentication secrets in the page, no JavaScript.
Only Home Assistant's Ingress proxy is permitted to reach this service.
"""
from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock, Thread
from time import time
from urllib.parse import parse_qs, urlsplit

from learning_store import reset_description, step_breakdown, summary
from repo_selection import effective_repositories, store_selection
from repo_selection_ui import cached_available, get_available, selector_html
from mobile_notify import (clear_service, effective_services, friendly_label,
                           saved_aliases, save_services, selection_file)
from mobile_notify_ui import (cached_services, get_services,
                              selector_html as mobile_selector_html)


def read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds >= 3600:
        return f"{seconds // 3600} Std. {(seconds % 3600) // 60} Min."
    return f"{seconds // 60} Min. {seconds % 60:02d} Sek."


STYLES = """
:root { color-scheme: light dark; font-family: system-ui,-apple-system,sans-serif }
* { box-sizing: border-box }
body { max-width: 880px; margin: 0 auto; padding: 16px 14px 56px;
       line-height: 1.45; background: #f5f7f8; color: #18242c }
a { color: #086ca3 }
h1 { font-size: 1.53rem; margin: 0 }
h2 { font-size: 1.11rem; margin: 0 0 9px }
h3 { font-size: 1rem; margin: 9px 0 5px; overflow-wrap: anywhere }
p { margin: 8px 0 13px }
small,.muted { color: #52616d }
.header-row { display: flex; align-items: center; justify-content: space-between;
              flex-wrap: wrap; gap: 12px; margin-bottom: 18px }
.back-link { display: inline-flex; align-items: center; justify-content: center;
             min-height: 44px; border: 1px solid #c8d6df; background: white;
             border-radius: 10px; padding: 8px 13px; font-weight: 650;
             text-decoration: none }
.brand { display: flex; align-items: center; gap: 14px; padding: 0 0 16px }
.brand-mark { width: 46px; height: 46px; flex-shrink: 0; color: currentColor }
.topnav { display: flex; flex-wrap: wrap; gap: 9px; margin-bottom: 18px }
.topnav a { display: inline-flex; align-items: center; justify-content: center;
            border: 1px solid #d0dce4; border-radius: 9px; padding: 10px 12px;
            min-height: 44px; background: white; font-weight: 600; text-decoration: none }
.card { background: white; border: 1px solid #dae2e8; border-radius: 14px;
        padding: 14px 16px; margin: 13px 0 }
.stats { display: flex; flex-wrap: wrap; gap: 9px; margin: 12px 0 }
.metric { flex: 1; min-width: 142px; padding: 10px; background: #f0f5f7;
          border-radius: 10px; max-width: 100% }
.metric b { display: block; font-size: 1.09rem; font-variant-numeric: tabular-nums }
.workflow-step { padding: 8px 0; border-bottom: 1px solid #e6ebee }
.workflow-step:last-child { border-bottom: 0 }
.workflow-step strong,.workflow-step>.muted { display: block; overflow-wrap: anywhere }
.metric span { display: block; font-size: .81rem; color: #536673 }
.fold-title,.workflow-title { display: flex; align-items: center;
                             flex-wrap: wrap; gap: 5px 10px }
.fold-title>span:first-child,.workflow-title>span:first-child { flex: 1 1 190px;
                                           min-width: 0; overflow-wrap: anywhere }
.fold-count { font-size: .87rem; font-weight: 500; color: #546472;
              background: #edf2f5; border-radius: 7px; padding: 4px 7px }
details>summary { cursor: pointer; font-weight: 660; min-height: 44px;
                  padding: 9px 4px; border-radius: 8px; }
details>summary:focus-visible,a:focus-visible,button:focus-visible {
    outline: 3px solid #1389bd; outline-offset: 2px }
details[open]>summary { margin-bottom: 7px; }
.fold-body { padding: 0 2px 5px }
.workflow-fold { margin: 9px 0; border-top: 1px solid #e6ebee;
                 padding-top: 8px }
.time-fold,.runner-fold,.reset-fold { margin: 9px 0; padding: 5px 12px;
                                     border: 1px solid #e1e9ed; border-radius: 10px }
.time-fold>.fold-body,.runner-fold>.fold-body { padding-top: 3px }
.learning-intro { margin: 20px 3px 12px }
.repository-list { max-height: 480px; overflow-y: auto; border: 1px solid #dce4e9;
                   border-radius: 10px; padding: 3px 10px }
.repository-choice { display: flex; align-items: center; min-height: 52px;
                     gap: 12px; padding: 9px 4px; border-bottom: 1px solid #e8edef }
.repository-choice:last-child { border-bottom: 0 }
.repository-choice input { width: 23px; height: 23px; flex-shrink: 0 }
.repository-details { display:flex; flex-direction:column; min-width:0;
                      overflow-wrap: anywhere }
.repository-details small { font-size: .78rem; margin-top: 2px }
.neutral { background: #33586b }
.mobile-choice { padding: 10px 3px; border-bottom: 1px solid #dce4e9 }
.mobile-choice-label { display:flex; gap:12px; align-items:center; }
.mobile-choice-label input { width:22px; height:22px; flex-shrink:0 }
.mobile-choice-label span { display:flex; flex-direction:column; min-width:0; overflow-wrap:anywhere }
.mobile-choice-label small { font-weight:normal; font-size:.76rem }
.alias-label { display:block; font-size:.85rem; margin:8px 0 0 33px }
.alias-label input { display:block; min-height:40px; width:100%; padding:8px;
                     border:1px solid #b8c6d2; border-radius:8px; font:inherit }
.warning { padding: 10px; background: #fce4e0; color: #6f201c;
           border-radius: 9px }
form { margin: 12px 0 0 }
button { background: #a4362c; color: white; font-size: .94rem; border: 0;
         padding: 11px 13px; min-height: 44px; border-radius: 9px; cursor: pointer }
button.neutral { background: #30576b }
.ack { display: block; margin: 10px 0; font-size: .89rem }
.note { padding: 13px; border-radius: 10px; background: #e4f4f0; color: #154a40 }
.empty { padding: 9px 0; color: #64737d }
code { font-size: .87em; overflow-wrap: anywhere }
.notify-picker { margin: 18px 0; padding: 12px; border: 1px solid #dce4e9;
                 border-radius: 12px }
.notify-picker select { width: 100%; min-width: 0; min-height: 46px; font: inherit;
                        border-radius: 9px; border: 1px solid #aab8c3;
                        padding: 10px; background: #fff; color: #152b39 }
.notify-picker label { display: block; margin-bottom: 8px }
.picker-buttons { margin: 12px 0 0 }
@media (prefers-color-scheme: dark) {
 .notify-picker select { background: #202b31; color: #f2f6f7; border-color: #546875 }
 .notify-picker { border-color: #40515b }
}
@media (prefers-color-scheme: dark) {
 body { background: #11171c; color: #f2f6f7 }
 .card,.back-link,.topnav a { background: #202b31; border-color: #36444c }
 .metric,.fold-count { background: #293a43 }
 a { color: #8bc9e9 }
 small,.muted,.metric span,.empty,.fold-count { color: #bac9d1 }
 .workflow-fold,.repository-choice { border-color: #37434b }
 .repository-list,.time-fold,.runner-fold,.reset-fold { border-color: #40515b }
 .note { background: #183b34; color: #d1f6e8 }
}
@media (max-width: 370px) {
 .metric { min-width: 100%; }
 .topnav a { flex: 1 1 130px }
}
"""


def reset_form(scope: str, label: str, csrf: str) -> str:
    return (
        '<form action="reset" method="post">'
        f'<input type="hidden" name="scope" value="{escape(scope, quote=True)}">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        '<label class="ack"><input type="checkbox" name="confirm" value="yes" required>'
        ' Ich bestätige, dass diese gesammelten Laufzeiten gelöscht werden.</label>'
        f'<button type="submit">{escape(label)}</button></form>'
    )


# Material Design Icons "github" vector, rendered inline without external assets.
GITHUB_PATH = (
    "M12,2A10,10 0 0,0 2,12C2,16.42 4.87,20.17 8.84,21.5"
    "C9.34,21.58 9.5,21.27 9.5,21C9.5,20.77 9.5,20.14 9.5,19.31"
    "C6.73,19.91 6.14,17.97 6.14,17.97C5.68,16.81 5.03,16.5 5.03,16.5"
    "C4.12,15.88 5.1,15.9 5.1,15.9C6.1,15.97 6.63,16.93 6.63,16.93"
    "C7.5,18.45 8.97,18 9.54,17.76C9.63,17.11 9.89,16.67 10.17,16.42"
    "C7.95,16.17 5.62,15.31 5.62,11.5C5.62,10.39 6,9.5 6.65,8.79"
    "C6.55,8.54 6.2,7.5 6.75,6.15C6.75,6.15 7.59,5.88 9.5,7.17"
    "C10.29,6.95 11.15,6.84 12,6.84C12.85,6.84 13.71,6.95 14.5,7.17"
    "C16.41,5.88 17.25,6.15 17.25,6.15C17.8,7.5 17.45,8.54 17.35,8.79"
    "C18,9.5 18.38,10.39 18.38,11.5C18.38,15.32 16.04,16.16 13.81,16.41"
    "C14.17,16.72 14.5,17.33 14.5,18.26C14.5,19.6 14.5,20.68 14.5,21"
    "C14.5,21.27 14.66,21.59 15.17,21.5C19.14,20.16 22,16.42 22,12"
    "A10,10 0 0,0 12,2Z"
)


def settings_panel(data_dir: Path, mobile_html: str = "", expand: bool = False) -> str:
    """Read-only overview: Supervisor owns token and native options."""
    settings = read_json(data_dir / "options.json")
    token_status = "Hinterlegt" if settings.get("github_api_token") else "Nicht hinterlegt"
    enabled = "Aktiviert" if settings.get("live_activity_enabled") else "Deaktiviert"
    choices = effective_services(settings, data_dir)
    names = saved_aliases(data_dir)
    service = escape(", ".join(names.get(name) or friendly_label(name) for name in choices)
                     or "Keine Geräte ausgewählt")
    polling = settings.get("poll_interval_seconds", 60)
    try:
        interval = max(30, min(300, int(polling)))
    except (ValueError, TypeError):
        interval = 60
    return (
        '<details class="card" id="settings"' + (' open' if expand else '') + '>'
        '<summary class="fold-title"><span>⚙️ Einstellungen</span>'
        '<span class="fold-count">Übersicht</span></summary><div class="fold-body">'
        '<p class="muted">Überwachung, Lernzeiten und Repository-Auswahl verwaltest du '
        'auf dieser Seite. Die sicherheitsrelevanten App-Optionen werden weiterhin '
        'von Home Assistant selbst gespeichert.</p>'
        '<div class="stats">'
        f'<div class="metric"><b>{token_status}</b><span>GitHub-Token</span></div>'
        f'<div class="metric"><b>{interval} Sek.</b><span>GitHub-Abfrage</span></div>'
        f'<div class="metric"><b>{enabled}</b><span>iPhone-Live-Aktivitäten</span></div>'
        '</div>'
        f'<p class="muted">Benachrichtigungsgeräte: <strong>{service}</strong></p>'
        + mobile_html
        + '<p><a class="back-link" href="/hassio" target="_top" rel="noopener noreferrer">'
        'Zur HA-App-Konfiguration ↗</a></p>'
        '<p class="muted"><small>Die native Home-Assistant-Registerkarte „Konfiguration“ '
        'kann eine App technisch nicht umleiten. Klicke in der App-Übersicht auf '
        'GitHub Build Monitor → Konfiguration, um Token, Aktivierung und Intervall '
        'zu ändern.</small></p></div></details>'
    )


def render(data_dir: Path, csrf: str, queued: bool = False,
           repositories_html: str = "", mobile_html: str = "",
           expand_settings: bool = False) -> bytes:
    history = read_json(data_dir / "monitor_history.json")
    configured = effective_repositories(read_json(data_dir / "options.json"), data_dir)
    records = summary(history, configured)
    cards = []
    for entry in records:
        name = escape(entry["repository"])
        summary_caption = (
            f'{entry["workflow_samples"]} Läufe · {entry["step_samples"]} Schritt-Messungen'
        )
        workflow_parts = []
        for item in entry["workflows"]:
            runner_text = ", ".join(
                f"{escape(runner)} ({int(count)})" for runner, count in item["runners"]
            )
            ready = (
                "Prognose möglich" if item["prognosis_ready"]
                else f"Noch {max(0, 3 - item['runs'])} Messungen bis zur Prognose"
            )
            time_values = (
                '<details class="time-fold"><summary>⏱ Zeitwerte anzeigen</summary>'
                '<div class="fold-body"><div class="stats">'
                f'<div class="metric"><b>{duration(item["median_seconds"])}</b>'
                '<span>Typische Gesamtdauer</span></div>'
                f'<div class="metric"><b>{duration(item["median_queue_seconds"])}</b>'
                '<span>Typische Wartezeit</span></div>'
                f'<div class="metric"><b>{duration(item["min_seconds"])} – '
                f'{duration(item["max_seconds"])}</b><span>Bisherige Spannweite</span></div>'
                '</div></div></details>'
            )
            runner_details = (
                '<details class="runner-fold"><summary>🖥 Runner anzeigen</summary>'
                '<div class="fold-body"><p>'
                + (runner_text or "Noch kein Runner erfasst")
                + '</p></div></details>'
            )
            detail_sections = []
            for job_data in step_breakdown(history, entry["repository"], item["name"]):
                step_rows = []
                for step_data in job_data["steps"]:
                    step_rows.append(
                        '<div class="workflow-step">'
                        f'<strong>{escape(step_data["name"])}</strong>'
                        f'<span class="muted">{int(step_data["samples"])} Messungen</span>'
                        '<div class="stats">'
                        f'<div class="metric"><b>{duration(step_data["median_seconds"])}</b>'
                        '<span>Typisch</span></div>'
                        f'<div class="metric"><b>{duration(step_data["min_seconds"])} – '
                        f'{duration(step_data["max_seconds"])}</b><span>Spannweite</span>'
                        '</div></div>'
                    )
                detail_sections.append(
                    '<details class="runner-fold"><summary>📂 '
                    + escape(job_data["job"]) + f' ({len(job_data["steps"])} Schritte)'
                    '</summary><div class="fold-body">'
                    + "".join(step_rows) + '</div></details>'
                )
            steps_html = (
                '<details class="time-fold"><summary>🔎 Gelernte Schrittzeiten'
                f' ({sum(len(j["steps"]) for j in step_breakdown(history, entry["repository"], item["name"]))})'
                '</summary><div class="fold-body">'
                + "".join(detail_sections)
                + '</div></details>'
            ) if detail_sections else ''
            workflow_parts.append(
                '<details class="workflow-fold">'
                '<summary class="workflow-title">'
                f'<span>{escape(item["name"])}</span>'
                f'<span class="fold-count">{int(item["runs"])} Läufe</span></summary>'
                f'<div class="fold-body"><p class="muted">{escape(ready)}</p>'
                + time_values + steps_html + runner_details + '</div></details>'
            )
        if not workflow_parts:
            workflow_parts.append(
                '<p class="empty">Noch keine abgeschlossenen erfolgreichen '
                'Workflow-Messungen. Der Monitor lernt bei regulären Builds.</p>'
            )
        reset_at = reset_description(history, entry["repository"])
        if reset_at:
            workflow_parts.append(
                f'<p class="muted"><small>Zuletzt zurückgesetzt: {escape(reset_at)}</small></p>'
            )
        workflow_parts.append(
            '<details class="reset-fold"><summary>Lerndaten dieses Repositories zurücksetzen'
            '</summary><div class="fold-body">'
            '<p class="muted">Löscht nur diese historischen Zeiten; '
            'frühere Läufe werden nicht erneut eingelesen.</p>'
            + reset_form(entry["repository"], "Lerndaten zurücksetzen", csrf)
            + '</div></details>'
        )
        cards.append(
            '<section class="card"><details class="repo-fold">'
            f'<summary class="fold-title"><span>📦 {name}</span>'
            f'<span class="fold-count">{escape(summary_caption)}</span></summary>'
            '<div class="fold-body"><div class="stats">'
            f'<div class="metric"><b>{entry["workflow_samples"]}</b>'
            '<span>Workflow-Messungen</span></div>'
            f'<div class="metric"><b>{entry["step_samples"]}</b>'
            '<span>Schritt-Messungen</span></div>'
            f'<div class="metric"><b>{entry["step_types"]}</b>'
            '<span>Verschiedene Schritte</span></div></div>'
            + "".join(workflow_parts) + '</div></details></section>'
        )
    if not cards:
        cards = [
            '<section class="card"><p>Aktuell ist kein Repository zur '
            'Überwachung ausgewählt. Wähle oben Repositories aus GitHub aus.</p></section>'
        ]
    notification = (
        '<p class="note">Zurücksetzung vorgemerkt. Der Monitor führt sie im '
        'nächsten Prüfzyklus aus. Danach diese Seite aktualisieren.</p>'
        if queued else ''
    )
    icon = (
        '<svg class="brand-mark" role="img" aria-label="GitHub" viewBox="0 0 24 24">'
        f'<path fill="currentColor" d="{GITHUB_PATH}"></path></svg>'
    )
    html = (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>GitHub Build Monitor</title>'
        f'<style>{STYLES}</style></head><body>'
        '<nav class="header-row" aria-label="Zurück und Aktualisierung">'
        '<a class="back-link" href="/hassio" target="_top" rel="noopener noreferrer">'
        '← Zurück zu Apps</a><a href="./">↻ Aktualisieren</a></nav>'
        f'<header class="brand">{icon}<div><h1>GitHub Build Monitor</h1>'
        '<p class="muted">Überwachung · Repositories · Lernstatistik</p></div></header>'
        '<nav class="topnav" aria-label="Bereiche">'
        '<a href="#repositories">Repositories</a>'
        '<a href="#settings">Einstellungen</a>'
        '<a href="#learning">Lernstatistik</a></nav>'
        + notification + repositories_html + settings_panel(data_dir, mobile_html, expand_settings)
        + '<section id="learning" class="learning-intro"><h2>⏱ Lernstatistik</h2>'
        '<p class="muted">Tippe auf ein Repository, dann auf einen Workflow. '
        'Zeitwerte und Runner lassen sich einzeln aufklappen.</p></section>'
        + "".join(cards)
        + '<details class="card" id="reset-all"><summary>Alle Lerndaten zurücksetzen'
        '</summary><div class="fold-body">'
        '<p class="muted">Löscht alle gesammelten Zeiten, '
        'ohne GitHub-Token, Einstellungen, Sensoren oder Live-Aktivitäten zu verändern. '
        'Ältere Builds werden nicht erneut eingelesen.</p>'
        + reset_form("all", "Alle Lerndaten löschen", csrf)
        + '</div></details>'
        '<p class="muted"><small>Die Laufzeitdaten bleiben lokal in Home Assistant.</small></p>'
        '</body></html>'
    )
    return html.encode("utf-8")


class LearningHandler(BaseHTTPRequestHandler):
    server_version = "GHBuildLearning/1"

    def log_message(self, format: str, *args: object) -> None:
        # Do not log tokens, query strings or user-supplied form fields.
        pass

    def trusted(self) -> bool:
        return self.client_address[0] in self.server.allowed_peers

    def respond(self, code: int, text: bytes, content_type="text/plain; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(text)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "form-action 'self'; base-uri 'none'; frame-ancestors 'self'")
        self.end_headers()
        self.wfile.write(text)

    def do_GET(self) -> None:
        if not self.trusted():
            return self.respond(403, b"Only Home Assistant Ingress is allowed.")
        path = urlsplit(self.path)
        if path.path not in ("/", ""):
            return self.respond(404, b"Not found")
        query = parse_qs(path.query)
        queued = query.get("reset") == ["queued"]
        options = read_json(self.server.data_dir / "options.json")
        selected = effective_repositories(options, self.server.data_dir)
        available, problem = get_available(self.server, str(options.get("github_api_token") or ""),
                                           refresh=query.get("refresh") == ["1"])
        message = ("Auswahl gespeichert. Der Monitor übernimmt sie beim nächsten Prüfzyklus."
                   if query.get("selection") == ["saved"] else "")
        section = selector_html(selected, available, self.server.csrf,
                                message=message, error=problem or "")
        devices, mobile_error = get_services(
            self.server, refresh=query.get("refresh_mobile") == ["1"])
        saved_mobile = query.get("notify") == ["saved"]
        mobile_services = effective_services(options, self.server.data_dir)
        mobile_aliases = saved_aliases(self.server.data_dir)
        mobile_html = mobile_selector_html(
            mobile_services[0] if mobile_services else "", devices, self.server.csrf,
            message=("Zielgerät gespeichert. Der Monitor übernimmt es beim nächsten "
                     "Prüfzyklus." if saved_mobile else ""),
            error=mobile_error,
            override_active=selection_file(self.server.data_dir).exists(),
            selected=mobile_services, aliases=mobile_aliases)
        page = render(self.server.data_dir, self.server.csrf, queued=queued,
                      repositories_html=section, mobile_html=mobile_html,
                      expand_settings=saved_mobile or bool(mobile_error) or query.get("refresh_mobile") == ["1"])
        return self.respond(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if not self.trusted():
            return self.respond(403, b"Only Home Assistant Ingress is allowed.")
        route = urlsplit(self.path).path
        if route not in ("/reset", "/repositories", "/notify-service"):
            return self.respond(404, b"Not found")
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            return self.respond(415, b"Unsupported content type")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, b"Invalid content length")
        max_length = 100_000 if route in ("/repositories", "/notify-service") else 2048
        if length < 1 or length > max_length:
            return self.respond(413, b"Invalid body length")
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "strict"))
        if fields.get("csrf") != [self.server.csrf]:
            return self.respond(403, b"Invalid CSRF token")
        if route == "/notify-service":
            if fields.get("use_native") == ["1"]:
                with self.server.reset_lock:
                    clear_service(self.server.data_dir)
            else:
                available_services = cached_services(self.server)
                if available_services is None:
                    return self.respond(409, b"Device list expired; refresh it.")
                listed = fields.get("listed", [])
                names = fields.get("alias", [])
                targets = fields.get("target", [])
                if (len(listed) != len(names) or len(listed) > 50
                        or len(set(listed)) != len(listed)):
                    return self.respond(400, b"Invalid device form.")
                if set(listed) != set(available_services) or any(
                        target not in available_services for target in targets):
                    return self.respond(400, b"Unknown device in request.")
                if len(set(targets)) != len(targets):
                    return self.respond(400, b"Duplicate device.")
                try:
                    with self.server.reset_lock:
                        save_services(self.server.data_dir, targets, dict(zip(listed, names)))
                except (ValueError, TypeError):
                    return self.respond(400, b"Invalid selection or display name.")
            self.send_response(303)
            self.send_header("Location", "./?notify=saved#settings")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if route == "/repositories":
            options = read_json(self.server.data_dir / "options.json")
            token = str(options.get("github_api_token") or "")
            available = cached_available(self.server, token)
            if available is None:
                return self.respond(409, b"Repository-Liste abgelaufen. Bitte erneut aus GitHub laden.")
            available_by_name = {entry["full_name"].casefold(): entry["full_name"]
                                 for entry in available}
            selections = fields.get("repository", [])
            if len(selections) > 1000 or len(selections) != len(set(name.casefold() for name in selections)):
                return self.respond(400, b"Invalid repository selection")
            if any(name.casefold() not in available_by_name for name in selections):
                return self.respond(400, b"Repository not authorized for this token")
            chosen = [available_by_name[name.casefold()] for name in selections]
            with self.server.reset_lock:
                store_selection(self.server.data_dir, chosen)
            self.send_response(303)
            self.send_header("Location", "./?selection=saved")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if fields.get("confirm") != ["yes"]:
            return self.respond(403, b"Missing confirmation")
        scope = fields.get("scope", [""])[0]
        allowed = effective_repositories(read_json(self.server.data_dir / "options.json"),
                                         self.server.data_dir)
        if scope != "all" and scope not in allowed:
            return self.respond(400, b"Unknown repository")
        with self.server.reset_lock:
            path = self.server.data_dir / "reset-learning-command.json"
            if path.exists():
                return self.respond(409, b"An earlier reset is still pending.")
            command = {"scope": scope, "at": time(), "csrf_checked": True}
            temp = self.server.data_dir / "reset-learning-command.tmp"
            temp.write_text(json.dumps(command), encoding="utf-8")
            os.replace(temp, path)
        self.send_response(303)
        self.send_header("Location", "./?reset=queued")
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()


def start(data_dir: Path, port: int = 8099, host: str = "0.0.0.0",
          allowed_peers: set[str] | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), LearningHandler)
    server.daemon_threads = True
    server.data_dir = data_dir
    server.csrf = token_urlsafe(32)
    server.reset_lock = Lock()
    server.repositories_lock = Lock()
    server.repositories_cache = {}
    server.mobile_services_lock = Lock()
    server.mobile_services_cache = {}
    server.ha_token = os.environ.get("SUPERVISOR_TOKEN", "")
    # HA Supervisor's documented ingress proxy IP. No direct LAN access.
    server.allowed_peers = ({"172.30.32.2"} if allowed_peers is None
                            else allowed_peers)
    Thread(target=server.serve_forever, name="learning-ui", daemon=True).start()
    return server
