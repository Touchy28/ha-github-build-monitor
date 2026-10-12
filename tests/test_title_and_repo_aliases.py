"""Compact iOS headlines, repository aliases and safe name persistence."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))
import monitor
import repo_selection

REPO = "Touchy28/more-tents"
OPTIONS = {"repositories": [REPO]}


def run(status="in_progress"):
    return {"id": 731, "run_number": 1055, "name": "CI",
            "status": status, "conclusion": "success",
            "created_at": "2026-10-12T10:00:00Z",
            "updated_at": "2026-10-12T10:04:30Z",
            "html_url": "https://github.com/Touchy28/more-tents/actions/runs/731"}


def progress(step_eta=None, total_eta=None):
    return {"progress_percent": 35, "completed_steps": 12, "total_steps": 23,
            "current_step": "Waiting for runner",
            "current_step_remaining_seconds": step_eta,
            "estimated_remaining_seconds": total_eta}


class CompactHeadlineTests(unittest.TestCase):
    def test_no_redundant_github_prefix_and_time_visible(self):
        now = monitor.timestamp("2026-10-12T10:03:40Z")
        payload = monitor.activity_payload(run(), progress(), REPO, now=now)
        self.assertEqual(payload["title"], "more-tents · CI #1055 · Restzeit –")
        self.assertNotIn("GitHub · ", payload["title"])
        self.assertNotIn("ca. 3", payload["message"])
        self.assertIn("12/23 Schritte", payload["message"])
        self.assertEqual(payload["data"]["critical_text"], "≈35%")
        self.assertEqual(payload["data"]["tag"], monitor.activity_tag(REPO, 731))

    def test_time_estimate_goes_into_title_when_available(self):
        payload = monitor.activity_payload(run(), progress(61, 720), REPO,
                                           display="B&B")
        self.assertEqual(payload["title"], "B&B · CI #1055 · ≈2/12m")
        self.assertNotIn("noch ca.", payload["message"])
        self.assertEqual(payload["data"]["progress"], 35)

    def test_finished_time_is_stable_and_not_elapsed_since_now(self):
        payload = monitor.activity_payload(run(status="completed"), progress(),
                                           REPO, display="B&B",
                                           now=monitor.timestamp("2026-10-12T14:00:00Z"))
        self.assertEqual(payload["title"], "B&B · CI #1055 · ✓")
        self.assertIn("Erfolgreich", payload["message"])

    def test_very_long_alias_keeps_time_suffix(self):
        payload = monitor.activity_payload(run(), progress(60, 720), REPO,
                                           display="Langer Kürzelname der Anwendung")
        self.assertTrue(payload["title"].endswith("· ≈1/12m"))
        self.assertLessEqual(len(payload["title"]), 35)

    def test_remaining_is_step_over_total_not_elapsed_or_eta_range(self):
        now = monitor.timestamp("2026-10-12T11:45:00Z")
        payload = monitor.activity_payload(run(), progress(50, 690), REPO,
                                           display="B&B", now=now)
        self.assertEqual(payload["title"], "B&B · CI #1055 · ≈1/12m")
        self.assertNotIn("⏱", payload["title"])

    def test_missing_step_eta_keeps_total_and_unknown_marker(self):
        self.assertEqual(monitor.activity_title(run(), progress(None, 690), REPO, "B&B"),
                         "B&B · CI #1055 · ≈–/12m")
        self.assertEqual(monitor.activity_title(run(), progress(50, None), REPO, "B&B"),
                         "B&B · CI #1055 · ≈1/–m")
        self.assertEqual(monitor.activity_title(run(), progress(), REPO, "B&B"),
                         "B&B · CI #1055 · Restzeit –")

    def test_total_eta_cannot_be_less_than_step_remaining(self):
        self.assertEqual(monitor.activity_title(run(), progress(300, 60), REPO, "B&B"),
                         "B&B · CI #1055 · ≈5/5m")

    def test_running_eta_rounded_up_and_no_fabricated_zero(self):
        self.assertEqual(monitor.activity_title(run(), progress(1, 61), REPO, "B&B"),
                         "B&B · CI #1055 · ≈1/2m")
        self.assertEqual(monitor.activity_title(run(), progress(0, -1), REPO, "B&B"),
                         "B&B · CI #1055 · Restzeit –")

    def test_missing_run_start_does_not_invent_remaining_time(self):
        bare = {"id": 731, "status": "queued"}
        self.assertEqual(monitor.activity_title(bare, progress(), REPO), "more-tents · Run #731 · Restzeit –")


class RepoAliasTests(unittest.TestCase):
    def test_preserve_old_selection_and_add_alias_without_changing_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo_selection.store_selection(root, [REPO])
            self.assertEqual(repo_selection.repository_aliases(root), {})
            repo_selection.store_selection(root, [REPO], {REPO: "B&B"})
            self.assertEqual(repo_selection.effective_repositories(OPTIONS, root), [REPO])
            self.assertEqual(repo_selection.display_name(REPO, repo_selection.repository_aliases(root)), "B&B")
            saved = json.loads(repo_selection.selection_file(root).read_text())
            self.assertEqual(saved["repositories"], [REPO])
            self.assertEqual(saved["aliases"][REPO.casefold()], "B&B")

    def test_display_name_survives_selection_only_updates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo_selection.store_selection(root, [REPO], {REPO: "B&B"})
            repo_selection.store_selection(root, [])
            self.assertEqual(repo_selection.repository_aliases(root)[REPO.casefold()], "B&B")
            repo_selection.store_selection(root, [REPO])
            self.assertEqual(repo_selection.repository_aliases(root)[REPO.casefold()], "B&B")

    def test_invalid_alias_prevented_before_disk_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo_selection.store_selection(root, [REPO], {REPO: "Before"})
            for invalid in ["x" * 33, "a" * 100]:
                with self.assertRaises(ValueError):
                    repo_selection.store_selection(root, [REPO], {REPO: invalid})
            self.assertEqual(repo_selection.repository_aliases(root)[REPO.casefold()], "Before")

    def test_case_insensitive_lookup(self):
        self.assertEqual(repo_selection.display_name(
            "Touchy28/more-tents", {"touchy28/more-tents": "🌳 B&B"}), "🌳 B&B")


if __name__ == "__main__":
    unittest.main()
