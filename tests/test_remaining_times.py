"""Current step ETA uses real GitHub step timestamps and learned samples."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))

from core import history_key, snapshot, timestamp
from monitor import activity_title
from forecast import predict

REPO = "Touchy28/more-tents"
RUN = {"id": 42, "status": "in_progress", "name": "Publish"}
NOW = timestamp("2026-10-12T12:00:00Z")


def job(state="in_progress", started="2026-10-12T11:59:30Z", name="compile"):
    return {"name": "build", "status": state, "steps": [
        {"name": name, "status": state, "started_at": started}
    ]}


def historic(j, samples):
    return {"steps": {history_key(REPO, j, j["steps"][0], "Publish"): samples}}


class RemainingTimesTests(unittest.TestCase):
    def test_running_step_remaining_uses_successful_historical_samples(self):
        j = job()
        value = snapshot(REPO, RUN, [j], historic(j, [90, 95, 100]), now=NOW)
        self.assertEqual(value["current_step_remaining_seconds"], 65)
        self.assertEqual(value["current_step"], "compile")
        self.assertEqual(value["current_job"], "build")

    def test_requires_three_real_samples_no_guessed_one_minute(self):
        j = job()
        for samples in ([], [90], [90, 95]):
            with self.subTest(samples=samples):
                result = snapshot(REPO, RUN, [j], historic(j, samples), NOW)
                self.assertIsNone(result["current_step_remaining_seconds"])

    def test_no_eta_when_queued_without_started_timestamp(self):
        j = job("queued", None, "Waiting for runner")
        value = snapshot(REPO, {"id": 42, "status": "queued", "name": "Publish"},
                         [j], historic(j, [45, 50, 55]), NOW)
        self.assertIsNone(value["current_step_remaining_seconds"])
        # The production flow merges the conservative whole-run forecast
        # after snapshot; without 3 prior complete workflows the total ETA
        # also remains unknown rather than using a guessed step sum.
        value.update(predict(REPO, RUN, [j], {}, NOW))
        self.assertEqual(activity_title(RUN, value, REPO, "B&B"),
                         "B&B · Restzeit –")

    def test_overdue_step_is_unknown_not_fake_zero(self):
        j = job(started="2026-10-12T11:55:00Z")
        value = snapshot(REPO, RUN, [j], historic(j, [60, 65, 75]), NOW)
        self.assertIsNone(value["current_step_remaining_seconds"])

    def test_completed_step_has_no_remaining_eta(self):
        j = job("completed", "2026-10-12T11:58:00Z")
        value = snapshot(REPO, {"id": 42, "status": "completed", "name": "Publish"},
                         [j], historic(j, [90, 95, 100]), NOW)
        self.assertIsNone(value["current_step_remaining_seconds"])

    def test_real_running_step_preferred_over_queued_placeholder(self):
        queued = job("queued", None, "Waiting for runner")
        active = job(started="2026-10-12T11:59:30Z")
        value = snapshot(REPO, RUN, [queued, active],
                         historic(active, [80, 90, 100]), NOW)
        self.assertEqual(value["current_step"], "compile")
        self.assertEqual(value["current_step_remaining_seconds"], 60)

    def test_invalid_step_history_does_not_create_eta(self):
        j = job()
        value = snapshot(REPO, RUN, [j], historic(j, ["bad", -1, 90, None]), NOW)
        self.assertIsNone(value["current_step_remaining_seconds"])


if __name__ == "__main__":
    unittest.main()
