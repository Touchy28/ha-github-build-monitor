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
                  csrf: str, message: str = "", error: str = "",
                  aliases: dict[str, str] | None = None) -> str:
    from repo_selection import display_name
    aliases = aliases or {}
    parts = [
        '<details class="card repo-picker" id="repositories"',
        ' open' if (message or error) else '',
        '><summary class="fold-title"><span>📁 Repositories auswählen</span>'
        f'<span class="fold-count">{len(current)} aktiv</span></summary>',
        '<div class="fold-body">',
        '<p class="muted">Wähle die GitHub-Projekte für die Überwachung aus. '
        'Bei Bedarf kannst du einen kurzen Anzeigenamen festlegen.</p>',
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
                         ", ".join(escape(display_name(repo, aliases)) for repo in current) + "</p>")
        parts.append("</div></details>")
        return "".join(parts)
    current_set = {item.casefold() for item in current}
    choices = []
    for repo in available:
        name = repo["full_name"]
        custom = aliases.get(name.casefold(), "")
        marked = " checked" if name.casefold() in current_set else ""
        flags = " · ".join(flag for flag, enabled in (
            ("🔒 Privat", repo.get("private")), ("Archiviert", repo.get("archived"))
        ) if enabled)
        description = repo.get("description") or ""
        choices.append(
            '<div class="selection-choice">'
            '<label class="selection-choice-label">'
            f'<input type="checkbox" name="repository" value="{escape(name, quote=True)}"{marked}>'
            '<span class="selection-choice-details">'
            f'<strong>{escape(custom or name.split("/")[-1])}</strong>'
            f'<small>{escape(name)}{(" · " + escape(flags)) if flags else ""}</small>'
            + (f'<small>{escape(description)}</small>' if description else "")
            + '</span></label>'
            f'<input type="hidden" name="listed" value="{escape(name, quote=True)}">'
            '<label class="selection-alias-label">Anzeigename / Abkürzung (optional)'
            f'<input type="text" name="alias" maxlength="32" value="{escape(custom, quote=True)}"'
            f' placeholder="{escape(name.split("/")[-1], quote=True)}"></label>'
            '</div>'
        )
    selected = sum(1 for repo in available
                   if repo["full_name"].casefold() in current_set)
    parts += [
        f'<p class="muted"><strong>{selected} von {len(available)}</strong> '
        'Repositories ausgewählt</p>',
        '<form action="repositories" method="post">',
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">',
        '<div class="selection-list">',
        "".join(choices) or "<p>Für diesen Token wurden keine Repositories gefunden.</p>",
        '</div><p class="muted">Anzeigenamen ändern nur die Darstellung, '
        'nicht GitHub-Adressen, Sensoren oder bereits gelernte Zeiten.</p>',
        '<button type="submit">Auswahl speichern</button>',
        '</form></div></details>',
    ]
    return "".join(parts)
