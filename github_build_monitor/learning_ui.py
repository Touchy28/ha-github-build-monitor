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

from learning_store import reset_description, summary
from repo_selection import effective_repositories, store_selection
from repo_selection_ui import cached_available, get_available, selector_html


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
:root { color-scheme: light dark; font-family: system-ui, -apple-system, sans-serif }
* { box-sizing: border-box }
body { max-width: 880px; margin: 0 auto; padding: 22px 14px 50px; line-height: 1.45;
       background: #f5f7f8; color: #18242c }
h1 { font-size: 1.6rem; margin: 2px 0 5px }
h2 { font-size: 1.12rem; margin: 0 0 4px; overflow-wrap: anywhere }
h3 { font-size: 0.98rem; margin: 12px 0 4px; overflow-wrap: anywhere }
p { margin: 6px 0 13px }
small, .muted { color: #51616d }
.card { background: white; border: 1px solid #dce4e9; border-radius: 14px;
        padding: 17px; margin-top: 16px; box-shadow: 0 1px 3px #10212b0a }
.stats { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 }
.metric { flex: 1; min-width: 135px; border-radius: 9px;
          padding: 10px; background: #f0f5f7 }
.metric b { display: block; font-size: 1.16rem; font-variant-numeric: tabular-nums }
.metric span { font-size: 0.82rem; color: #536673 }
.workflow { border-top: 1px solid #e5ebee; padding: 10px 0 }
details { margin-top: 14px }
.repository-list { max-height: 480px; overflow-y: auto; border: 1px solid #dce4e9;
                   border-radius: 10px; padding: 3px 12px; }
.repository-choice { display: flex; align-items: center; min-height: 52px;
                     gap: 12px; padding: 9px 4px; border-bottom: 1px solid #e8edef; }
.repository-choice:last-child { border-bottom: 0 }
.repository-choice input { width: 23px; height: 23px; flex-shrink: 0 }
.repository-details { display:flex; flex-direction:column; min-width:0;
                      overflow-wrap: anywhere }
.repository-details small { font-size: .78rem; margin-top: 2px }
.neutral { background: #33586b }
.warning { padding: 10px; background: #fce4e0; color: #6f201c;
           border-radius: 9px }
summary { cursor: pointer; font-weight: 600 }
form { margin-top: 12px }
button { background: #aa3a2b; color: white; font-size: .94rem;
         border: 0; padding: 10px 12px; border-radius: 9px;
         cursor: pointer }
button:focus-visible, a:focus-visible { outline: 3px solid #1089cf }
.ack { display: block; margin-bottom: 10px; font-size: .89rem }
.ok { color: #137b60 }
.note { padding: 13px; border-radius: 10px; background: #e4f4f0; color: #154a40 }
.empty { padding: 9px 0; color: #64737d }
code { font-size: .87em }
@media (prefers-color-scheme: dark) {
 body { background: #11171c; color: #f2f6f7 }
 .card { background: #202b31; border-color: #36444c }
 .metric { background: #293a43 }
 small, .muted, .metric span, .empty { color: #bac9d1 }
 .workflow { border-color: #37434b }
 .note { background: #183b34; color: #d1f6e8 }
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


def render(data_dir: Path, csrf: str, queued: bool = False,
           repositories_html: str = "") -> bytes:
    history = read_json(data_dir / "monitor_history.json")
    configured = effective_repositories(read_json(data_dir / "options.json"), data_dir)
    records = summary(history, configured)
    cards = []
    for entry in records:
        name = escape(entry["repository"])
        metrics = (
            f'<div class="metric"><b>{entry["workflow_samples"]}</b><span>Workflow-Messungen</span></div>'
            f'<div class="metric"><b>{entry["step_samples"]}</b><span>Schritt-Messungen</span></div>'
            f'<div class="metric"><b>{entry["step_types"]}</b><span>Verschiedene Schritte</span></div>'
        )
        parts = []
        for item in entry["workflows"]:
            runner_text = ", ".join(
                f"{escape(name)} ({count})" for name, count in item["runners"]
            )
            ready = ("Prognose möglich" if item["prognosis_ready"] else
                     f"Noch {3 - item['runs']} Messungen bis zur ersten Prognose")
            parts.append(
                f'<div class="workflow"><h3>{escape(item["name"])}</h3>'
                f'<div class="muted">{item["runs"]} erfolgreiche Läufe · {escape(ready)}</div>'
                '<div class="stats">'
                f'<div class="metric"><b>{duration(item["median_seconds"])}</b><span>Typische Gesamtdauer</span></div>'
                f'<div class="metric"><b>{duration(item["median_queue_seconds"])}</b><span>Typische Wartezeit</span></div>'
                f'<div class="metric"><b>{duration(item["min_seconds"])} – {duration(item["max_seconds"])}</b><span>Bisherige Spannweite</span></div>'
                f'</div><small>Runner: {runner_text or "noch unbekannt"}</small></div>'
            )
        reset_at = reset_description(history, entry["repository"])
        if not parts:
            parts.append('<p class="empty">Noch keine vollständigen erfolgreichen '
                         'Workflow-Messungen. Der Monitor lernt bei regulären Builds.</p>')
        if reset_at:
            parts.append(f'<p class="muted"><small>Zuletzt zurückgesetzt: {reset_at}</small></p>')
        parts.append(
            '<details><summary>Lerndaten dieses Repositories zurücksetzen</summary>'
            '<p class="muted">Löscht nur die zu diesem Repository gehörenden Zeitmessungen. '
            'Frühere Läufe werden nicht erneut eingelesen.</p>'
            + reset_form(entry["repository"], "Lerndaten zurücksetzen", csrf)
            + '</details>'
        )
        cards.append(f'<section class="card"><h2>{name}</h2>'
                     f'<div class="stats">{metrics}</div>{"".join(parts)}</section>')
    if not cards:
        cards = ['<section class="card"><p>Aktuell ist kein Repository zur Überwachung ausgewählt. '
                 'Wähle oben Repositories aus GitHub aus.</p></section>']
    toast = ('<p class="note">Zurücksetzung vorgemerkt. Der Monitor führt sie im '
             'nächsten Prüfzyklus aus. Danach diese Seite aktualisieren.</p>'
             if queued else '')
    html = (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>GitHub Build Monitor – Lernstatistik</title>'
        f'<style>{STYLES}</style></head><body>'
        '<header><h1>📊 Build-Lernstatistik</h1>'
        '<p class="muted">Lokale Erfahrungswerte je Repository und Workflow. '
        'Nur erfolgreich abgeschlossene Builds fließen in die Prognose ein. '
        '<a href="./">↻ Anzeige aktualisieren</a></p></header>'
        + toast + repositories_html + "".join(cards)
        + '<section class="card"><h2>Alle Lerndaten zurücksetzen</h2>'
        '<p class="muted">Setzt die gesammelten Zeiten aller Repositories zurück, '
        'ohne GitHub-Token, Einstellungen, Sensoren oder Live-Aktivitäten zu löschen. '
        'Alte Builds werden nicht nachträglich wieder als neue Messungen übernommen.</p>'
        + reset_form("all", "Alle Lerndaten löschen", csrf)
        + '</section><p class="muted"><small>Die Daten bleiben lokal in Home Assistant '
        'und werden nicht an einen zusätzlichen Dienst übertragen.</small></p>'
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
        page = render(self.server.data_dir, self.server.csrf, queued=queued,
                      repositories_html=section)
        return self.respond(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if not self.trusted():
            return self.respond(403, b"Only Home Assistant Ingress is allowed.")
        route = urlsplit(self.path).path
        if route not in ("/reset", "/repositories"):
            return self.respond(404, b"Not found")
        if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            return self.respond(415, b"Unsupported content type")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, b"Invalid content length")
        max_length = 100_000 if route == "/repositories" else 2048
        if length < 1 or length > max_length:
            return self.respond(413, b"Invalid body length")
        fields = parse_qs(self.rfile.read(length).decode("utf-8", "strict"))
        if fields.get("csrf") != [self.server.csrf]:
            return self.respond(403, b"Invalid CSRF token")
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
    # HA Supervisor's documented ingress proxy IP. No direct LAN access.
    server.allowed_peers = ({"172.30.32.2"} if allowed_peers is None
                            else allowed_peers)
    Thread(target=server.serve_forever, name="learning-ui", daemon=True).start()
    return server
