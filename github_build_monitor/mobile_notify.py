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
    """Backward-compatible primary notification target."""
    return next(iter(effective_services(options, data_dir)), "")



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



def effective_services(options: dict, data_dir: Path) -> list[str]:
    """Read new list, v0.1.7 saved single value, or native HA option."""
    try:
        saved = json.loads(selection_file(data_dir).read_text(encoding="utf-8"))
        if isinstance(saved, dict) and isinstance(saved.get("services"), list):
            return validated_services(saved["services"])
        if isinstance(saved, dict) and isinstance(saved.get("service"), str):
            return [normalize(saved["service"])]
    except (OSError, ValueError, TypeError):
        pass
    original = options.get("live_activity_notify_service") or ""
    try:
        return [normalize(original)] if original else []
    except ValueError:
        return []


def validated_services(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > 50:
        raise ValueError("Ungültige Geräteauswahl.")
    result = []
    for name in values:
        target = normalize(name)
        if target in result:
            raise ValueError("Gerät doppelt ausgewählt.")
        result.append(target)
    return result


def saved_aliases(data_dir: Path) -> dict[str, str]:
    try:
        raw = json.loads(selection_file(data_dir).read_text(encoding="utf-8"))
        aliases = raw.get("aliases", {})
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
    if not isinstance(aliases, dict):
        return {}
    result = {}
    for service, name in aliases.items():
        try:
            normalized = normalize(service)
        except (ValueError, TypeError):
            continue
        if isinstance(name, str) and 0 < len(name.strip()) <= 48:
            result[normalized] = name.strip()
    return result


def save_services(data_dir: Path, services: list[str],
                  aliases: dict[str, str] | None = None) -> None:
    """Only selection + display names are stored, never Supervisor credentials."""
    chosen = validated_services(services)
    names = saved_aliases(data_dir) if aliases is None else {}
    if aliases is not None:
        for service, name in aliases.items():
            key = normalize(service)
            if not isinstance(name, str) or len(name) > 48:
                raise ValueError("Ungültiger Anzeigename.")
            if name.strip():
                names[key] = name.strip()
    file = selection_file(data_dir)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + ".tmp")
    tmp.write_text(json.dumps({"services": chosen, "aliases": names},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, file)


def friendly_label(service: str) -> str:
    """Turn machine IDs into legible labels without guessing another person's name."""
    words = normalize(service).removeprefix("mobile_app_").split("_")
    replacements = {
        "iphone": "iPhone", "ipad": "iPad", "ios": "iOS",
        "imac": "iMac", "macbook": "MacBook", "pixel": "Pixel",
        "android": "Android", "von": "von", "der": "der", "und": "und",
    }
    return " ".join(replacements.get(part.casefold(), part.capitalize())
                    for part in words)
