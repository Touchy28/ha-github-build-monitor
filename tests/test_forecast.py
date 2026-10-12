"""Regression tests for workflow-aware and runner-aware ETA estimates."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))

import core
import forecast

REPO = "Touchy28/more-tents"


def run(ident=1, status="completed", conclusion="success", workflow_id=77):
    return {"id": ident, "name": "Publish Home Assistant app",
            "workflow_id": workflow_id, "created_at": "2026-10-12T05:10:00Z",
            "status": status, "conclusion": conclusion}


def jobs(runner="more-tents-ha-1"):
    return [
        {"name": "publish", "status": "completed", "runner_name": runner,
         "started_at": "2026-10-12T05:10:10Z",
         "completed_at": "2026-10-12T05:13:00Z"},
        {"name": "deploy-home-assistant", "status": "completed", "runner_name": runner,
         "started_at": "2026-10-12T05:17:00Z",
         "completed_at": "2026-10-12T05:17:12Z"},
    ]


class LearningTests(unittest.TestCase):
    def test_observe_whole_run_including_between_job_queue(self):
        history = {}
        self.assertTrue(forecast.observe(REPO, run(), jobs(), history))
        records = history["forecast"]["workflows"][forecast.workflow_key(REPO, run())]
        self.assertEqual(records[0]["seconds"], 432.0)
        # Job intervals: [10,180] and [420,432] => working 182 sec.
        # The remaining 250 sec includes queue and hand-off.
        self.assertEqual(records[0]["queue_seconds"], 250.0)
        self.assertEqual(records[0]["runner"], "ha")
        self.assertFalse(forecast.observe(REPO, run(), jobs(), history))

    def test_failed_jobs_are_never_learned(self):
        self.assertFalse(forecast.observe(REPO, run(conclusion="failure"), jobs(), {}))
        self.assertFalse(forecast.observe(REPO, run(status="in_progress"), jobs(), {}))

    def test_different_workflows_do_not_share_history(self):
        history = {}
        forecast.observe(REPO, run(1, workflow_id=10), jobs(), history)
        forecast.observe(REPO, run(2, workflow_id=11), jobs(), history)
        self.assertEqual(len(history["forecast"]["workflows"]), 2)

    def test_runner_families(self):
        self.assertEqual(forecast.runner_class([{"runner_name": "NEWMAJOR"}]), "newmajor")
        self.assertEqual(forecast.runner_class([{"runner_name": "synology-prod"}]), "synology")
        self.assertEqual(forecast.runner_class([{"runner_name": "dso-ha-2"}]), "ha")
        self.assertEqual(forecast.runner_class([
            {"runner_name": "NEWMAJOR"}, {"runner_name": "dso-ha-2"}]), "mixed")
        self.assertEqual(forecast.runner_class([]), "unknown")

    def test_overlapping_jobs_count_only_once(self):
        self.assertEqual(forecast._union_duration(
            [(0, 120), (30, 150), (151, 160)]), 159)

    def test_no_precise_eta_with_insufficient_samples(self):
        now = core.timestamp("2026-10-12T05:11:00Z")
        forecast_jobs = [{"runner_name": "more-tents-ha-1", "name": "publish"}]
        self.assertIsNone(forecast.predict(
            REPO, run(status="in_progress"), forecast_jobs, {}, now
        )["estimated_remaining_seconds"])

    def test_forecast_range_and_queue_history(self):
        key = forecast.workflow_key(REPO, run())
        history = {"forecast": {"workflows": {key: [
            {"seconds": x, "queue_seconds": 240,
             "runner": "ha", "jobs": ["deploy-home-assistant", "publish"]}
            for x in [360, 390, 420, 450, 480, 510]
        ]}}}
        now = core.timestamp("2026-10-12T05:12:00Z")
        running = run(status="in_progress")
        value = forecast.predict(REPO, running, jobs(), history, now)
        self.assertEqual(value["forecast_samples"], 6)
        self.assertEqual(value["forecast_confidence"], "medium")
        self.assertLess(value["eta_lower_seconds"], value["eta_upper_seconds"])
        self.assertEqual(value["forecast_wait_seconds"], 240)
        self.assertLess(value["estimated_remaining_seconds"], 390)

    def test_forecast_no_false_zero_after_typical_window(self):
        key = forecast.workflow_key(REPO, run())
        history = {"forecast": {"workflows": {key: [
            {"seconds": x, "queue_seconds": 100,
             "runner": "ha", "jobs": ["publish", "deploy-home-assistant"]}
            for x in [360, 380, 400, 420]
        ]}}}
        now = core.timestamp("2026-10-12T06:00:00Z")
        result = forecast.predict(REPO, run(status="in_progress"), jobs(), history, now)
        self.assertIsNone(result["estimated_remaining_seconds"])
        self.assertEqual(result["forecast_confidence"], "overdue")

    def test_different_runner_uses_fallback_with_lower_confidence(self):
        key = forecast.workflow_key(REPO, run())
        history = {"forecast": {"workflows": {key: [
            {"seconds": x, "runner": "ha", "jobs": ["deploy-home-assistant", "publish"]}
            for x in [390, 400, 410, 420, 430]
        ]}}}
        target = [{"name": "publish", "runner_name": "NEWMAJOR"}]
        eta = forecast.predict(REPO, run(status="in_progress"), target, history,
                               core.timestamp("2026-10-12T05:11:00Z"))
        self.assertEqual(eta["forecast_confidence"], "low")
        self.assertEqual(eta["forecast_samples"], 5)

    def test_job_selection_preferred_to_other_job_topologies(self):
        key = forecast.workflow_key(REPO, run())
        samples = [
            {"seconds": n, "runner": "ha", "jobs": ["publish"]}
            for n in [200, 210, 220]
        ]
        samples += [
            {"seconds": n, "runner": "ha",
             "jobs": ["deploy-home-assistant", "publish"]}
            for n in [700, 710, 720]
        ]
        history = {"forecast": {"workflows": {key: samples}}}
        current = [{"name": "publish", "runner_name": "more-tents-ha-1"}]
        eta = forecast.predict(REPO, run(status="in_progress"), current, history,
                               core.timestamp("2026-10-12T05:11:00Z"))
        self.assertLess(eta["estimated_remaining_seconds"], 200)


if __name__ == "__main__":
    unittest.main()
