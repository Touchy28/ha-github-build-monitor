"""Repository discovery and selected monitor targets.

Discover repositories with the user's existing fine-grained GitHub token.
Persist *only* selected repository names in the add-on's private /data path.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core import repositories

_SELECTION_FILE = "monitored_repositories.json"
_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def selection_file(data_dir: Path) -> Path:
    return data_dir / _SELECTION_FILE


def effective_repositories(options: dict, data_dir: Path) -> list[str]:
    """Saved GUI choice wins; legacy options are used only before first save.

    An empty saved list means 'watch nothing' (not 'fall back to defaults').
    """
    try:
        saved = json.loads(selection_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return repositories(options)
    if isinstance(saved, dict) and isinstance(saved.get("repositories"), list):
        return repositories(saved)
    return repositories(options)


def store_selection(data_dir: Path, names: list[str]) -> None:
    valid = repositories({"repositories": names})
    if len(valid) != len(names):
        raise ValueError("Invalid or duplicate repository names")
    target = selection_file(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps({"repositories": valid}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    os.replace(temporary, target)


def fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def discover(token: str, *, max_pages: int = 10) -> list[dict]:
    """List token-authorized repositories through GitHub, read only.

    /user/repos accepts fine-grained PATs with Metadata:read.
    Requests are made server-side, never in the phone browser.
    """
    if not token or not isinstance(token, str):
        raise ValueError("GitHub-Token fehlt in den App-Optionen.")
    if len(token) > 2000:
        raise ValueError("Ungültiges Token-Format.")
    result: dict[str, dict] = {}
    for page in range(1, max_pages + 1):
        url = "https://api.github.com/user/repos?per_page=100&sort=full_name&direction=asc&page=" + str(page)
        req = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + token,
            "User-Agent": "HA-GitHub-Build-Monitor/0.1.5",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urlopen(req, timeout=12) as response:
                payload = json.loads(response.read(2_000_000))
        except HTTPError as exc:
            if exc.code == 401:
                raise ValueError("GitHub lehnt das Token ab (HTTP 401).") from None
            if exc.code == 403:
                raise ValueError("GitHub verweigert den Zugriff (HTTP 403). Token-Berechtigung und API-Limit prüfen.") from None
            raise ValueError("GitHub-Repository-Liste nicht verfügbar (HTTP " + str(exc.code) + ").") from None
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError("GitHub ist derzeit nicht erreichbar. Auswahl bleibt unverändert.") from None
        if not isinstance(payload, list):
            raise ValueError("GitHub hat kein gültiges Repository-Verzeichnis geliefert.")
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            full = entry.get("full_name")
            if not isinstance(full, str) or not _REPO_NAME.fullmatch(full):
                continue
            # Keep visible metadata for meaningful selection.
            result[full.casefold()] = {
                "full_name": full,
                "private": bool(entry.get("private")),
                "description": str(entry.get("description") or "")[:160],
                "archived": bool(entry.get("archived")),
            }
        if len(payload) < 100:
            break
    else:
        # Never claim completeness when the account exceeds the page cap.
        raise ValueError("Mehr als 1.000 Repositories gefunden. Bitte Administrator informieren.")
    return sorted(result.values(), key=lambda item: item["full_name"].casefold())
