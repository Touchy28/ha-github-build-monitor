"""Native-HTML selector for Home Assistant mobile notification services."""
from __future__ import annotations

from html import escape
from time import monotonic

from mobile_notify import discover_mobile_services, effective_service, friendly_label, normalize

CACHE_SECONDS = 90


def get_services(server, *, refresh: bool = False) -> tuple[list[str] | None, str]:
    """Read from HA Core and avoid repeated fetches on every page refresh."""
    with server.mobile_services_lock:
        cache = server.mobile_services_cache
        if (not refresh and cache.get("time") is not None
                and monotonic() - cache["time"] < CACHE_SECONDS):
            return list(cache["services"]), ""
        try:
            services = discover_mobile_services(server.ha_token)
        except ValueError as exc:
            # Do not destroy the previously saved selection.
            return None, str(exc)
        server.mobile_services_cache = {
            "time": monotonic(),
            "services": list(services),
        }
        return services, ""


def cached_services(server) -> list[str] | None:
    cache = server.mobile_services_cache
    if (cache.get("time") is None
            or monotonic() - cache["time"] >= CACHE_SECONDS):
        return None
    return list(cache["services"])


def selector_html(service: str, services: list[str] | None, csrf: str,
                  message: str = "", error: str = "",
                  override_active: bool = False,
                  selected: list[str] | None = None,
                  aliases: dict[str, str] | None = None) -> str:
    """Compact multi-device selector with editable display names.

    Each displayed row has both a checkbox and an optional friendly name.
    Hidden listed targets make submitted name mapping unambiguous even when
    only some checkboxes are checked (native HTML, no JavaScript).
    """
    selected = [service] if selected is None and service else (selected or [])
    chosen = set(selected)
    aliases = aliases or {}
    body = [
        '<div class="notify-picker">',
        f'<p class="muted"><strong>{len(chosen)} ausgewählt</strong>. '
        'Du kannst mehrere Geräte benachrichtigen und die Namen anpassen.</p>',
        '<form method="get" action="./">'
        '<button type="submit" class="neutral" name="refresh_mobile" value="1">'
        '↻ Geräte aus Home Assistant neu einlesen</button></form>'
    ]
    if error:
        body.append(f'<p class="warning" role="alert">{escape(error)}</p>')
    if message:
        body.append(f'<p class="note">{escape(message)}</p>')
    if services is None:
        body.append('<p class="muted">Die bestehende Einstellung bleibt erhalten.</p>')
    elif not services:
        body.append('<p class="warning">Keine Companion-App-Geräte gefunden. '
                    'Prüfe die registrierten Benachrichtigungsdienste.</p>')
    if services:
        body.extend([
            '<form action="notify-service" method="post">',
            f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">',
            '<div class="selection-list">'
        ])
        for item in services:
            try:
                key = normalize(item)
            except ValueError:
                continue
            title = aliases.get(key) or friendly_label(key)
            checked = " checked" if key in chosen else ""
            body.extend([
                '<div class="selection-choice">',
                f'<label class="selection-choice-label"><input type="checkbox" name="target" '
                f'value="{escape(key, quote=True)}"{checked}>',
                f'<span class="selection-choice-details"><strong>{escape(title)}</strong><small>notify.{escape(key)}</small>'
                '</span></label>',
                f'<input type="hidden" name="listed" value="{escape(key, quote=True)}">',
                '<label class="selection-alias-label">Anzeigename (optional)',
                f'<input type="text" name="alias" maxlength="48" '
                f'value="{escape(aliases.get(key, ""), quote=True)}" '
                f'placeholder="{escape(friendly_label(key), quote=True)}"></label>',
                '</div>'
            ])
        body.extend([
            '</div><p class="muted">Nicht gewählte Geräte erhalten keine '
            'neuen Live-Aktivitäten. Beim Abwählen wird eine bestehende '
            'Aktivität dort beendet.</p>',
            '<button type="submit">Geräteauswahl speichern</button></form>'
        ])
        missing = chosen - set(services)
        if missing:
            body.append('<p class="warning">Ein bisher gewähltes Gerät ist in '
                        'Home Assistant nicht mehr registriert: ' +
                        ", ".join(escape(name) for name in sorted(missing)) + '</p>')
    if override_active:
        body.append(
            '<form action="notify-service" method="post">'
            f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
            '<button class="neutral" type="submit" name="use_native" value="1">'
            'Wert aus HA-App-Konfiguration verwenden</button></form>'
        )
    body.append('<p class="muted"><small>Gerätenamen dienen ausschließlich der '
                'Anzeige. Der Versand erfolgt weiterhin an die technischen '
                'Home-Assistant-Dienste.</small></p></div>')
    return "".join(body)
