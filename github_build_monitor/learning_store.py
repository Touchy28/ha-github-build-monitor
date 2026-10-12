"""Pure learning-history inspection/reset functions.

Only historical timing data is modified. Credentials, settings,
monitor_state.json, and current iPhone Live Activities are not touched.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import median

from core import timestamp


def learning_allowed(repo: str, run: dict, history: dict) -> bool:
    """Do not silently restore measurements older than a user's reset."""
    cutoff = max(
        float(history.get("learning_reset_global_after") or 0),
        float((history.get("learning_reset_after") or {}).get(repo.casefold()) or 0),
    )
    if not cutoff:
        return True
    # GitHub's updated_at records the terminal transition; the other
    # timestamps are conservative fallbacks for tests/older API results.
    ended = timestamp(run.get("updated_at") or run.get("completed_at")
                      or run.get("created_at"))
    return ended is not None and ended > cutoff


def reset_history(history: dict, scope: str, when: float) -> None:
    """Reset all, or just one repository; record cutoff to prevent re-backfill."""
    if scope == "all":
        history["steps"] = {}
        history["learned_runs"] = []
        history["forecast"] = {"seen": [], "workflows": {}}
        history["learning_reset_global_after"] = when
        history["learning_reset_after"] = {}
    else:
        slug = scope.casefold()
        prefix_step = slug + "\x1f"
        prefix_run = slug + ":"
        history["steps"] = {k: v for k, v in (history.get("steps") or {}).items()
                            if not k.casefold().startswith(prefix_step)}
        history["learned_runs"] = [
            run for run in (history.get("learned_runs") or [])
            if not str(run).casefold().startswith(prefix_run)
        ]
        history.setdefault("learning_reset_after", {})[slug] = when
        forecast = history.setdefault("forecast", {})
        forecast["workflows"] = {
            k: v for k, v in (forecast.get("workflows") or {}).items()
            if not k.casefold().startswith(prefix_run)
        }
        forecast["seen"] = [
            run for run in (forecast.get("seen") or [])
            if not str(run).casefold().startswith(prefix_run)
        ]
    # The v0.1.0 source must not be reimported when the add-on is restarted.
    history["v010_migration_done"] = True


def summary(history: dict, watched: list[str]) -> list[dict]:
    """Summarize timings without exposing tokens or unrelated monitor state."""
    result = []
    all_workflows = history.get("forecast", {}).get("workflows", {})
    steps = history.get("steps", {})
    for repo in watched:
        step_keys = [k for k in steps if k.casefold().startswith(repo.casefold() + "\x1f")]
        workflows = []
        prefix = repo.casefold() + ":"
        for key, records in all_workflows.items():
            if not key.casefold().startswith(prefix) or not isinstance(records, list):
                continue
            valid = [r for r in records
                     if isinstance(r, dict)
                     and isinstance(r.get("seconds"), (int, float))
                     and 0 < r["seconds"] <= 8 * 3600]
            if not valid:
                continue
            numbers = [float(v["seconds"]) for v in valid]
            waits = [float(v.get("queue_seconds") or 0) for v in valid]
            names = [v.get("workflow_name") for v in valid
                     if isinstance(v.get("workflow_name"), str) and v["workflow_name"]]
            runners = Counter(str(v.get("runner") or "unknown") for v in valid)
            workflows.append({
                "id": key[len(prefix):],
                "name": names[-1] if names else "Workflow #" + key[len(prefix):],
                "runs": len(valid),
                "median_seconds": round(median(numbers)),
                "min_seconds": round(min(numbers)),
                "max_seconds": round(max(numbers)),
                "median_queue_seconds": round(median(waits)),
                "runners": runners.most_common(),
                "prognosis_ready": len(valid) >= 3,
            })
        workflows.sort(key=lambda row: (-row["runs"], row["name"]))
        result.append({
            "repository": repo,
            "workflows": workflows,
            "workflow_samples": sum(w["runs"] for w in workflows),
            "step_types": len(step_keys),
            "step_samples": sum(len(steps[k]) for k in step_keys
                                if isinstance(steps[k], list)),
        })
    return result


def reset_description(history: dict, repo: str) -> str:
    cutoff = max(float(history.get("learning_reset_global_after") or 0),
                 float((history.get("learning_reset_after") or {}).get(repo.casefold()) or 0))
    if not cutoff:
        return ""
    return datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
