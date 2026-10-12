"""Live Activities are independently started, updated, and cleared on each phone."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))
import monitor

OLD = "mobile_app_iphone_von_matthias"
TABLET = "mobile_app_ipad"
THIRD = "mobile_app_android"
REPO = "Touchy28/more-tents"


def run(ident=42, status="in_progress", conclusion=None):
    return {"id": ident, "status": status, "conclusion": conclusion,
            "name": "HA Publish", "created_at": "2026-10-12T10:00:00Z"}


def progress():
    return {"progress_percent": 33, "current_step": "Compile",
            "completed_steps": 2, "total_steps": 5,
            "eta_lower_seconds": None, "eta_upper_seconds": None}


class MultiTargetTests(unittest.TestCase):
    def test_old_v017_state_migrates_only_to_previous_recipient(self):
        state = {"activities": {REPO: {"42": {"percent": 20}}},
                 "active_mobile_notify_service": OLD}
        with mock.patch.object(monitor, "notify") as send:
            chosen = monitor.reconcile_mobile_targets([OLD, TABLET], OLD, state, "TOKEN")
        self.assertEqual(chosen, [OLD, TABLET])
        self.assertEqual(state["activity_targets"][OLD][REPO]["42"]["percent"], 20)
        self.assertNotIn(TABLET, state["activity_targets"])
        send.assert_not_called()

    def test_per_device_progress_independently_throttled(self):
        phones = {}
        state = {"activities": {}, "active_mobile_notify_services": [OLD, TABLET],
                 "activity_targets": {}}
        monitor.reconcile_mobile_targets([OLD, TABLET], OLD, state, "TOKEN")
        config = {"live_activity_enabled": True,
                  "live_activity_notify_services": [OLD, TABLET]}
        with mock.patch.object(monitor, "runs_for", return_value=[run()]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify") as send:
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, 1791800010)
            self.assertEqual(send.call_count, 2)
            self.assertEqual({call.args[0] for call in send.call_args_list}, {OLD, TABLET})
            self.assertEqual(state["activity_targets"][OLD][REPO]["42"]["percent"],
                             state["activity_targets"][TABLET][REPO]["42"]["percent"])
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, 1791800020)
            self.assertEqual(send.call_count, 2)
            # Force one phone's old state to be behind so only it updates.
            state["activity_targets"][TABLET][REPO]["42"]["step"] = "Alter Schritt"
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, 1791800030)
            self.assertEqual(send.call_count, 3)
            self.assertEqual(send.call_args.args[0], TABLET)

    def test_one_offline_phone_does_not_block_other_phone(self):
        state = {"activity_targets": {}, "active_mobile_notify_services": [OLD, TABLET],
                 "activities": {}}
        monitor.reconcile_mobile_targets([OLD, TABLET], OLD, state, "TOKEN")
        cfg = {"live_activity_enabled": True,
               "live_activity_notify_services": [OLD, TABLET]}
        delivered = []
        def send(target, ha_token, payload):
            if target == OLD:
                raise RuntimeError("Phone temporarily offline")
            delivered.append((target, payload["message"]))
        with mock.patch.object(monitor, "runs_for", return_value=[run()]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify", side_effect=send):
            monitor.monitor_repository(REPO, "", "TOKEN", cfg, state, {}, 1791800010)
        self.assertEqual(delivered[0][0], TABLET)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(state["activity_targets"][OLD][REPO], {})
        self.assertIn("42", state["activity_targets"][TABLET][REPO])

    def test_remaining_time_in_message_updates_when_eta_changes(self):
        state = {"activities": {}, "active_mobile_notify_services": [OLD],
                 "activity_targets": {}}
        monitor.reconcile_mobile_targets([OLD], OLD, state, "TOKEN")
        config = {"live_activity_enabled": True,
                  "live_activity_notify_services": [OLD],
                  "repository_aliases": {REPO.casefold(): "B&B"}}
        def forecast(repo, run, jobs, history, now):
            return {"estimated_remaining_seconds": 630 - (now - 1791800010)}
        with mock.patch.object(monitor, "runs_for", return_value=[run()]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "predict", side_effect=forecast), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify") as sent:
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, 1791800010)
            self.assertEqual(sent.call_count, 1)
            self.assertEqual(sent.call_args.args[2]["title"], "B&B · Run #42")
            self.assertIn("≈–/11m", sent.call_args.args[2]["message"])
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, 1791800020)
            self.assertEqual(sent.call_count, 1)
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, 1791800050)
            self.assertEqual(sent.call_count, 2)
            self.assertEqual(sent.call_args.args[2]["title"], "B&B · Run #42")
            self.assertIn("≈–/10m", sent.call_args.args[2]["message"])

    def test_each_phone_receives_completion_then_removal(self):
        state = {"activity_targets": {}, "active_mobile_notify_services": [OLD, TABLET],
                 "activities": {}}
        monitor.reconcile_mobile_targets([OLD, TABLET], OLD, state, "TOKEN")
        config = {"live_activity_enabled": True,
                  "live_activity_notify_services": [OLD, TABLET]}
        now = 1791800010
        with mock.patch.object(monitor, "runs_for", side_effect=[
                [run()], *[[run(status="completed", conclusion="success")]
                           for _ in range(7)]]), \
             mock.patch.object(monitor, "jobs_for", return_value=[]), \
             mock.patch.object(monitor, "set_sensor"), \
             mock.patch.object(monitor, "notify") as send:
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now)
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 60)
            for target in (OLD, TABLET):
                self.assertIn("finished_at", state["activity_targets"][target][REPO]["42"])
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 120)
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 180)
            for target in (OLD, TABLET):
                self.assertEqual(state["activity_targets"][target][REPO]["42"]["final_sent_count"], 3)
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 300)
            for target in (OLD, TABLET):
                self.assertEqual(state["activity_targets"][target][REPO]["42"]["clear_sent_count"], 1)
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 360)
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 420)
            by_device = {}
            for c in send.call_args_list:
                by_device.setdefault(c.args[0], []).append(c.args[2]["message"])
            self.assertEqual(sum(x == "clear_notification" for x in by_device[OLD]), 3)
            self.assertEqual(sum(x == "clear_notification" for x in by_device[TABLET]), 3)
            self.assertEqual(sum("Erfolgreich abgeschlossen" in x for x in by_device[OLD]), 3)
            self.assertEqual(sum("Erfolgreich abgeschlossen" in x for x in by_device[TABLET]), 3)
            for target in (OLD, TABLET):
                self.assertIn("42", state["activity_targets"][target][REPO])
            monitor.monitor_repository(REPO, "", "TOKEN", config, state, {}, now + 480)
            self.assertFalse(state["activity_targets"][OLD][REPO])
            self.assertFalse(state["activity_targets"][TABLET][REPO])

    def test_deselecting_one_device_only_clears_its_own_runs(self):
        state = {"activity_targets": {
            OLD: {REPO: {"42": {"percent": 19}}},
            TABLET: {REPO: {"42": {"percent": 19}}}},
            "active_mobile_notify_services": [OLD, TABLET]}
        with mock.patch.object(monitor, "notify") as send:
            monitor.reconcile_mobile_targets([TABLET], OLD, state, "TOKEN")
        self.assertNotIn(OLD, state["activity_targets"])
        self.assertIn("42", state["activity_targets"][TABLET][REPO])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.args[0], OLD)

    def test_removal_retries_old_device_if_push_fails(self):
        state = {"activity_targets": {
            OLD: {REPO: {"42": {"percent": 19}}},
            TABLET: {REPO: {"42": {"percent": 19}}}},
            "active_mobile_notify_services": [OLD, TABLET]}
        with mock.patch.object(monitor, "notify", side_effect=RuntimeError("timeout")):
            monitor.reconcile_mobile_targets([TABLET], OLD, state, "TOKEN")
        self.assertIn("42", state["activity_targets"][OLD][REPO])
        self.assertIn("42", state["activity_targets"][TABLET][REPO])
        with mock.patch.object(monitor, "notify") as send:
            monitor.reconcile_mobile_targets([TABLET], OLD, state, "TOKEN")
        self.assertNotIn(OLD, state["activity_targets"])
        self.assertEqual(send.call_count, 1)

    def test_empty_selection_clears_all_existing_activities(self):
        state = {"activity_targets": {
            OLD: {REPO: {"42": {"percent": 19}}},
            TABLET: {REPO: {"42": {"percent": 19}}}},
            "active_mobile_notify_services": [OLD, TABLET]}
        with mock.patch.object(monitor, "notify") as send:
            monitor.reconcile_mobile_targets([], OLD, state, "TOKEN")
        self.assertEqual(send.call_count, 2)
        self.assertEqual(state["activity_targets"], {})
        self.assertEqual(state["active_mobile_notify_services"], [])


if __name__ == "__main__":
    unittest.main()
