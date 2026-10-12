"""Home Assistant GitHub Actions Build Monitor.

Never starts or registers runners; requires only GitHub Actions read permission
and HA's limited homeassistant_api connection.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core import (activity_tag, learn, notify_service, repositories, sensor_id,
                  snapshot)

API_URL = "https://api.github.com"
HA_URL = "http://supervisor/core/api"
DATA_DIR = Path(os.environ.get("BUILD_MONITOR_DATA_DIR", "/data"))


def log(message: str) -> None:
    print("[github-build-monitor] " + message, flush=True)


def read_json(path: Path, default: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def api_call(url: str, *, token: str = "", method: str = "GET",
             data: dict | None = None, timeout: int = 20) -> dict:
    headers = {"User-Agent": "HA-GitHub-Build-Monitor/0.1.1",
               "Accept": "application/vnd.github+json"}
    if url.startswith(API_URL):
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token:
            headers["Authorization"] = "Bearer " + token
    elif url.startswith(HA_URL):
        headers["Authorization"] = "Bearer " + token
    else:
        raise ValueError("Unrecognized API host")
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
        return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raise RuntimeError(f"API HTTP {exc.code} ({url.split('?')[0]})") from None
    except URLError as exc:
        raise RuntimeError(f"API connection failed: {exc.reason}") from None


def runs_for(repo: str, github_token: str) -> list[dict]:
    path = quote(repo, safe="/")
    response = api_call(f"{API_URL}/repos/{path}/actions/runs?per_page=20",
                        token=github_token)
    return response.get("workflow_runs", [])


def jobs_for(repo: str, run_id: int, github_token: str) -> list[dict]:
    path = quote(repo, safe="/")
    response = api_call(f"{API_URL}/repos/{path}/actions/runs/{int(run_id)}/jobs?per_page=100",
                        token=github_token)
    return response.get("jobs", [])


def set_sensor(repo: str, value: dict, ha_token: str) -> None:
    entity_id = sensor_id(repo)
    data = {
        "state": value.get("state", "unknown"),
        "attributes": {
            "friendly_name": f"GitHub Build {repo}",
            "icon": "mdi:github",
            **{key: item for key, item in value.items() if key != "state"}
        }
    }
    api_call(f"{HA_URL}/states/{entity_id}", token=ha_token, method="POST", data=data)


def notify(service: str, ha_token: str, payload: dict) -> None:
    name = notify_service(service)
    api_call(f"{HA_URL}/services/notify/{name}", token=ha_token,
             method="POST", data=payload)


def activity_payload(run: dict, progress: dict, repo: str) -> dict:
    status = str(run.get("status") or "")
    conclusion = str(run.get("conclusion") or "")
    if status == "completed":
        msg = ("Erfolgreich abgeschlossen" if conclusion == "success"
               else f"Beendet: {conclusion or 'unbekannt'}")
    else:
        step = progress.get("current_step") or progress.get("current_job")
        msg = f"{step or status} · ca. {progress['progress_percent']} %"
    return {
        "title": f"GitHub · {repo.split('/')[-1]}"[:64],
        "message": msg[:150],
        "data": {
            "tag": activity_tag(repo, run["id"]),
            "live_update": True,
            "progress": int(progress["progress_percent"]),
            "progress_max": 100,
            "notification_icon": "mdi:github",
            "notification_icon_color": "#35A16B" if status != "completed"
              or conclusion == "success" else "#DF6B3B",
            "alert_once": True,
        },
    }


def clear_payload(repo: str, run_id: int) -> dict:
    return {"message": "clear_notification",
            "data": {"tag": activity_tag(repo, run_id)}}


def is_active(run: dict) -> bool:
    return run.get("status") != "completed"


def monitor_repository(repo: str, github_token: str, ha_token: str,
                       config: dict, state: dict, history: dict, now: float) -> None:
    recent = runs_for(repo, github_token)
    relevant = [r for r in recent if is_active(r)][:6]
    if not relevant and recent:
        relevant = [recent[0]]
    jobs_cache: dict[int, list[dict]] = {}
    results: dict[int, dict] = {}
    recent_by_id = {int(r["id"]): r for r in recent if r.get("id") is not None}
    active_count = sum(1 for r in recent if is_active(r))
    for run in relevant:
        run_id = int(run["id"])
        jobs = jobs_for(repo, run_id, github_token)
        jobs_cache[run_id] = jobs
        learn(repo, run, jobs, history)
        results[run_id] = snapshot(repo, run, jobs, history, now)
    primary = next((r for r in relevant if is_active(r)), relevant[0] if relevant else None)
    if primary is None:
        set_sensor(repo, {"repository": repo, "state": "idle",
                          "progress_percent": 0, "active_run_count": 0}, ha_token)
    else:
        data = dict(results[int(primary["id"])])
        data["active_run_count"] = active_count
        # Progress never moves backward within the same run even when dynamic jobs are added.
        previous = state.setdefault("sensor_progress", {}).get(repo, {})
        if previous.get("run_id") == data["run_id"] and is_active(primary):
            data["progress_percent"] = max(data["progress_percent"],
                                           int(previous.get("percent", 0)))
        state["sensor_progress"][repo] = {
            "run_id": data["run_id"], "percent": data["progress_percent"]}
        set_sensor(repo, data, ha_token)
        label = f"{data['state']} {data['progress_percent']}%"
        last_label = state.setdefault("log_state", {}).get(repo)
        if last_label != label:
            log(f"{repo}: {data['workflow']} #{data['run_id']} {label}"
                  + f" ({data['completed_steps']}/{data['total_steps']} steps)")
            state["log_state"][repo] = label

    if not config.get("live_activity_enabled"):
        return
    service = config.get("live_activity_notify_service", "")
    notify_service(service)  # never accept an arbitrary HA service
    activities = state.setdefault("activities", {}).setdefault(repo, {})
    for run in relevant:
        if not is_active(run):
            continue
        run_id = str(run["id"])
        data = results[int(run_id)]
        old = activities.get(run_id) or {}
        # Never allow a live bar to move backward for the same run.
        data["progress_percent"] = max(data["progress_percent"], int(old.get("percent", 0)))
        step = data.get("current_step") or data.get("current_job") or ""
        if (not old
                or data["progress_percent"] - int(old.get("percent", 0)) >= 2
                or step != old.get("step")
                or now - float(old.get("sent_at", 0)) >= 180):
            notify(service, ha_token, activity_payload(run, data, repo))
            activities[run_id] = {"percent": data["progress_percent"],
                                  "step": step, "sent_at": now}
    for run_id, old in list(activities.items()):
        if "finished_at" in old:
            if now - float(old["finished_at"]) >= 30:
                notify(service, ha_token, clear_payload(repo, int(run_id)))
                del activities[run_id]
            continue
        run = recent_by_id.get(int(run_id))
        if run is not None and is_active(run):
            continue
        if run is None:
            # No longer in GitHub's last 20 runs: end stale notification.
            notify(service, ha_token, clear_payload(repo, int(run_id)))
            del activities[run_id]
            continue
        rid = int(run_id)
        if rid not in results:
            jobs = jobs_cache.get(rid) or jobs_for(repo, rid, github_token)
            learn(repo, run, jobs, history)
            results[rid] = snapshot(repo, run, jobs, history, now)
        notify(service, ha_token, activity_payload(run, results[rid], repo))
        old["finished_at"] = now


def main() -> None:
    config = read_json(DATA_DIR / "options.json", {})
    repos = repositories(config)
    if not repos:
        log("No valid repositories configured; set owner/repository in app options")
        return
    token = str(config.get("github_api_token") or "")
    ha_token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not ha_token:
        log("Missing SUPERVISOR_TOKEN; enable homeassistant_api")
        return
    interval = max(30, min(300, int(config.get("poll_interval_seconds", 60))))
    if config.get("live_activity_enabled"):
        try:
            notify_service(config.get("live_activity_notify_service", ""))
        except ValueError as exc:
            log(f"Live Activity disabled until configured: {exc}")
            config["live_activity_enabled"] = False
    log(f"Started: {len(repos)} repositories, poll every {interval}s,"
        f" mobile notifications {'enabled' if config.get('live_activity_enabled') else 'disabled'}")
    state_file = DATA_DIR / "monitor_state.json"
    history_file = DATA_DIR / "monitor_history.json"
    state = read_json(state_file, {})
    history = read_json(history_file, {})
    while True:
        now = time.time()
        for repo in repos:
            try:
                monitor_repository(repo, token, ha_token, config, state, history, now)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                log(f"{repo}: {exc}")
                try:
                    set_sensor(repo, {"repository": repo, "state": "unavailable",
                                      "error": str(exc)}, ha_token)
                except Exception:
                    pass
            finally:
                write_json(state_file, state)
                write_json(history_file, history)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped")
        sys.exit(0)
