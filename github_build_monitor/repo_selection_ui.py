"""Ingress repository selection UI: API token never reaches the browser."""
from __future__ import annotations

from html import escape
from threading import Lock
from time import monotonic
from urllib.parse import urlencode

from repo_selection import discover, effective_repositories, fingerprint

CACHE_TTL = 600


def get_available(server, token: str, *, refresh: bool = False):
    """Return current token's list, or a safe error message."""
    if not token:
        return None, "Bitte zuerst den GitHub-Token in der App-Konfiguration speichern."
    sha = fingerprint(token)
    with server.repositories_lock:
        cache = server.repositories_cache
        if (not refresh and cache.get("sha") == sha
                and monotonic() - cache.get("time", -10**9) < CACHE_TTL):
            return cache["list"], None
        try:
            available = discover(token)
        except ValueError as exc:
            server.repositories_cache = {}
            return None, str(exc)
        server.repositories_cache = {
            "sha": sha, "time": monotonic(), "list": available,
        }
    return available, None


def cached_available(server, token: str):
    cache = server.repositories_cache
    if (not token or cache.get("sha") != fingerprint(token)
            or monotonic() - cache.get("time", -10**9) >= CACHE_TTL):
        return None
    return cache["list"]


def selector_html(current: list[str], available: list[dict] | None,
                  csrf: str, message: str = "", error: str = "") -> str:
    parts = [
        '<section class="card" id="repositories">',
        '<h2>🐙 Repositories auswählen</h2>',
        '<p class="muted">GitHub liest mit dem vorhandenen Token alle für ihn '
        'sichtbaren Repositories ein. Du entscheidest, welche überwacht werden. '
        'Der Token selbst bleibt in Home Assistant.</p>',
    ]
    if message:
        parts.append(f'<p class="note">{escape(message)}</p>')
    if error:
        parts.append(f'<p class="warning" role="alert">{escape(error)}</p>')
    parts.append(
        '<form action="./" method="get" style="margin-bottom:12px">'
        '<button class="neutral" type="submit" name="refresh" value="1">'
        '↻ Repository-Liste von GitHub aktualisieren</button></form>'
    )
    if available is None:
        if current:
            parts.append("<p><strong>Bisher überwacht:</strong> " +
                         ", ".join(escape(repo) for repo in current) + "</p>")
        parts.append("</section>")
        return "".join(parts)
    current_set = {item.casefold() for item in current}
    choices = []
    for repo in available:
        name = repo["full_name"]
        marked = " checked" if name.casefold() in current_set else ""
        private = " 🔒 Privat" if repo.get("private") else ""
        archived = " · Archiviert" if repo.get("archived") else ""
        description = repo.get("description") or ""
        sub = (f'<small>{escape(description)}</small>' if description else "")
        choices.append(
            '<label class="repository-choice">'
            f'<input type="checkbox" name="repository" value="{escape(name, quote=True)}"{marked}>'
            '<span class="repository-details">'
            f'<strong>{escape(name)}</strong>'
            f'<small>{escape(private + archived)}</small>'
            + sub + '</span></label>'
        )
    selected = sum(1 for repo in available
                   if repo["full_name"].casefold() in current_set)
    parts += [
        f'<p class="muted"><strong>{selected} von {len(available)}</strong> '
        'Repositories ausgewählt</p>',
        '<form action="repositories" method="post">',
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">',
        '<div class="repository-list">',
        "".join(choices) or "<p>Für diesen Token wurden keine Repositories gefunden.</p>",
        '</div><p class="muted">Du kannst die Auswahl später jederzeit ändern. '
        'Nicht ausgewählte Projekte werden nicht mehr abgefragt; '
        'bereits gelernte Zeiten bleiben erhalten.</p>',
        '<button type="submit">Auswahl speichern</button>',
        '</form></section>',
    ]
    return "".join(parts)
