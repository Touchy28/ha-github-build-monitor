"""Pure helpers for GitHub Build Monitor (no secrets, network or HA imports)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from statistics import median

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_NOTIFY = re.compile(r"^(?:notify\.)?mobile_app_[a-zA-Z0-9_]+$")


def repositories(options: dict) -> list[str]:
    result, seen = [], set()
    for value in options.get("repositories") or []:
        if not isinstance(value, str) or not _REPO.fullmatch(value):
            continue
        if value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result


def notify_service(name: str) -> str:
    if not isinstance(name, str) or not _NOTIFY.fullmatch(name):
        raise ValueError("Expected notify.mobile_app_<device> (no URL or arbitrary service)")
    return name.removeprefix("notify.")


def sensor_id(repo: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", repo.lower()).strip("_")[:35]
    digest = hashlib.sha256(repo.lower().encode()).hexdigest()[:6]
    # Keep the original v0.1.0 entity ID for existing HA dashboards.
    return f"sensor.github_runner_{slug}_{digest}"


def activity_tag(repo: str, run_id: int) -> str:
    digest = hashlib.sha256(repo.lower().encode()).hexdigest()[:12]
    return f"gha_{digest}_{int(run_id)}"[:64]


def timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def duration(step: dict) -> float | None:
    start, end = timestamp(step.get("started_at")), timestamp(step.get("completed_at"))
    if start is None or end is None or end < start:
        return None
    elapsed = end - start
    return elapsed if elapsed <= 6 * 3600 else None


def history_key(repo: str, job: dict, step: dict, workflow: str = "") -> str:
    return "\x1f".join((repo.lower(), workflow, str(job.get("name") or ""), str(step.get("name") or "")))


def expected_seconds(repo: str, job: dict, step: dict, history: dict, workflow: str = "") -> float:
    samples = history.get("steps", {}).get(history_key(repo, job, step, workflow), [])
    clean = [float(n) for n in samples if isinstance(n, (float, int)) and 0 < n <= 21600]
    return max(2.0, median(clean)) if clean else 60.0


def learn(repo: str, run: dict, jobs: list[dict], history: dict) -> bool:
    """Learn step times only once, and only from successful completed workflows."""
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return False
    identity = f"{repo.lower()}:{run.get('id')}"
    learned = history.setdefault("learned_runs", [])
    if identity in learned:
        return False
    buckets = history.setdefault("steps", {})
    for job in jobs:
        for step in job.get("steps") or []:
            elapsed = duration(step)
            if elapsed is None or step.get("conclusion") not in ("success", None):
                continue
            key = history_key(repo, job, step, str(run.get("name") or ""))
            bucket = buckets.setdefault(key, [])
            bucket.append(round(elapsed, 2))
            buckets[key] = bucket[-20:]
    learned.append(identity)
    history["learned_runs"] = learned[-1000:]
    return True


def snapshot(repo: str, run: dict, jobs: list[dict], history: dict,
             now: float | None = None) -> dict:
    """Completed steps count fully; running steps count at most 90% of expected duration.

    A percentage describes estimated completion, not a precise GitHub-reported
    percentage. For finished unsuccessful runs, 100% means *finished*, NOT success.
    """
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    status = str(run.get("status") or "unknown")
    conclusion = run.get("conclusion")
    total_weight = done_weight = 0.0
    total_steps = completed_steps = 0
    active_step = ""
    active_job = ""
    observed = 0
    historic = 0
    for job in jobs:
        steps = job.get("steps") or []
        if not steps:
            # Queued/skipped jobs sometimes have no GitHub steps.
            steps = [{"name": "Waiting for runner", "status": job.get("status", "queued"),
                      "conclusion": job.get("conclusion"), "started_at": job.get("started_at")}]
        for step in steps:
            total_steps += 1
            weight = expected_seconds(repo, job, step, history, str(run.get("name") or ""))
            total_weight += weight
            entry = history.get("steps", {}).get(history_key(repo, job, step, str(run.get("name") or "")), [])
            if len(entry) >= 2:
                historic += 1
            state = step.get("status") or ("completed" if step.get("conclusion") else "queued")
            if state == "completed" or step.get("conclusion") is not None:
                completed_steps += 1
                done_weight += weight
                continue
            if state == "in_progress":
                started = timestamp(step.get("started_at"))
                if started is not None:
                    observed = max(observed, int(now - started))
                    # Retain the v0.1.0 rule: never interpolate unmeasured steps.
                    # Two historical observations are required for this exact workflow step.
                    if len(entry) >= 2:
                        done_weight += weight * min(.9, max(0, now - started) / weight)
            if not active_step:
                active_step = str(step.get("name") or "")
                active_job = str(job.get("name") or "")
    if status == "completed":
        percent = 100
    elif total_weight:
        percent = min(99, max(0, int(done_weight / total_weight * 100)))
    else:
        percent = 0
    eta = None
    if status != "completed" and total_weight and historic / max(1, total_steps) >= 0.65:
        eta = max(0, int(total_weight - done_weight))
    if not active_job:
        for job in jobs:
            if job.get("status") == "in_progress":
                active_job = str(job.get("name") or "")
                break
    return {
        "repository": repo,
        "state": status,
        "conclusion": conclusion,
        "workflow": run.get("name") or "GitHub Actions",
        "run_id": run.get("id"),
        "run_url": run.get("html_url"),
        "head_branch": run.get("head_branch"),
        "progress_percent": percent,
        "progress_is_estimate": status != "completed",
        "completed_steps": completed_steps,
        "total_steps": total_steps,
        "current_job": active_job,
        "current_step": active_step,
        "estimated_remaining_seconds": eta,
        "runner_name": next((j.get("runner_name") for j in jobs
                             if j.get("runner_name") and j.get("status") == "in_progress"), None),
    }
