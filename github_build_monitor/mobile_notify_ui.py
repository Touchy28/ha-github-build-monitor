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
                  override_active: bool = False) -> str:
    current = ""
    try:
        current = normalize(service) if service else ""
    except ValueError:
        current = ""
    options: list[str] = []
    if services is not None:
        for item in services:
            try:
                key = normalize(item)
            except ValueError:
                continue
            selected = " selected" if key == current and override_active else ""
            options.append(
                f'<option value="{escape(key, quote=True)}"{selected}>'
                f'{escape(friendly_label(key))} · {escape("notify." + key)}</option>'
            )
    current_label = escape(current) if current else "Nicht eingerichtet"
    body = [
        '<div class="notify-picker">',
        '<h3>📱 Zielgerät für Live-Aktivitäten</h3>',
        f'<p class="muted">Aktuell: <code>{current_label}</code></p>',
        '<p class="muted">Die Liste stammt direkt aus Home Assistant. '
        'Es werden ausschließlich Companion-App-Benachrichtigungsdienste angeboten.</p>',
    ]
    if error:
        body.append(f'<p class="warning" role="alert">{escape(error)}</p>')
    if message:
        body.append(f'<p class="note">{escape(message)}</p>')
    if services is None:
        body.append('<p class="muted">Die bestehende Einstellung bleibt erhalten.</p>')
    elif not services:
        body.append(
            '<p class="warning">Keine <code>notify.mobile_app_*</code>-Dienste gefunden. '
            'Prüfe die Home-Assistant-Companion-App und die Push-Berechtigung.</p>'
        )
    else:
        if current and current not in services:
            body.append(
                '<p class="warning">Der bisherige Dienst ist aktuell nicht in der '
                'HA-Diensteliste vorhanden. Er wird nicht automatisch geändert.</p>'
            )
        body += [
            '<form action="notify-service" method="post">',
            f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">',
            '<label for="mobile-target"><strong>Benachrichtigungsziel auswählen</strong></label>',
            '<select id="mobile-target" name="service" required>',
            '<option value="__native__"' + ('' if override_active else ' selected')
            + '>Wert aus HA-App-Konfiguration verwenden</option>',
            "".join(options),
            '</select>',
            '<div class="picker-buttons"><button type="submit">Gerät speichern</button></div>',
            '</form>',
        ]
    body.append(
        '<p class="muted"><small>Die Geräteauswahl aus der Weboberfläche hat Vorrang '
        'vor dem alten Textfeld in der HA-App-Konfiguration. '
        'Du kannst das Ziel später jederzeit ändern oder auf den HA-Wert zurückschalten.</small></p></div>'
    )
    return "".join(body)
