"""Runner-aware GitHub Actions forecasts.

Uses the *whole workflow* duration rather than summing individual steps.
This captures queue times, runner hand-offs, and parallel jobs. Historical
data is stored only in the app's local state, never in GitHub.
"""
from __future__ import annotations

from statistics import median
from core import timestamp


def workflow_key(repo: str, run: dict) -> str:
    identity = run.get("workflow_id") or run.get("name") or "unknown"
    return f"{repo.casefold()}:{identity}"


def runner_class(jobs: list[dict]) -> str:
    """Conservative grouping for known runners; unknown ones stay separate."""
    result = set()
    for job in jobs:
        name = str(job.get("runner_name") or "").casefold()
        if not name:
            continue
        labels = [str(v).casefold() for v in job.get("labels") or []]
        if "newmajor" in name:
            result.add("newmajor")
        elif "synology" in name or name.startswith("nas-"):
            result.add("synology")
        elif name.startswith(("dso-ha", "more-tents-ha", "ha-")):
            result.add("ha")
        elif name.startswith(("github actions", "github-hosted")) or "ubuntu-latest" in labels:
            result.add("github-hosted")
        else:
            result.add(name)
    return next(iter(result)) if len(result) == 1 else "mixed" if result else "unknown"


def _union_duration(intervals: list[tuple[float, float]]) -> float:
    """Duration spent with at least one job actually running."""
    merged: list[list[float]] = []
    for start, finish in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, finish])
        else:
            merged[-1][1] = max(merged[-1][1], finish)
    return sum(finish - start for start, finish in merged)


def observe(repo: str, run: dict, jobs: list[dict], history: dict) -> bool:
    """Learn a completed successful workflow once, including waiting time."""
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        return False
    start = timestamp(run.get("created_at") or run.get("run_started_at"))
    if start is None or not jobs:
        return False
    intervals = []
    for job in jobs:
        a = timestamp(job.get("started_at"))
        b = timestamp(job.get("completed_at"))
        if a is not None and b is not None and a <= b:
            intervals.append((a, b))
    # The jobs endpoint is sometimes incomplete immediately after completion;
    # do not learn a misleadingly short run from missing final jobs.
    if not intervals or any(j.get("status") != "completed" for j in jobs):
        return False
    finish = max(b for _, b in intervals)
    elapsed = finish - start
    if not 2 <= elapsed <= 8 * 3600:
        return False

    store = history.setdefault("forecast", {})
    seen = store.setdefault("seen", [])
    run_key = f"{repo.casefold()}:{run.get('id')}"
    if run_key in seen:
        return False
    sample = {
        "seconds": round(elapsed, 1),
        "queue_seconds": round(max(0, elapsed - _union_duration(intervals)), 1),
        "runner": runner_class(jobs),
        "jobs": sorted(str(job.get("name") or "") for job in jobs),
    }
    group = store.setdefault("workflows", {}).setdefault(workflow_key(repo, run), [])
    group.append(sample)
    store["workflows"][workflow_key(repo, run)] = group[-40:]
    seen.append(run_key)
    store["seen"] = seen[-1500:]
    return True


def _quantile(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    i = int(pos)
    return sorted_values[i] + (sorted_values[min(i + 1, len(sorted_values) - 1)] - sorted_values[i]) * (pos - i)


def predict(repo: str, run: dict, jobs: list[dict], history: dict,
            now: float) -> dict:
    """Return range and confidence, not a fabricated precise ETA."""
    default = {
        "eta_lower_seconds": None,
        "eta_upper_seconds": None,
        "estimated_remaining_seconds": None,
        "forecast_samples": 0,
        "forecast_confidence": "insufficient",
        "forecast_runner_group": runner_class(jobs),
        "forecast_wait_seconds": None,
    }
    if run.get("status") == "completed":
        return {**default, "forecast_confidence": "completed"}
    start = timestamp(run.get("created_at") or run.get("run_started_at"))
    if start is None:
        return default
    elapsed = max(0.0, now - start)
    all_samples = history.get("forecast", {}).get("workflows", {}).get(workflow_key(repo, run), [])
    runner = runner_class(jobs)
    # Prefer job topology, then runner family. Fallback only if at least three
    # examples exist and downgrade confidence on the heterogeneous sample.
    available_names = sorted(str(j.get("name") or "") for j in jobs)
    by_jobs = [s for s in all_samples if s.get("jobs") == available_names]
    group = by_jobs if len(by_jobs) >= 3 else all_samples
    homogeneous_jobs = group is by_jobs
    by_runner = [s for s in group if s.get("runner") == runner]
    if runner != "unknown" and len(by_runner) >= 3:
        group = by_runner
        runner_specific = True
    else:
        runner_specific = False
    values = sorted(float(s["seconds"]) for s in group
                    if isinstance(s.get("seconds"), (int, float)) and s["seconds"] > 0)
    if len(values) < 3:
        return {**default, "forecast_samples": len(values)}
    lower = _quantile(values, .25)
    upper = _quantile(values, .75)
    typical = median(values)
    wait = median([float(s.get("queue_seconds", 0)) for s in group])
    confidence = ("high" if len(values) >= 10 and runner_specific and homogeneous_jobs
                  else "medium" if len(values) >= 5 and runner_specific and homogeneous_jobs
                  else "low")
    # If this run already exceeds typical historical upper duration, an ETA
    # of zero would be misleading. Keep watching without presenting a number.
    if elapsed >= upper:
        return {
            **default, "forecast_samples": len(values),
            "forecast_confidence": "overdue",
            "forecast_wait_seconds": int(wait),
        }
    return {
        **default,
        "estimated_remaining_seconds": int(max(0, typical - elapsed)),
        "eta_lower_seconds": int(max(0, lower - elapsed)),
        "eta_upper_seconds": int(max(0, upper - elapsed)),
        "forecast_samples": len(values),
        "forecast_confidence": confidence,
        "forecast_wait_seconds": int(wait),
    }
