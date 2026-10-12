import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))

import core
import monitor

REPO = "Touchy28/more-tents"


def sample_run(status="in_progress", conclusion=None, run_id=42):
    return {"id": run_id, "name": "Build", "status": status,
            "conclusion": conclusion, "html_url": "https://github.com/example/actions/runs/42"}


def sample_job():
    return {"name": "test", "status": "in_progress", "steps": [
        {"name": "checkout", "status": "completed", "conclusion": "success",
         "started_at": "2023-11-14T22:12:00Z",
         "completed_at": "2023-11-14T22:13:00Z"},
        {"name": "build", "status": "in_progress",
         "started_at": "2023-11-14T22:13:10Z"}]}


class OptionsTests(unittest.TestCase):
    def test_repos_deduplicated_and_invalid_ignored(self):
        result = core.repositories({"repositories": [
            REPO, "touchy28/more-tents", "bad repo", "Touchy28/DSO-Optimizer",
            "invalid/../../escape", 10]})
        self.assertEqual(result, [REPO, "Touchy28/DSO-Optimizer"])

    def test_repos_missing(self):
        self.assertEqual(core.repositories({}), [])

    def test_notify_service_restricts_to_mobile_app(self):
        self.assertEqual(core.notify_service("notify.mobile_app_mein_iphone"),
                         "mobile_app_mein_iphone")
        for forbidden in ["notify.persistent_notification", "script.turn_on",
                          "https://example.com", "notify.mobile_app_abc/other", ""]:
            with self.subTest(forbidden=forbidden):
                with self.assertRaises(ValueError):
                    core.notify_service(forbidden)

    def test_sensor_id_is_stable_and_unique(self):
        self.assertEqual(core.sensor_id(REPO), core.sensor_id(REPO.lower()))
        self.assertNotEqual(core.sensor_id(REPO),
                            core.sensor_id("Touchy28/DSO-Optimizer"))

    def test_activity_tags_are_unique_per_run(self):
        self.assertNotEqual(core.activity_tag(REPO, 12),
                            core.activity_tag(REPO, 13))
        self.assertNotEqual(core.activity_tag(REPO, 12),
                            core.activity_tag("Touchy28/DSO-Optimizer", 12))
        self.assertLessEqual(len(core.activity_tag(REPO, 12)), 64)

    def test_notifiers_use_correct_clear_command(self):
        self.assertEqual(monitor.clear_payload(REPO, 4)["message"], "clear_notification")
        self.assertEqual(monitor.clear_payload(REPO, 4)["data"]["tag"],
                         core.activity_tag(REPO, 4))


class ProgressTests(unittest.TestCase):
    def test_zero_jobs(self):
        result = core.snapshot(REPO, sample_run(), [], {}, now=1700000000)
        self.assertEqual(result["progress_percent"], 0)
        self.assertTrue(result["progress_is_estimate"])

    def test_running_steps_bounded(self):
        now = core.timestamp("2023-11-14T22:13:20Z")
        result = core.snapshot(REPO, sample_run(), [sample_job()], {}, now=now)
        self.assertGreater(result["progress_percent"], 0)
        self.assertLess(result["progress_percent"], 100)
        self.assertEqual(result["completed_steps"], 1)
        self.assertEqual(result["total_steps"], 2)
        self.assertEqual(result["current_step"], "build")

    def test_completed_success_is_100(self):
        run = sample_run("completed", "success")
        result = core.snapshot(REPO, run, [sample_job()], {})
        self.assertEqual(result["progress_percent"], 100)
        self.assertFalse(result["progress_is_estimate"])
        self.assertEqual(result["conclusion"], "success")

    def test_completed_failure_is_not_labeled_success(self):
        run = sample_run("completed", "failure")
        result = core.snapshot(REPO, run, [sample_job()], {})
        self.assertEqual(result["progress_percent"], 100)
        self.assertEqual(result["conclusion"], "failure")
        msg = monitor.activity_payload(run, result, REPO)["message"]
        self.assertIn("failure", msg)

    def test_queued_job_without_steps(self):
        job = {"name": "waiting", "status": "queued", "steps": []}
        result = core.snapshot(REPO, sample_run("queued"), [job], {})
        self.assertEqual(result["total_steps"], 1)
        self.assertEqual(result["progress_percent"], 0)

    def test_history_only_successful_run(self):
        history = {}
        jobs = [sample_job()]
        self.assertFalse(core.learn(REPO, sample_run(), jobs, history))
        self.assertFalse(history)
        self.assertTrue(core.learn(REPO, sample_run("completed", "success"), jobs, history))
        self.assertFalse(core.learn(REPO, sample_run("completed", "success"), jobs, history))
        key = core.history_key(REPO, jobs[0], jobs[0]["steps"][0], "Build")
        self.assertEqual(history["steps"][key], [60.0])

    def test_historical_eta_requires_multiple_observations(self):
        job = sample_job()
        key1 = core.history_key(REPO, job, job["steps"][0], "Build")
        key2 = core.history_key(REPO, job, job["steps"][1], "Build")
        history = {"steps": {key1: [60, 55], key2: [120, 110]}}
        result = core.snapshot(REPO, sample_run(), [job], history,
                               now=core.timestamp("2023-11-14T22:13:20Z"))
        self.assertIsInstance(result["estimated_remaining_seconds"], int)

    def test_malformed_timestamps_ignored(self):
        self.assertIsNone(core.timestamp("nonsense"))
        self.assertIsNone(core.duration({"started_at": "today", "completed_at": "soon"}))

    def test_live_activity_payload(self):
        run = sample_run()
        value = core.snapshot(REPO, run, [sample_job()], {})
        payload = monitor.activity_payload(run, value, REPO)
        self.assertTrue(payload["data"]["live_update"])
        self.assertEqual(payload["data"]["progress_max"], 100)
        self.assertEqual(payload["data"]["tag"], core.activity_tag(REPO, 42))

    def test_package_has_no_runner_or_docker_rights(self):
        path = Path(__file__).resolve().parents[1] / "github_build_monitor"
        conf = (path / "config.yaml").read_text()
        self.assertNotIn("docker_api: true", conf)
        self.assertNotIn("privileged:", conf)
        self.assertNotIn("registration_token", conf)
        self.assertNotIn("config.sh", (path / "run.sh").read_text())


if __name__ == "__main__":
    unittest.main()
