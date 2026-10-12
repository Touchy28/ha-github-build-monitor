"""Learning dashboard/ingress, reset, security and regression tests."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))

import core
import forecast
import learning_store
import learning_ui
import monitor


REPO = "Touchy28/more-tents"
DSO = "Touchy28/DSO-Optimizer"


def run(ident=1, created="2026-10-12T05:10:00Z", updated="2026-10-12T05:15:00Z"):
    return {"id": ident, "workflow_id": 77,
            "name": "Publish Home Assistant app", "status": "completed",
            "conclusion": "success", "created_at": created, "updated_at": updated}


def job():
    return {"name": "publish", "status": "completed", "runner_name": "more-tents-ha-1",
            "started_at": "2026-10-12T05:10:10Z",
            "completed_at": "2026-10-12T05:14:50Z",
            "steps": [{"name": "Flutter", "status": "completed", "conclusion": "success",
                       "started_at": "2026-10-12T05:10:15Z",
                       "completed_at": "2026-10-12T05:14:30Z"}]}


def history():
    records = {"steps": {}, "learned_runs": [], "forecast": {"workflows": {}, "seen": []}}
    for i in range(1, 4):
        forecast.observe(REPO, run(ident=i), [job()], records)
        core.learn(REPO, run(ident=i), [job()], records)
    forecast.observe(DSO, run(ident=8), [job()], records)
    core.learn(DSO, run(ident=8), [job()], records)
    return records


class HistoryResetTests(unittest.TestCase):
    def test_summary_has_counts_times_and_names(self):
        view = learning_store.summary(history(), [REPO, DSO])
        self.assertEqual(view[0]["workflow_samples"], 3)
        self.assertEqual(view[0]["step_samples"], 3)
        self.assertEqual(view[0]["workflows"][0]["name"], "Publish Home Assistant app")
        self.assertEqual(view[0]["workflows"][0]["median_queue_seconds"], 10)
        self.assertTrue(view[0]["workflows"][0]["prognosis_ready"])
        self.assertEqual(view[1]["workflow_samples"], 1)

    def test_v014_history_names_can_be_recovered(self):
        data = history()
        key = REPO.casefold() + ":77"
        for sample in data["forecast"]["workflows"][key]:
            sample.pop("workflow_name", None)
        data["workflow_names"] = {key: "Publish Home Assistant app"}
        rows = learning_store.summary(data, [REPO])
        self.assertEqual(rows[0]["workflows"][0]["name"], "Publish Home Assistant app")

    def test_step_breakdown_nested_by_job(self):
        records = history()
        rows = learning_store.step_breakdown(records, REPO, "Publish Home Assistant app")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job"], "publish")
        self.assertEqual(rows[0]["steps"][0]["name"], "Flutter")
        self.assertEqual(rows[0]["steps"][0]["samples"], 3)
        self.assertEqual(rows[0]["steps"][0]["median_seconds"], 255)
        self.assertEqual(learning_store.step_breakdown(records, REPO, "Other"), [])

    def test_reset_one_preserves_other_repository(self):
        data = history()
        cutoff = core.timestamp("2026-10-12T06:00:00Z")
        learning_store.reset_history(data, REPO, cutoff)
        summary = learning_store.summary(data, [REPO, DSO])
        self.assertEqual(summary[0]["step_samples"], 0)
        self.assertEqual(summary[0]["workflow_samples"], 0)
        self.assertEqual(summary[1]["step_samples"], 1)
        self.assertEqual(summary[1]["workflow_samples"], 1)
        self.assertTrue(data["v010_migration_done"])
        self.assertFalse(learning_store.learning_allowed(REPO, run(4), data))
        self.assertTrue(learning_store.learning_allowed(DSO, run(4), data))

    def test_reset_blocks_old_learning_but_allows_new(self):
        data = history()
        cutoff = core.timestamp("2026-10-12T06:00:00Z")
        learning_store.reset_history(data, REPO, cutoff)
        self.assertFalse(forecast.observe(REPO, run(200), [job()], data))
        self.assertFalse(core.learn(REPO, run(201), [job()], data))
        future = run(300, updated="2026-10-12T08:00:00Z")
        self.assertTrue(forecast.observe(REPO, future, [job()], data))
        self.assertTrue(core.learn(REPO, future, [job()], data))

    def test_reset_all_preserves_unrelated_state(self):
        data = history()
        data["internal_marker"] = {"safe": True}
        learning_store.reset_history(data, "all", 2000000000.0)
        self.assertEqual(data["internal_marker"], {"safe": True})
        self.assertEqual(data["forecast"]["workflows"], {})
        self.assertEqual(data["learned_runs"], [])
        self.assertEqual(data["steps"], {})
        self.assertFalse(learning_store.learning_allowed(DSO, run(), data))

    def test_monitor_applies_pending_reset_and_does_not_replay(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            original = history()
            (root / "reset-learning-command.json").write_text(
                json.dumps({"scope": REPO, "at": 1790000000., "csrf_checked": True}))
            self.assertTrue(monitor.apply_pending_learning_reset(root, original))
            self.assertFalse((root / "reset-learning-command.json").exists())
            self.assertEqual(learning_store.summary(original, [REPO])[0]["workflow_samples"], 0)
            persisted = json.loads((root / "monitor_history.json").read_text())
            self.assertEqual(persisted["forecast"]["workflows"].get(REPO.lower() + ":77"), None)
            self.assertFalse(monitor.apply_pending_learning_reset(root, original))


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "options.json").write_text(json.dumps({
            "github_api_token": "SECRET_DO_NOT_SHOW",
            "repositories": [REPO, DSO],
            "live_activity_notify_service": "mobile_app_iphone_von_matthias",
        }))
        (self.root / "monitor_history.json").write_text(json.dumps(history()))
        self.github_repos = [
            {"full_name": REPO, "private": False,
             "description": "Bäume & Bienen", "archived": False},
            {"full_name": DSO, "private": True,
             "description": "DSO Optimizer", "archived": False},
            {"full_name": "Touchy28/new-project", "private": False,
             "description": "", "archived": False},
        ]
        self.github_fetch = mock.patch("repo_selection_ui.discover",
                                       return_value=self.github_repos)
        self.github_fetcher = self.github_fetch.start()
        self.mobile_fetch = mock.patch("mobile_notify_ui.discover_mobile_services",
                                       return_value=["mobile_app_ipad",
                                                     "mobile_app_iphone_von_matthias"])
        self.mobile_fetcher = self.mobile_fetch.start()
        self.server = learning_ui.start(self.root, port=0, host="127.0.0.1",
                                        allowed_peers={"127.0.0.1"})
        self.server.ha_token = "TEST_HA_SUPERVISOR_SECRET"
        self.url = "http://127.0.0.1:" + str(self.server.server_address[1]) + "/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.github_fetch.stop()
        self.mobile_fetch.stop()
        self.temp.cleanup()

    def test_secure_html_without_token(self):
        with urlopen(self.url, timeout=4) as r:
            page = r.read().decode("utf-8")
            self.assertEqual(r.status, 200)
            self.assertIn("no-store", r.headers["Cache-Control"])
            self.assertIn("frame-ancestors", r.headers["Content-Security-Policy"])
        self.assertIn("Publish Home Assistant app", page)
        self.assertIn("Lerndaten dieses Repositories zurücksetzen", page)
        self.assertNotIn("SECRET_DO_NOT_SHOW", page)

    def post(self, scope=REPO, csrf=None, confirm="yes"):
        body = urlencode({"scope": scope,
                          "csrf": self.server.csrf if csrf is None else csrf,
                          "confirm": confirm}).encode("utf-8")
        req = Request(self.url + "reset", data=body, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        return urlopen(req, timeout=4)

    def test_token_based_repo_selection_persists(self):
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        self.assertIn('name="repository" value="' + REPO + '" checked', html)
        self.assertIn("Touchy28/new-project", html)
        self.assertNotIn("SECRET_DO_NOT_SHOW", html)
        form = [("csrf", self.server.csrf), ("repository", "Touchy28/new-project")]
        for entry in self.github_repos:
            name = entry["full_name"]
            form.extend([("listed", name), ("alias", "B&B" if name == REPO else "")])
        values = urlencode(form).encode("utf-8")
        request = Request(
            self.url + "repositories", data=values, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(request, timeout=4) as result:
            self.assertEqual(result.status, 200)
        from repo_selection import effective_repositories
        options = json.loads((self.root / "options.json").read_text())
        self.assertEqual(effective_repositories(options, self.root),
                         ["Touchy28/new-project"])
        self.assertEqual(options["repositories"], [REPO, DSO])
        self.assertEqual(options["github_api_token"], "SECRET_DO_NOT_SHOW")

    def test_mobile_dropdown_is_discovered_and_native_service_selected(self):
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        self.assertIn('name="target"', html)
        self.assertIn("mobile_app_iphone_von_matthias", html)
        self.assertIn("mobile_app_ipad", html)
        self.assertIn("iPhone von Matthias", html)
        self.assertIn('name="alias"', html)
        self.assertNotIn("TEST_HA_SUPERVISOR_SECRET", html)

    def test_mobile_selection_persists_separately_and_preserves_options(self):
        with urlopen(self.url, timeout=4):
            pass
        form = urlencode([
            ("csrf", self.server.csrf),
            ("listed", "mobile_app_ipad"), ("alias", "Familien-iPad"),
            ("listed", "mobile_app_iphone_von_matthias"), ("alias", ""),
            ("target", "mobile_app_ipad"),
            ("target", "mobile_app_iphone_von_matthias"),
        ]).encode("utf-8")
        req = Request(self.url + "notify-service", data=form, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=4) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('id="devices" open', response.read().decode("utf-8"))
        from mobile_notify import effective_service, selection_file
        options = json.loads((self.root / "options.json").read_text())
        self.assertEqual(effective_service(options, self.root), "mobile_app_ipad")
        from mobile_notify import effective_services, saved_aliases
        self.assertEqual(effective_services(options, self.root),
                         ["mobile_app_ipad", "mobile_app_iphone_von_matthias"])
        self.assertEqual(saved_aliases(self.root)["mobile_app_ipad"], "Familien-iPad")
        self.assertEqual(options["live_activity_notify_service"],
                         "mobile_app_iphone_von_matthias")
        self.assertEqual(json.loads(selection_file(self.root).read_text())["services"],
                         ["mobile_app_ipad", "mobile_app_iphone_von_matthias"])

    def test_mobile_picker_falls_back_to_ha_option(self):
        from mobile_notify import effective_service, save_service
        save_service(self.root, "mobile_app_ipad")
        form = urlencode({"csrf": self.server.csrf,
                          "use_native": "1"}).encode("utf-8")
        req = Request(self.url + "notify-service", data=form, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=4):
            pass
        self.assertEqual(effective_service(
            json.loads((self.root / "options.json").read_text()), self.root
        ), "mobile_app_iphone_von_matthias")

    def test_unlisted_mobile_action_rejected(self):
        with urlopen(self.url, timeout=4):
            pass
        form = urlencode({"csrf": self.server.csrf,
                          "service": "notify.send_message"}).encode("utf-8")
        req = Request(self.url + "notify-service", data=form, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=4)
        self.assertEqual(err.exception.code, 400)

    def test_mobile_form_rejects_expired_cache_and_csrf(self):
        form = urlencode({"csrf": self.server.csrf,
                          "service": "mobile_app_ipad"}).encode("utf-8")
        req = Request(self.url + "notify-service", data=form, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=4)
        self.assertEqual(err.exception.code, 409)
        with urlopen(self.url, timeout=4):
            pass
        form = urlencode({"csrf": "wrong",
                          "service": "mobile_app_ipad"}).encode("utf-8")
        req = Request(self.url + "notify-service", data=form, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as err:
            urlopen(req, timeout=4)
        self.assertEqual(err.exception.code, 403)

    def test_ha_mobile_list_is_cached_and_refreshable(self):
        with urlopen(self.url, timeout=4):
            pass
        with urlopen(self.url, timeout=4):
            pass
        self.assertEqual(self.mobile_fetcher.call_count, 1)
        with urlopen(self.url + "?refresh_mobile=1", timeout=4) as response:
            self.assertIn('id="devices" open', response.read().decode("utf-8"))
        self.assertEqual(self.mobile_fetcher.call_count, 2)

    def test_can_uncheck_all_monitored_repositories(self):
        with urlopen(self.url, timeout=4):
            pass
        form = [("csrf", self.server.csrf)]
        for entry in self.github_repos:
            form.extend([("listed", entry["full_name"]), ("alias", "")])
        data = urlencode(form).encode("utf-8")
        request = Request(self.url + "repositories", data=data, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(request, timeout=4):
            pass
        from repo_selection import effective_repositories
        config = json.loads((self.root / "options.json").read_text())
        self.assertEqual(effective_repositories(config, self.root), [])
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        self.assertIn("kein Repository zur Überwachung", html)

    def test_many_repositories_can_be_saved(self):
        extra = [{"full_name": "Touchy28/extra-" + str(i).zfill(3),
                  "private": False, "description": "", "archived": False}
                 for i in range(120)]
        self.github_repos.extend(extra)
        with urlopen(self.url, timeout=4):
            pass
        items = [("csrf", self.server.csrf)]
        items.extend(("repository", item["full_name"]) for item in extra)
        for entry in self.github_repos:
            items.extend([("listed", entry["full_name"]), ("alias", "")])
        data = urlencode(items).encode("utf-8")
        self.assertGreater(len(data), 2048)
        req = Request(self.url + "repositories", data=data, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(req, timeout=4) as response:
            self.assertEqual(response.status, 200)
        from repo_selection import effective_repositories
        chosen = effective_repositories({"repositories": [REPO]}, self.root)
        self.assertEqual(len(chosen), 120)

    def test_selection_rejects_repo_not_authorized_by_token(self):
        with urlopen(self.url, timeout=4):
            pass
        data = urlencode({"csrf": self.server.csrf,
                          "repository": "Unlisted/private"}).encode("utf-8")
        request = Request(self.url + "repositories", data=data, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=4)
        self.assertEqual(error.exception.code, 400)
        self.assertFalse((self.root / "monitored_repositories.json").exists())

    def test_selection_requires_repository_list_for_current_token(self):
        data = urlencode({"csrf": self.server.csrf,
                          "repository": REPO}).encode("utf-8")
        request = Request(self.url + "repositories", data=data, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=4)
        self.assertEqual(error.exception.code, 409)

    def test_selection_rejects_csrf(self):
        with urlopen(self.url, timeout=4):
            pass
        data = urlencode({"csrf": "invalid", "repository": REPO}).encode("utf-8")
        request = Request(self.url + "repositories", data=data, method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=4)
        self.assertEqual(error.exception.code, 403)

    def test_selection_refreshes_from_github_when_requested(self):
        with urlopen(self.url, timeout=4):
            pass
        with urlopen(self.url + "?refresh=1", timeout=4):
            pass
        self.assertEqual(self.github_fetcher.call_count, 2)

    def test_multilevel_time_values_collapsed_by_default(self):
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        self.assertIn('class="repo-fold"', html)
        self.assertIn('class="workflow-fold"', html)
        self.assertIn('class="time-fold"', html)
        self.assertIn('class="runner-fold"', html)
        self.assertIn('Gelernte Schrittzeiten', html)
        self.assertIn('📂 publish', html)
        self.assertIn('Flutter', html)
        self.assertIn('class="reset-fold"', html)
        # Each level uses native <details> (no open attribute -> collapsed).
        self.assertNotIn('<details class="repo-fold" open', html)
        self.assertNotIn('<details class="workflow-fold" open', html)
        self.assertNotIn('<details class="time-fold" open', html)
        self.assertNotIn('<details class="runner-fold" open', html)
        self.assertIn('Typische Gesamtdauer', html)
        self.assertIn('Typische Wartezeit', html)
        self.assertIn('Bisherige Spannweite', html)
        self.assertIn("Lerndaten dieses Repositories zurücksetzen", html)

    def test_back_navigation_and_unified_configuration_panel(self):
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        self.assertIn('href="/hassio" target="_top"', html)
        self.assertIn('← Zurück zu Apps', html)
        self.assertIn('href="#settings"', html)
        self.assertIn('id="settings"', html)
        self.assertIn('GitHub-Token', html)
        self.assertIn('GitHub Build Monitor', html)
        self.assertNotIn('SECRET_DO_NOT_SHOW', html)
        self.assertIn('aria-label="GitHub"', html)

    def test_repository_picker_collapsed_unless_error_or_saved(self):
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        self.assertIn('<details class="card repo-picker" id="repositories"', html)
        self.assertNotIn('<details class="card repo-picker" id="repositories" open', html)
        from repo_selection_ui import selector_html
        forced = selector_html([REPO], [], "csrf", error="GitHub momentan nicht erreichbar")
        self.assertIn('<details class="card repo-picker" id="repositories" open', forced)
        self.assertIn('GitHub momentan nicht erreichbar', forced)

    def test_device_section_is_between_repositories_and_settings(self):
        with urlopen(self.url, timeout=4) as response:
            html = response.read().decode("utf-8")
        repo = html.index('id="repositories"')
        devices = html.index('id="devices"')
        settings = html.index('id="settings"')
        self.assertLess(repo, devices)
        self.assertLess(devices, settings)
        self.assertIn('href="#devices"', html)
        self.assertNotIn('<details class="card" id="devices" open', html)
        self.assertIn('class="selection-list"', html)
        self.assertIn('class="selection-choice"', html)
        self.assertIn('Anzeigename / Abkürzung', html)
        self.assertIn('Anzeigename (optional)', html)

    def test_save_repository_alias_shows_in_learning_and_form(self):
        with urlopen(self.url, timeout=4):
            pass
        form = [("csrf", self.server.csrf), ("repository", REPO)]
        for entry in self.github_repos:
            repo = entry["full_name"]
            form.extend([("listed", repo), ("alias", "B&B" if repo == REPO else "")])
        request = Request(self.url + "repositories", data=urlencode(form).encode("utf-8"),
                          method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urlopen(request, timeout=4) as response:
            html = response.read().decode("utf-8")
        from repo_selection import effective_repositories, repository_aliases
        self.assertEqual(effective_repositories(
            json.loads((self.root / "options.json").read_text()), self.root), [REPO])
        self.assertEqual(repository_aliases(self.root)[REPO.lower()], "B&B")
        self.assertIn("B&amp;B", html)
        self.assertIn("Touchy28/more-tents", html)
        self.assertIn('id="devices"', html)
        self.assertNotIn("SECRET_DO_NOT_SHOW", html)

    def test_alias_validation_rejects_too_long(self):
        with urlopen(self.url, timeout=4):
            pass
        form = [("csrf", self.server.csrf), ("repository", REPO)]
        for entry in self.github_repos:
            repo = entry["full_name"]
            form.extend([("listed", repo), ("alias", "X" * 33 if repo == REPO else "")])
        request = Request(self.url + "repositories", data=urlencode(form).encode("utf-8"),
                          method="POST",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=4)
        self.assertEqual(error.exception.code, 400)
        self.assertFalse((self.root / "monitored_repositories.json").exists())

    def test_binary_assets_and_panel_icon(self):
        folder = Path(__file__).resolve().parents[1] / "github_build_monitor"
        for file in ("icon.png", "logo.png"):
            self.assertEqual((folder / file).read_bytes()[:8],
                             b"\x89PNG\r\n\x1a\n")
        configuration = (folder / "config.yaml").read_text()
        self.assertIn('panel_icon: mdi:github', configuration)
        self.assertRegex(configuration, r'(?m)^version: "[0-9]+[.][0-9]+[.][0-9]+"')

    def test_post_queues_and_monitor_applies(self):
        with self.post() as response:
            self.assertEqual(response.status, 200)  # urllib follows 303 to GET
        command = json.loads((self.root / "reset-learning-command.json").read_text())
        self.assertEqual(command["scope"], REPO)
        data = json.loads((self.root / "monitor_history.json").read_text())
        self.assertEqual(learning_store.summary(data, [REPO])[0]["workflow_samples"], 3)
        self.assertTrue(monitor.apply_pending_learning_reset(self.root, data))
        self.assertEqual(learning_store.summary(data, [REPO])[0]["workflow_samples"], 0)

    def test_post_rejects_missing_confirmation(self):
        with self.assertRaises(HTTPError) as result:
            self.post(confirm="no")
        self.assertEqual(result.exception.code, 403)
        self.assertFalse((self.root / "reset-learning-command.json").exists())

    def test_post_rejects_bad_csrf(self):
        with self.assertRaises(HTTPError) as result:
            self.post(csrf="bad-token")
        self.assertEqual(result.exception.code, 403)

    def test_cannot_reset_unknown_repository(self):
        with self.assertRaises(HTTPError) as result:
            self.post(scope="someone/other-repo")
        self.assertEqual(result.exception.code, 400)

    def test_ingress_source_ip_is_required(self):
        self.server.allowed_peers = {"172.30.32.2"}
        with self.assertRaises(HTTPError) as result:
            urlopen(self.url, timeout=4)
        self.assertEqual(result.exception.code, 403)
        with self.assertRaises(HTTPError) as result:
            self.post()
        self.assertEqual(result.exception.code, 403)

    def test_while_reset_pending_second_request_rejected(self):
        with self.post():
            pass
        with self.assertRaises(HTTPError) as result:
            self.post(scope="all")
        self.assertEqual(result.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
)

    def test_post_queues_and_monitor_applies(self):
        with self.post() as response:
            self.assertEqual(response.status, 200)  # urllib follows 303 to GET
        command = json.loads((self.root / "reset-learning-command.json").read_text())
        self.assertEqual(command["scope"], REPO)
        data = json.loads((self.root / "monitor_history.json").read_text())
        self.assertEqual(learning_store.summary(data, [REPO])[0]["workflow_samples"], 3)
        self.assertTrue(monitor.apply_pending_learning_reset(self.root, data))
        self.assertEqual(learning_store.summary(data, [REPO])[0]["workflow_samples"], 0)

    def test_post_rejects_missing_confirmation(self):
        with self.assertRaises(HTTPError) as result:
            self.post(confirm="no")
        self.assertEqual(result.exception.code, 403)
        self.assertFalse((self.root / "reset-learning-command.json").exists())

    def test_post_rejects_bad_csrf(self):
        with self.assertRaises(HTTPError) as result:
            self.post(csrf="bad-token")
        self.assertEqual(result.exception.code, 403)

    def test_cannot_reset_unknown_repository(self):
        with self.assertRaises(HTTPError) as result:
            self.post(scope="someone/other-repo")
        self.assertEqual(result.exception.code, 400)

    def test_ingress_source_ip_is_required(self):
        self.server.allowed_peers = {"172.30.32.2"}
        with self.assertRaises(HTTPError) as result:
            urlopen(self.url, timeout=4)
        self.assertEqual(result.exception.code, 403)
        with self.assertRaises(HTTPError) as result:
            self.post()
        self.assertEqual(result.exception.code, 403)

    def test_while_reset_pending_second_request_rejected(self):
        with self.post():
            pass
        with self.assertRaises(HTTPError) as result:
            self.post(scope="all")
        self.assertEqual(result.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
