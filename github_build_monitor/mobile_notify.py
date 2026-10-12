"""Discover eligible Home Assistant mobile notification services.

Read-only enumeration of HA Core services; selection is stored in an app-private
file rather than writing Supervisor-managed /data/options.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core import notify_service

HA_SERVICES_URL = "http://supervisor/core/api/services"
_SELECTION_FILENAME = "selected_mobile_notify_service.json"


def normalize(service: str) -> str:
    """Canonical form: mobile_app_<device> (without optional notify. prefix)."""
    return notify_service(service)


def selection_file(data_dir: Path) -> Path:
    return data_dir / _SELECTION_FILENAME


def clear_service(data_dir: Path) -> None:
    """Return control to the existing Home Assistant add-on option."""
    selection_file(data_dir).unlink(missing_ok=True)


def effective_service(options: dict, data_dir: Path) -> str:
    """A saved web UI choice takes priority; otherwise old HA options win."""
    existing = str(options.get("live_activity_notify_service") or "")
    try:
        saved = json.loads(selection_file(data_dir).read_text(encoding="utf-8"))
        choice = saved.get("service")
        if not isinstance(choice, str):
            return existing
        return normalize(choice)
    except (ValueError, TypeError, OSError, AttributeError):
        return existing


def save_service(data_dir: Path, service: str) -> None:
    """Save only the whitelisted HA mobile notification service name."""
    clean = normalize(service)
    target = selection_file(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps({"service": clean}, ensure_ascii=False),
                         encoding="utf-8")
    os.replace(temporary, target)


def parse_services(payload: object) -> list[str]:
    """HA returns [{domain:'notify', services:{service_name:metadata}}].

    Accept the legacy list shape too. Never offer arbitrary notify actions.
    """
    if not isinstance(payload, list):
        raise ValueError("Unerwartete Antwort von Home Assistant.")
    found: set[str] = set()
    for domain in payload:
        if not isinstance(domain, dict) or domain.get("domain") != "notify":
            continue
        values = domain.get("services") or {}
        names = values if isinstance(values, (list, dict)) else []
        for name in names:
            if not isinstance(name, str):
                continue
            try:
                found.add(normalize(name))
            except ValueError:
                continue
    return sorted(found)


def discover_mobile_services(ha_token: str) -> list[str]:
    if not ha_token:
        raise ValueError("Kein Home-Assistant-API-Zugriff verfügbar.")
    request = Request(HA_SERVICES_URL, headers={
        "Authorization": "Bearer " + ha_token,
        "Accept": "application/json",
        "User-Agent": "HA-GitHub-Build-Monitor/0.1.7",
    }, method="GET")
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read(2_000_000))
    except HTTPError as exc:
        raise ValueError(f"Home Assistant meldet HTTP {exc.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Home Assistant ist vorübergehend nicht erreichbar.") from None
    except (ValueError, TypeError):
        raise ValueError("Die Home-Assistant-Diensteliste konnte nicht gelesen werden.") from None
    return parse_services(payload)


def friendly_label(service: str) -> str:
    """Human-readable label, retaining the original service ID in the menu."""
    clean = normalize(service)
    suffix = clean.removeprefix("mobile_app_")
    return suffix.replace("_", " ").strip().title()
