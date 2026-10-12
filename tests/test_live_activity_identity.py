"""Regression tests: distinct parallel runs and durable iOS terminal updates."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))
import monitor

REPO = "Touchy28/more-tents"
PHONE = "mobile_app_iphone"


def run(run_id, number, name="CI", status="in_progress", conclusion=None):
    return {
        "id": run_id,
        "run_number": number,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "head_branch": "test/example",
        "created_at": "2026-10-12T10:00:00Z",
        "html_url": f"https://github.com/Touchy28/more-tents/actions/runs/{run_id}",
    }


def config():
    return {"live_activity_enabled": True,
            "live_activity_notify_services": [PHONE],
            "repository_aliases": {REPO.casefold(): "B&B"}}


def state():
    return {"activities": {}, "active_mobile_notify_services": [PHONE],
            "activity_targets": {}}


class RunIdentityTests(unittest.TestCase):
    def test_title_contains_fixed_workflow_and_run_number(self):
        progress = {"current_step_remaining_seconds": None,
                    "estimated_remaining_seconds": 250}
        title = monitor.activity_title(run(42, 1055), progress, REPO, "B&B")
        self.assertEqual(title, "B&B · CI #1055")
        self.assertEqual(monitor.remaining_time_label(run(42, 1055), progress), "≈–/5m")
        self.assertLessEqual(len(title), 64)
        another = monitor.activity_title(run(43, 94, "Switch prototype"),
                                         progress, REPO, "B&B")
        self.assertEqual(another, "B&B · Switch prototype #94")
        self.assertNotEqual(title, another)

    def test_long_alias_and_workflow_preserve_number_and_finish(self):
        result = monitor.activity_title(
            run(99, 1055, "Very long workflow name that will be abbreviated",
                "completed", "success"),
            {}, REPO, "Repository with a really long display name")
        self.assertIn("#1055", result)
        self.assertTrue(result.endswith("#1055"))
        self.assertLessEqual(len(result), 64)

    def test_parallel_runs_are_distinct_on_phone_and_sensor(self):
        incoming = [run(44, 1055), run(45, 94, "Switch prototype", "queued")]
        current = state()
        seen = []
        with mock.patch.object(monitor, "runs_for", return_value=incoming), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor", side_effect=lambda repo, data, token: seen.append(data)), \
             mock.patch.object(monitor, "notify") as notify:
            monitor.monitor_repository(REPO, "", "TOKEN", config(), current, {}, 1791800010)
        self.assertEqual(seen[-1]["run_id"], 44)
        self.assertEqual(seen[-1]["primary_run_id"], 44)
        self.assertEqual(seen[-1]["active_run_count"], 2)
        details = seen[-1]["active_run_details"]
        self.assertEqual({d["run_id"] for d in details}, {44, 45})
        self.assertEqual({d["status"] for d in details}, {"in_progress", "queued"})
        payloads = [c.args[2] for c in notify.call_args_list]
        self.assertEqual(len(payloads), 2)
        self.assertNotEqual(payloads[0]["data"]["tag"], payloads[1]["data"]["tag"])
        self.assertIn("CI #1055", payloads[0]["title"])
        self.assertNotIn("≈", payloads[0]["title"])
        self.assertIn("Restzeit –", payloads[0]["message"])
        self.assertIn("Switch prototype #94", payloads[1]["title"])

    def test_successful_primary_run_has_no_active_details(self):
        current = state()
        with mock.patch.object(monitor, "runs_for",
                               return_value=[run(44, 1055, status="completed",
                                                 conclusion="success")]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor") as sensor, \
             mock.patch.object(monitor, "notify"):
            monitor.monitor_repository(REPO, "", "TOKEN", config(), current, {}, 1791800010)
        data = sensor.call_args.args[1]
        self.assertEqual(data["state"], "completed")
        self.assertEqual(data["progress_percent"], 100)
        self.assertEqual(data["active_run_details"], [])
        self.assertEqual(data["active_run_count"], 0)


class TerminalDeliveryTests(unittest.TestCase):
    def test_failed_resend_preserves_attempt_for_next_poll(self):
        current = state()
        finished = run(42, 1055, status="completed", conclusion="success")
        payload = monitor.activity_payload(
            finished, {"progress_percent": 100, "current_step": "",
                       "completed_steps": 9, "total_steps": 9},
            REPO, "B&B")
        records = {"42": {
            "finished_at": 100, "last_final_sent_at": 100,
            "final_sent_count": 1, "final_payload": payload,
        }}
        current["activity_targets"] = {PHONE: {REPO: records}}
        with mock.patch.object(monitor, "runs_for", return_value=[finished]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify", side_effect=RuntimeError("phone unreachable")):
            monitor.monitor_repository(REPO, "", "TOKEN", config(), current, {}, 200)
        self.assertEqual(records["42"]["final_sent_count"], 1)
        with mock.patch.object(monitor, "runs_for", return_value=[finished]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify") as notify:
            monitor.monitor_repository(REPO, "", "TOKEN", config(), current, {}, 210)
        self.assertEqual(records["42"]["final_sent_count"], 2)
        self.assertEqual(notify.call_args.args[2]["data"]["progress"], 100)

    def test_rerun_with_same_github_id_restarts_tracking(self):
        current = state()
        records = {"42": {"finished_at": 100, "final_sent_count": 2,
                          "last_final_sent_at": 160,
                          "final_payload": {"message": "old completion"}}}
        current["activity_targets"] = {PHONE: {REPO: records}}
        with mock.patch.object(monitor, "runs_for", return_value=[run(42, 1055)]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify") as notify:
            monitor.monitor_repository(REPO, "", "TOKEN", config(), current, {}, 1791800010)
        self.assertNotIn("finished_at", records["42"])
        self.assertIn("CI #1055", notify.call_args.args[2]["title"])

    def test_legacy_finishing_record_is_eventually_removed(self):
        current = state()
        records = {"42": {"finished_at": 100}}  # v0.2.0 state without retry payload
        current["activity_targets"] = {PHONE: {REPO: records}}
        with mock.patch.object(monitor, "runs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify") as notify:
            monitor.monitor_repository(REPO, "", "TOKEN", config(), current, {}, 281)
        self.assertNotIn("42", records)
        self.assertEqual(notify.call_args.args[2]["message"], "clear_notification")


if __name__ == "__main__":
    unittest.main()
