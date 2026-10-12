"""Home Assistant GitHub Actions Build Monitor.

Never starts or registers runners; requires only GitHub Actions read permission
and HA's limited homeassistant_api connection.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from core import (activity_tag, history_key, learn, notify_service, repositories,
                  sensor_id, snapshot, timestamp)
from forecast import observe, predict, workflow_key
from learning_store import learning_allowed, reset_history
from learning_ui import start as start_learning_ui
from mobile_notify import effective_service, effective_services
from repo_selection import effective_repositories, repository_aliases, display_name

API_URL = "https://api.github.com"
HA_URL = "http://supervisor/core/api"
DATA_DIR = Path(os.environ.get("BUILD_MONITOR_DATA_DIR", "/data"))

# A successful HA notify call confirms acceptance by HA, not display on iOS.
# Keep finishing and clearing separate: quiet iOS pushes may be delayed, so
# a single clear can arrive before a late completion update and be undone.
FINAL_ACTIVITY_UPDATES = 3
FINAL_ACTIVITY_RETRY_SECONDS = 60
FINAL_ACTIVITY_MIN_VISIBLE_SECONDS = 180
FINAL_ACTIVITY_CLEAR_GRACE_SECONDS = 90
FINAL_ACTIVITY_CLEAR_ATTEMPTS = 3
FINAL_ACTIVITY_CLEAR_RETRY_SECONDS = 60


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
    jobs = []
    # Match v0.1.0: workflows can have more than 100 jobs.
    for page in range(1, 6):
        response = api_call(
            f"{API_URL}/repos/{path}/actions/runs/{int(run_id)}/jobs?per_page=100&page={page}",
            token=github_token)
        batch = response.get("jobs") or []
        if not isinstance(batch, list):
            break
        jobs.extend(job for job in batch if isinstance(job, dict))
        if len(batch) < 100:
            break
    return jobs


def set_sensor(repo: str, value: dict, ha_token: str) -> None:
    entity_id = sensor_id(repo)
    raw_state = str(value.get("state") or "unknown")
    outcome = str(value.get("conclusion") or "")
    # Preserve v0.1.0 state names used by existing dashboard automations.
    if raw_state == "completed":
        state = {"success": "success", "failure": "failure",
                 "timed_out": "failure", "cancelled": "cancelled"}.get(outcome, "completed")
    elif raw_state == "in_progress":
        state = "running"
    elif raw_state in ("queued", "waiting", "pending", "requested"):
        state = "queued"
    else:
        state = raw_state
    attrs = {key: item for key, item in value.items() if key != "state"}
    # Older dashboards read the following attributes directly.
    attrs.update({
        "status": state,
        "progress": value.get("progress_percent", 0),
        "steps_done": value.get("completed_steps", 0),
        "steps_total": value.get("total_steps", 0),
        "job": value.get("current_job", ""),
        "step": value.get("current_step", ""),
        "runner": value.get("runner_name", "") or "",
        "eta_seconds": value.get("estimated_remaining_seconds"),
        "active_runs": value.get("active_run_count", 0),
        "url": value.get("run_url", ""),
        "run_number": value.get("run_number"),
        "jobs": value.get("jobs", 0),
        "github_status": raw_state,
        "friendly_name": f"GitHub Runner {repo}",
        "icon": "mdi:github",
    })
    api_call(f"{HA_URL}/states/{entity_id}", token=ha_token, method="POST",
             data={"state": state, "attributes": attrs})


def notify(service: str, ha_token: str, payload: dict) -> None:
    name = notify_service(service)
    api_call(f"{HA_URL}/services/notify/{name}", token=ha_token,
             method="POST", data=payload)


def compact_minutes(seconds: float) -> str:
    """Compact iOS title time: 0–59m or 1h02, without verbose units."""
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    return f"{seconds // 60}m"


def remaining_time_label(run: dict, progress: dict) -> str:
    """Time/status text for the *mutable* iOS message, never its fixed title.

    No historical estimate -> an en dash. Never display elapsed as remaining.
    """
    status = str(run.get("status") or "")
    if status == "completed":
        outcome = str(run.get("conclusion") or "")
        return {"success": "✓", "failure": "Fehler",
                "cancelled": "Abbruch", "timed_out": "Zeitüberschreitung"}.get(
                    outcome, "Beendet")
    step = progress.get("current_step_remaining_seconds")
    entire = progress.get("estimated_remaining_seconds")
    # A workflow cannot finish sooner than the step that is still running.
    if (isinstance(step, (int, float)) and not isinstance(step, bool)
            and isinstance(entire, (int, float)) and not isinstance(entire, bool)
            and step > entire > 0):
        entire = step
    def minutes(value: object) -> str:
        from math import ceil
        return str(ceil(value / 60)) if (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 < value < 8 * 3600) else "–"
    current, total = minutes(step), minutes(entire)
    if current == "–" and total == "–":
        return "Restzeit –"
    return f"≈{current}/{total}m"


def activity_title(run: dict, progress: dict, repo: str,
                   display: str = "", now: float | None = None) -> str:
    """Immutable iOS header: repository alias, workflow and run identity.

    HA Companion iOS sets 'title' at creation; subsequent pushes cannot change
    that title. Estimated remaining time therefore belongs in 'message'.
    """
    name = (display.strip() if isinstance(display, str) else "") or repo.split("/")[-1]
    number = run.get("run_number")
    if isinstance(number, int) and not isinstance(number, bool) and number > 0:
        workflow = str(run.get("name") or "Workflow").strip() or "Workflow"
        if len(workflow) > 18:
            workflow = workflow[:17] + "…"
        identity = f"{workflow} #{number}"
    elif run.get("id") is not None:
        identity = f"Run #{run['id']}"
    else:
        identity = ""
    maximum_name = 12 if identity else 20
    if len(name) > maximum_name:
        name = name[:maximum_name - 1] + "…"
    heading = f"{name} · {identity}" if identity else name
    return heading[:64]


def activity_payload(run: dict, progress: dict, repo: str,
                     display: str = "", now: float | None = None) -> dict:
    status = str(run.get("status") or "")
    conclusion = str(run.get("conclusion") or "")
    label = remaining_time_label(run, progress)
    if status == "completed":
        result = ("Erfolgreich abgeschlossen" if conclusion == "success"
                  else f"Beendet: {conclusion or 'unbekannt'}")
        msg = f"{label} · {result}"
    else:
        step = progress.get("current_step") or progress.get("current_job")
        # Time is first so even a long step name cannot hide the ETA on iOS.
        msg = (f"{label} · {step or status} · "
               f"{progress.get('completed_steps', 0)}/{progress.get('total_steps', 0)} Schritte")
    return {
        "title": activity_title(run, progress, repo, display, now),
        "message": msg[:150],
        "data": {
            "tag": activity_tag(repo, run["id"]),
            "live_update": True,
            "progress": int(progress["progress_percent"]),
            "progress_max": 100,
            "progress_bar_direction": "increasing",
            "critical_text": f"≈{progress['progress_percent']}%" if status != "completed" else label,
            "url": run.get("html_url") or f"https://github.com/{repo}/actions",
            "notification_icon": "mdi:github",
            "notification_icon_color": "#35A16B" if status != "completed"
              or conclusion == "success" else "#DF6B3B",
            # Final updates should use normal push priority, not quiet priority 5.
            "alert_once": status != "completed",
        },
    }


def clear_payload(repo: str, run_id: int) -> dict:
    return {"message": "clear_notification",
            "data": {"tag": activity_tag(repo, run_id)}}


def is_active(run: dict, now: float | None = None) -> bool:
    status = run.get("status")
    if status not in ("queued", "in_progress", "waiting", "pending", "requested"):
        return False
    # Preserve v0.1.0's protection against abandoned queued runs.
    if status != "in_progress":
        created = timestamp(run.get("created_at"))
        reference = time.time() if now is None else now
        if created is not None and reference - created > 8 * 3600:
            return False
    return True


def monitor_repository(repo: str, github_token: str, ha_token: str,
                       config: dict, state: dict, history: dict, now: float) -> None:
    recent = runs_for(repo, github_token)
    # Restore readable names for workflow histories created by v0.1.4.
    workflow_names = history.setdefault("workflow_names", {})
    for known_run in recent:
        if known_run.get("name"):
            workflow_names[workflow_key(repo, known_run)] = str(known_run["name"])
    relevant = [r for r in recent if is_active(r, now)][:6]
    if not relevant and recent:
        relevant = [recent[0]]
    jobs_cache: dict[int, list[dict]] = {}
    results: dict[int, dict] = {}
    recent_by_id = {int(r["id"]): r for r in recent if r.get("id") is not None}
    active_count = sum(1 for r in recent if is_active(r, now))
    for run in relevant:
        run_id = int(run["id"])
        jobs = jobs_for(repo, run_id, github_token)
        jobs_cache[run_id] = jobs
        learn(repo, run, jobs, history)
        observe(repo, run, jobs, history)
        results[run_id] = snapshot(repo, run, jobs, history, now)
        results[run_id].update(predict(repo, run, jobs, history, now))
    # Incrementally collect recent successful runs. Different workflow types
    # have their own histories, and queue time matters as much as build time.
    # Limit to one additional completed run per polling cycle for API economy.
    seen = set(history.get("forecast", {}).get("seen", []))
    for finished in recent:
        key = f"{repo.casefold()}:{finished.get('id')}"
        if (finished.get("status") == "completed"
                and finished.get("conclusion") == "success" and key not in seen
                and learning_allowed(repo, finished, history)):
            run_id = int(finished["id"])
            jobs = jobs_cache.get(run_id)
            if jobs is None:
                jobs = jobs_for(repo, run_id, github_token)
                jobs_cache[run_id] = jobs
            learn(repo, finished, jobs, history)
            observe(repo, finished, jobs, history)
            break
    # Preserve the legacy single sensor, but expose *each* simultaneously
    # active workflow as a separate record. "success" in the sensor only
    # refers to its primary run; other runs retain their own IDs/statuses.
    active_details = []
    for run in relevant:
        if not is_active(run, now):
            continue
        detail = results[int(run["id"])]
        active_details.append({
            "run_id": int(run["id"]),
            "run_number": run.get("run_number"),
            "workflow": run.get("name") or "GitHub Actions",
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_branch": run.get("head_branch"),
            "progress_percent": detail["progress_percent"],
            "current_job": detail.get("current_job"),
            "current_step": detail.get("current_step"),
            "runner_name": detail.get("runner_name"),
            "run_url": detail.get("run_url"),
        })
    primary = next((r for r in relevant if is_active(r, now)), relevant[0] if relevant else None)
    if primary is None:
        set_sensor(repo, {"repository": repo, "state": "idle",
                          "progress_percent": 0, "active_run_count": 0,
                          "active_run_details": [], "primary_run_id": None}, ha_token)
    else:
        data = dict(results[int(primary["id"])])
        data["active_run_count"] = active_count
        data["active_run_details"] = active_details
        data["primary_run_id"] = data["run_id"]
        # Progress never moves backward within the same run even when dynamic jobs are added.
        previous = state.setdefault("sensor_progress", {}).get(repo, {})
        if previous.get("run_id") == data["run_id"] and is_active(primary, now):
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

    selected = config.get("live_activity_notify_services")
    if selected is None:
        service = config.get("live_activity_notify_service", "")
        selected = [service] if service else []
    if not isinstance(selected, list):
        selected = []
    activity_targets = state.setdefault("activity_targets", {})
    if not activity_targets and "activities" in state and selected:
        # Compat with direct v0.1.7 calls and their single-target persisted state.
        activity_targets[selected[0]] = state["activities"]
    for service in selected:
        activities = activity_targets.setdefault(service, {}).setdefault(repo, {})
        try:
            deliver_activity_updates(
                repo, github_token, ha_token, service,
                activities, config, now, relevant, recent_by_id,
                results, jobs_cache, history
            )
        except (RuntimeError, OSError, ValueError, TypeError, KeyError) as exc:
            # One unreachable phone must not suppress updates to all other devices.
            log(f"Live Activity delivery to {service} failed; will retry: {exc}")
    state["activities"] = activity_targets.get(selected[0], {}) if selected else {}


def deliver_activity_updates(repo: str, github_token: str, ha_token: str,
                             service: str, activities: dict, config: dict,
                             now: float, relevant: list[dict],
                             recent_by_id: dict[int, dict], results: dict[int, dict],
                             jobs_cache: dict[int, list[dict]], history: dict) -> None:
    """Per-device progress/finish bookkeeping: every phone is independent."""
    if not config.get("live_activity_enabled"):
        if activities:
            notify_service(service)
            for run_id in list(activities):
                notify(service, ha_token, clear_payload(repo, int(run_id)))
                del activities[run_id]
        return
    notify_service(service)
    for run in relevant:
        if not is_active(run, now):
            continue
        run_id = str(run["id"])
        data = dict(results[int(run_id)])
        old = activities.get(run_id) or {}
        # A GitHub rerun can reactivate the same run ID after a terminal result.
        # Start a fresh activity instead of retaining its old cleanup timer.
        if "finished_at" in old:
            del activities[run_id]
            old = {}
        # One phone's progress cannot incorrectly suppress another phone's update.
        data["progress_percent"] = max(data["progress_percent"], int(old.get("percent", 0)))
        step = data.get("current_step") or data.get("current_job") or ""
        payload = activity_payload(run, data, repo,
                                   display_name(repo, config.get("repository_aliases")), now)
        # The iOS title cannot change once started. Retire a tracked v0.2.1
        # activity that had a changing ETA in its header; recreate next poll.
        if old and old.get("title") and old["title"] != payload["title"]:
            notify(service, ha_token, clear_payload(repo, int(run_id)))
            del activities[run_id]
            log(f"{repo}: retired old-format Live Activity on {service} "
                f"for run {run_id}; will recreate")
            continue
        if (not old
                or data["progress_percent"] - int(old.get("percent", 0)) >= 2
                or step != old.get("step")
                or payload["message"] != old.get("message")
                or now - float(old.get("sent_at", 0)) >= 180):
            notify(service, ha_token, payload)
            activities[run_id] = {"percent": data["progress_percent"],
                                  "step": step, "title": payload["title"],
                                  "message": payload["message"], "sent_at": now}
    for run_id, old in list(activities.items()):
        if "finished_at" in old:
            finished_at = float(old["finished_at"])
            last_sent = float(old.get("last_final_sent_at", finished_at))
            attempts = int(old.get("final_sent_count", 1))
            final_payload = old.get("final_payload")
            clears = int(old.get("clear_sent_count", 0))
            # After the first clear, NEVER send a Live Activity update again.
            # That could recreate an activity iOS has already removed.
            if clears:
                last_clear = float(old.get("last_clear_sent_at", finished_at))
                if now - last_clear < FINAL_ACTIVITY_CLEAR_RETRY_SECONDS:
                    continue
                if clears >= FINAL_ACTIVITY_CLEAR_ATTEMPTS:
                    # Wait one additional poll after the last clear so state
                    # survives restart and no later update is emitted.
                    del activities[run_id]
                    log(f"{repo}: finished Live Activity cleanup for "
                        f"{service} run {run_id} ({clears} clears requested)")
                else:
                    notify(service, ha_token, clear_payload(repo, int(run_id)))
                    old["clear_sent_count"] = clears + 1
                    old["last_clear_sent_at"] = now
                    log(f"{repo}: clear {clears + 1}/"
                        f"{FINAL_ACTIVITY_CLEAR_ATTEMPTS} submitted to "
                        f"{service} for run {run_id}")
                continue
            if (attempts < FINAL_ACTIVITY_UPDATES
                    and now - last_sent >= FINAL_ACTIVITY_RETRY_SECONDS
                    and isinstance(final_payload, dict)):
                notify(service, ha_token, final_payload)
                old["final_sent_count"] = attempts + 1
                old["last_final_sent_at"] = now
                log(f"{repo}: completion update {attempts + 1}/"
                    f"{FINAL_ACTIVITY_UPDATES} submitted to {service} for run {run_id}")
            elif (now - finished_at >= FINAL_ACTIVITY_MIN_VISIBLE_SECONDS
                  and (not isinstance(final_payload, dict)
                       or (attempts >= FINAL_ACTIVITY_UPDATES
                           and now - last_sent >= FINAL_ACTIVITY_CLEAR_GRACE_SECONDS))):
                # Upgrade-compatible: v0.2.2 stored no clear counters.
                # Retry until several clear pushes have been accepted by HA.
                notify(service, ha_token, clear_payload(repo, int(run_id)))
                old["clear_sent_count"] = 1
                old["last_clear_sent_at"] = now
                # Never resend the final payload after starting to clear.
                old.pop("final_payload", None)
                log(f"{repo}: clear 1/{FINAL_ACTIVITY_CLEAR_ATTEMPTS} "
                    f"submitted to {service} for run {run_id}")
            continue
        run = recent_by_id.get(int(run_id))
        if run is not None and is_active(run, now):
            continue
        if run is None:
            # GitHub pagination may drop an older run before the phone's
            # Live Activity is removed. Retry its clear across poll cycles.
            notify(service, ha_token, clear_payload(repo, int(run_id)))
            old.update({"finished_at": now - FINAL_ACTIVITY_MIN_VISIBLE_SECONDS,
                        "last_final_sent_at": now - FINAL_ACTIVITY_CLEAR_GRACE_SECONDS,
                        "final_sent_count": FINAL_ACTIVITY_UPDATES,
                        "clear_sent_count": 1, "last_clear_sent_at": now})
            old.pop("final_payload", None)
            log(f"{repo}: first orphan clear submitted to {service} for run {run_id}")
            continue
        rid = int(run_id)
        if rid not in results:
            jobs = jobs_cache.get(rid) or jobs_for(repo, rid, github_token)
            learn(repo, run, jobs, history)
            results[rid] = snapshot(repo, run, jobs, history, now)
            results[rid].update(predict(repo, run, jobs, history, now))
        final_payload = activity_payload(run, results[rid], repo,
                                         display_name(repo, config.get("repository_aliases")), now)
        notify(service, ha_token, final_payload)
        # Keep retry delivery priority high without replaying a sound.
        # 'alert_once: true' lowers APNs priority and may let completion
        # pushes arrive after the clear, effectively reviving the activity.
        silent_high_priority_retry = {
            **final_payload,
            "data": {**final_payload["data"], "alert_once": False,
                     "push": {"sound": "none"}},
        }
        old.update({"finished_at": now, "last_final_sent_at": now,
                    "final_sent_count": 1, "final_payload": silent_high_priority_retry})
        log(f"{repo}: completion update 1/{FINAL_ACTIVITY_UPDATES} submitted "
            f"to {service} for run {run_id}")


def migrate_history(data_dir: Path, history: dict) -> dict:
    """Import v0.1.0 learned durations when the old data directory is retained."""
    old = read_json(data_dir / "github-build-monitor-state/history-v1.json", {})
    if not old or history.get("v010_migration_done"):
        return history
    steps = history.setdefault("steps", {})
    imported = 0
    for encoded, durations in old.get("durations", {}).items():
        try:
            repo, workflow, job, step = json.loads(encoded)
            if not isinstance(durations, list):
                continue
            key = history_key(str(repo), {"name": job}, {"name": step}, str(workflow))
            if key not in steps:
                clean = [float(n) for n in durations if isinstance(n, (int, float))
                         and 0 < float(n) <= 7200]
                if clean:
                    steps[key] = clean[-20:]
                    imported += 1
        except (TypeError, ValueError):
            continue
    history["v010_migration_done"] = True
    log(f"Imported {imported} historical step durations from v0.1.0")
    return history


def clear_legacy_notifications(data_dir: Path, state: dict, service: str,
                               ha_token: str, repositories: list[str] | None = None) -> None:
    """End old v0.1.0 per-repository activities after moving add-on sources.

    The old add-on and the new repository add-on do not share /data,
    therefore an old notifications-v1.json file may not be available.
    Tags were deterministic, so clear them for each configured repository.
    This cleanup runs once per app data volume after a notifier is configured.
    """
    if state.get("v010_legacy_tag_cleanup_v013"):
        return
    old = read_json(data_dir / "github-build-monitor-state/notifications-v1.json", {})
    known = set(repositories or [])
    known.update(repo for repo in old
                 if isinstance(repo, str) and "/" in repo)
    if not known:
        return
    if not service:
        return  # Try again after the user configures their phone.
    notify_service(service)
    for repo in sorted(known):
        tag = "ghrunner_" + hashlib.sha256(repo.lower().encode()).hexdigest()[:16]
        notify(service, ha_token, {"message": "clear_notification", "data": {"tag": tag}})
    state["v010_legacy_tag_cleanup_v013"] = True
    log(f"Cleared old v0.1.0 Live Activity tags for {len(known)} repositories")

def apply_pending_learning_reset(data_dir: Path, history: dict) -> bool:
    """Apply ingress reset requests in the monitoring thread (sole history writer)."""
    path = data_dir / "reset-learning-command.json"
    command = read_json(path, {})
    if not command:
        return False
    scope = command.get("scope")
    when = command.get("at")
    if (not isinstance(scope, str)
            or (scope != "all" and "/" not in scope)
            or not isinstance(when, (int, float))
            or not command.get("csrf_checked")):
        log("Invalid learning reset request ignored")
        path.unlink(missing_ok=True)
        return False
    request_id = f"{scope}:{when}"
    if history.get("last_learning_reset_id") != request_id:
        reset_history(history, scope, float(when))
        history["last_learning_reset_id"] = request_id
        write_json(data_dir / "monitor_history.json", history)
        log(f"Learning history reset for {scope} (other settings preserved)")
    path.unlink(missing_ok=True)
    return True


def reconcile_mobile_target(target: str, original: str, state: dict,
                            ha_token: str) -> str:
    """End old iPhone activities before switching the notification recipient.

    A selection can change on disk during a running build. Never leave old
    notifications orphaned and never send updates to both destinations.
    If clearing fails temporarily, retain the old target and retry later.
    """
    previous = state.get("active_mobile_notify_service")
    if not isinstance(previous, str):
        previous = original
    if previous == target:
        state["active_mobile_notify_service"] = target
        return target
    if previous:
        for repo, activities in state.get("activities", {}).items():
            for run_id in list(activities):
                try:
                    notify(previous, ha_token, clear_payload(repo, int(run_id)))
                except (RuntimeError, OSError, ValueError, TypeError) as exc:
                    log(f"Cannot switch mobile device yet; old notification "
                        f"cleanup will retry: {exc}")
                    return previous
                del activities[run_id]
    else:
        # No prior service is known to receive a clear call.
        state["activities"] = {}
    state["active_mobile_notify_service"] = target
    log("Changed Live Activity destination" if target else
        "Live Activity destination unset")
    return target


def reconcile_mobile_targets(desired: list[str], original: str,
                             state: dict, ha_token: str) -> list[str]:
    """Migrate v0.1.7 single activity state and retire only deselected phones.

    On temporary push failures, retain the old recipient's tracking state
    and retry closing their activities next time. No other device is blocked.
    """
    previous = state.get("active_mobile_notify_services")
    if not isinstance(previous, list):
        old = state.get("active_mobile_notify_service") or original
        previous = [old] if old else []
    device_data = state.setdefault("activity_targets", {})
    if previous and not state.get("activity_targets_migrated_v018"):
        legacy = state.get("activities", {})
        if isinstance(legacy, dict) and legacy:
            device_data.setdefault(previous[0], legacy)
    state["activity_targets_migrated_v018"] = True
    retired = []
    for device in list(device_data):
        if device in desired:
            continue
        for repo, activities in list(device_data[device].items()):
            for run_id in list(activities):
                try:
                    notify(device, ha_token, clear_payload(repo, int(run_id)))
                except (RuntimeError, OSError, ValueError, TypeError) as exc:
                    log(f"Could not close old Live Activity on {device}: {exc}")
                    break
                del activities[run_id]
        if all(not runs for runs in device_data[device].values()):
            retired.append(device)
    for device in retired:
        del device_data[device]
    state["active_mobile_notify_services"] = list(desired)
    state["active_mobile_notify_service"] = desired[0] if desired else ""
    state["activities"] = device_data.setdefault(desired[0], {}) if desired else {}
    return desired


def main() -> None:
    ha_token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not ha_token:
        log("Missing SUPERVISOR_TOKEN; enable homeassistant_api")
        return
    log("Started; monitoring configuration will refresh each poll")
    state_file = DATA_DIR / "monitor_state.json"
    history_file = DATA_DIR / "monitor_history.json"
    state = read_json(state_file, {})
    history = read_json(history_file, {})
    history = migrate_history(DATA_DIR, history)
    try:
        start_learning_ui(DATA_DIR)
        log("Learning dashboard active via Home Assistant Ingress")
    except OSError as exc:
        # Learning UI must never disable the build monitor if its port is unavailable.
        log(f"Learning dashboard could not start; monitoring continues: {exc}")
    while True:
        # Apply changes before polling so old GitHub runs are not learned again.
        apply_pending_learning_reset(DATA_DIR, history)
        # As in working v0.1.0, configuration changes take effect without a restart.
        native_options = read_json(DATA_DIR / "options.json", {})
        config = dict(native_options)
        config["repository_aliases"] = repository_aliases(DATA_DIR)
        selected_devices = reconcile_mobile_targets(
            effective_services(native_options, DATA_DIR),
            str(native_options.get("live_activity_notify_service") or ""),
            state, ha_token)
        config["live_activity_notify_services"] = selected_devices
        config["live_activity_notify_service"] = selected_devices[0] if selected_devices else ""
        repos = effective_repositories(config, DATA_DIR)
        token = str(config.get("github_api_token") or "")
        interval = max(30, min(300, int(config.get("poll_interval_seconds", 60))))
        if config.get("live_activity_enabled"):
            if not selected_devices:
                config["live_activity_enabled"] = False
            else:
                try:
                    for target in selected_devices:
                        notify_service(target)
                except ValueError as exc:
                    log(f"Live Activity disabled until configured: {exc}")
                    config["live_activity_enabled"] = False
        now = time.time()
        try:
            clear_legacy_notifications(
                DATA_DIR, state, config.get("live_activity_notify_service", ""),
                ha_token, repos)
        except (RuntimeError, OSError, ValueError) as exc:
            log(f"Legacy Live Activity cleanup will retry: {exc}")
        # A deselected repository has separate notifications on each device.
        prior = set(state.get("last_monitored_repositories") or [])
        tracking = state.setdefault("activity_targets", {})
        previous = prior | {repo for data in tracking.values() for repo in data}
        for previous_repo in previous - set(repos):
            for device, repositories_on_device in tracking.items():
                activities = repositories_on_device.get(previous_repo, {})
                for run_id in list(activities):
                    try:
                        notify(device, ha_token, clear_payload(previous_repo, int(run_id)))
                    except (RuntimeError, OSError, ValueError) as exc:
                        log(f"Unable to retire {previous_repo} on {device}: {exc}")
                        break
                    del activities[run_id]
            if previous_repo in prior:
                try:
                    set_sensor(previous_repo, {"state": "disabled", "repository": previous_repo,
                                               "progress_percent": 0, "active_run_count": 0}, ha_token)
                except (ValueError, RuntimeError, OSError) as exc:
                    log(f"Unable to mark {previous_repo} as disabled: {exc}")
        state["last_monitored_repositories"] = list(repos)
        for repo in repos:
            try:
                monitor_repository(repo, token, ha_token, config, state, history, now)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                # Keep the last sensor and Live Activity on transient API failures,
                # as the working v0.1.0 did. Never fabricate a workflow failure.
                log(f"{repo}: {type(exc).__name__}: {exc}")
            finally:
                write_json(state_file, state)
                write_json(history_file, history)
        # Also persist an empty selection when all repositories were unchecked.
        if not repos:
            write_json(state_file, state)
            write_json(history_file, history)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped")
        sys.exit(0)
