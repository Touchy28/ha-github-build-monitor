"""Native Companion App notification service picker tests."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_build_monitor"))

import mobile_notify
import mobile_notify_ui
import monitor

OLD = "mobile_app_iphone_von_matthias"
NEW = "mobile_app_ipad"
OTHER = "mobile_app_iphone_test"


class MobileNotifyTests(unittest.TestCase):
    def test_discovery_handles_real_ha_services_dictionary(self):
        payload = [
            {"domain": "light", "services": {"turn_on": {}, "turn_off": {}}},
            {"domain": "notify", "services": {
                OLD: {"name": "Phone"},
                NEW: {"name": "Tablet"},
                "send_message": {"name": "Generic"},
                "persistent_notification": {}
            }},
            {"domain": "notify", "services": ["notify." + OTHER]},
        ]
        self.assertEqual(mobile_notify.parse_services(payload), sorted([NEW, OLD, OTHER]))

    def test_discovery_rejects_non_mobile_and_bad_shape(self):
        self.assertEqual(mobile_notify.parse_services([
            {"domain": "notify", "services": {
                "send_message": {}, "mobile_app_bad/path": {}, "mobile_app_valid": {}
            }}
        ]), ["mobile_app_valid"])
        with self.assertRaises(ValueError):
            mobile_notify.parse_services({"notify": []})

    def test_normalize_allows_both_existing_forms(self):
        self.assertEqual(mobile_notify.normalize("notify." + OLD), OLD)
        self.assertEqual(mobile_notify.normalize(OLD), OLD)
        with self.assertRaises(ValueError):
            mobile_notify.normalize("notify.send_message")

    def test_saved_choice_overrides_native_without_changing_options(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            options = {"live_activity_notify_service": OLD,
                       "github_api_token": "fake-value"}
            self.assertEqual(mobile_notify.effective_service(options, root), OLD)
            mobile_notify.save_service(root, "notify." + NEW)
            self.assertEqual(mobile_notify.effective_service(options, root), NEW)
            self.assertEqual(json.loads(mobile_notify.selection_file(root).read_text()),
                             {"service": NEW})
            self.assertNotIn("fake-value", mobile_notify.selection_file(root).read_text())
            mobile_notify.clear_service(root)
            self.assertEqual(mobile_notify.effective_service(options, root), OLD)

    def test_invalid_service_is_not_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                mobile_notify.save_service(root, "notify.send_message")
            self.assertFalse(mobile_notify.selection_file(root).exists())

    def test_multi_targets_preserve_old_saved_single_and_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            opts = {"live_activity_notify_service": OLD}
            mobile_notify.save_service(root, OLD)
            self.assertEqual(mobile_notify.effective_services(opts, root), [OLD])
            mobile_notify.save_services(root, [OLD, NEW],
                                        {OLD: "Mein iPhone", NEW: "Kinder-iPad"})
            self.assertEqual(mobile_notify.effective_services(opts, root), [OLD, NEW])
            self.assertEqual(mobile_notify.saved_aliases(root)[NEW], "Kinder-iPad")
            mobile_notify.save_services(root, [], {OLD: "Mein iPhone"})
            self.assertEqual(mobile_notify.effective_services(opts, root), [])
            mobile_notify.clear_service(root)
            self.assertEqual(mobile_notify.effective_services(opts, root), [OLD])

    def test_invalid_multi_targets_or_aliases_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for selected, aliases in [
                ([OLD, OLD], {}), (["notify.send_message"], {}),
                ([OLD], {OLD: "X" * 49}),
            ]:
                with self.subTest(selected=selected, aliases=aliases):
                    with self.assertRaises(ValueError):
                        mobile_notify.save_services(root, selected, aliases)
            self.assertFalse(mobile_notify.selection_file(root).exists())

    def test_ha_get_services_authorized_and_never_sends_notification(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, limit=0):
                return json.dumps([
                    {"domain": "notify", "services": {OLD: {}, NEW: {}}}
                ]).encode("utf-8")
        calls = []
        def fetch(request, timeout):
            calls.append(request)
            return Response()
        with mock.patch.object(mobile_notify, "urlopen", side_effect=fetch):
            self.assertEqual(mobile_notify.discover_mobile_services("HA-SECRET"), [NEW, OLD])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get_method(), "GET")
        self.assertEqual(calls[0].full_url, "http://supervisor/core/api/services")
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer HA-SECRET")

    def test_discovery_does_not_return_api_token_errors(self):
        with self.assertRaises(ValueError):
            mobile_notify.discover_mobile_services("")
        with mock.patch.object(mobile_notify, "urlopen", side_effect=HTTPError(
            "http://supervisor/core/api/services", 403, "Forbidden", {}, io.BytesIO()
        )):
            with self.assertRaisesRegex(ValueError, "403"):
                mobile_notify.discover_mobile_services("secret")

    def test_dropdown_shows_only_allowed_choices_and_no_secrets(self):
        html = mobile_notify_ui.selector_html(
            OLD, [OLD, NEW], "fake-csrf", override_active=False)
        self.assertIn('name="target"', html)
        self.assertIn("iPhone von Matthias", html)
        self.assertIn("notify." + OLD, html)
        self.assertIn("notify." + NEW, html)
        self.assertIn('value="' + OLD + '" checked', html)
        self.assertNotIn("Authorization", html)

    def test_selection_is_safe_when_ha_api_is_unavailable(self):
        html = mobile_notify_ui.selector_html(
            OLD, None, "csrf", error="Cannot connect")
        self.assertIn("bestehende Einstellung bleibt erhalten", html)
        self.assertIn("Cannot connect", html)

    def test_native_fallback_available_during_api_error(self):
        html = mobile_notify_ui.selector_html(
            OLD, None, "csrf", error="Home Assistant offline", override_active=True)
        self.assertIn('name="use_native" value="1"', html)
        self.assertIn("Wert aus HA-App-Konfiguration verwenden", html)

    def test_switch_clears_old_notification_and_new_target_is_active(self):
        state = {
            "activities": {"Touchy28/more-tents": {"42": {"percent": 51}}},
            "active_mobile_notify_service": OLD,
        }
        with mock.patch.object(monitor, "notify") as notify:
            result = monitor.reconcile_mobile_target(NEW, OLD, state, "ha-token")
        self.assertEqual(result, NEW)
        self.assertEqual(state["activities"]["Touchy28/more-tents"], {})
        self.assertEqual(state["active_mobile_notify_service"], NEW)
        self.assertEqual(notify.call_args.args[0], OLD)
        self.assertEqual(notify.call_args.args[2]["message"], "clear_notification")

    def test_switch_retry_when_old_phone_unavailable(self):
        state = {
            "activities": {"Touchy28/more-tents": {"42": {"percent": 51}}},
            "active_mobile_notify_service": OLD,
        }
        with mock.patch.object(monitor, "notify", side_effect=RuntimeError("no push")):
            result = monitor.reconcile_mobile_target(NEW, OLD, state, "token")
        self.assertEqual(result, OLD)
        self.assertEqual(state["active_mobile_notify_service"], OLD)
        self.assertIn("42", state["activities"]["Touchy28/more-tents"])
        with mock.patch.object(monitor, "notify"):
            self.assertEqual(monitor.reconcile_mobile_target(NEW, OLD, state, "token"), NEW)

    def test_unchanged_target_keeps_live_activities(self):
        state = {"activities": {"r": {"2": {}}}, "active_mobile_notify_service": OLD}
        with mock.patch.object(monitor, "notify") as notify:
            self.assertEqual(monitor.reconcile_mobile_target(OLD, OLD, state, "token"), OLD)
        notify.assert_not_called()
        self.assertEqual(state["activities"], {"r": {"2": {}}})


if __name__ == "__main__":
    unittest.main()
