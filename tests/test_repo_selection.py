"""Repository discovery and persistent watch-list tests, no live GitHub calls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))
import repo_selection
from repo_selection_ui import get_available, cached_available


REPO = "Touchy28/more-tents"
DSO = "Touchy28/DSO-Optimizer"


class RepoSelectionTests(unittest.TestCase):
    def test_selection_defaults_to_existing_addon_options(self):
        with tempfile.TemporaryDirectory() as folder:
            options = {"repositories": [REPO, DSO]}
            self.assertEqual(repo_selection.effective_repositories(options, Path(folder)),
                             [REPO, DSO])

    def test_empty_selection_is_not_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            repo_selection.store_selection(path, [])
            self.assertEqual(repo_selection.effective_repositories(
                {"repositories": [REPO, DSO]}, path), [])

    def test_only_repository_names_are_stored(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            repo_selection.store_selection(path, [REPO, DSO])
            content = (path / "monitored_repositories.json").read_text()
            self.assertEqual(json.loads(content), {"repositories": [REPO, DSO]})
            self.assertNotIn("github_api_token", content)

    def test_invalid_selection_not_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            with self.assertRaises(ValueError):
                repo_selection.store_selection(path, ["../root", REPO])
            self.assertFalse((path / "monitored_repositories.json").exists())

    def test_discovery_requires_token(self):
        with self.assertRaises(ValueError):
            repo_selection.discover("")

    def test_discovery_pagination_and_metadata(self):
        class FakeResponse:
            def __init__(self, data):
                self.data = data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit=None):
                return json.dumps(self.data).encode("utf-8")
        many = [
            {"full_name": f"Touchy28/repo-{i:03}", "private": False,
             "description": None} for i in range(100)]
        final = [{"full_name": DSO, "private": True,
                  "description": "Private test", "archived": False}]
        requests = []
        def fetch(req, timeout):
            requests.append(req)
            return FakeResponse(many if len(requests) == 1 else final)
        with mock.patch.object(repo_selection, "urlopen", side_effect=fetch):
            result = repo_selection.discover("ghp_FAKE_TOKEN")
        self.assertEqual(len(result), 101)
        self.assertTrue(any(v["full_name"] == DSO and v["private"] for v in result))
        self.assertIn("Authorization", requests[0].headers)
        self.assertTrue(requests[0].full_url.startswith("https://api.github.com/user/repos"))
        self.assertIn("page=2", requests[-1].full_url)

    def test_listing_cache_never_exposes_secret(self):
        class Server:
            pass
        from threading import Lock
        server = Server()
        server.repositories_lock = Lock()
        server.repositories_cache = {}
        with mock.patch("repo_selection_ui.discover", return_value=[
            {"full_name": REPO, "private": False}
        ]) as fetch:
            list1, err1 = get_available(server, "secret")
            list2, err2 = get_available(server, "secret")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(list1, list2)
        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertNotIn("secret", repr(server.repositories_cache))
        self.assertIsNotNone(cached_available(server, "secret"))
        self.assertIsNone(cached_available(server, "different-token"))


if __name__ == "__main__":
    unittest.main()
