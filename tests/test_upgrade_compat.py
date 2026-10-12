import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'github_build_monitor'))
import core
import monitor


class UpgradeRegressionTests(unittest.TestCase):
    def test_entity_ids_stable(self):
        self.assertEqual(core.sensor_id('Touchy28/more-tents'), 'sensor.github_runner_touchy28_more_tents_18b499')
        self.assertEqual(core.sensor_id('Touchy28/DSO-Optimizer'), 'sensor.github_runner_touchy28_dso_optimizer_c0e18c')

    def test_legacy_service_forms_supported(self):
        self.assertEqual(core.notify_service('mobile_app_test'), 'mobile_app_test')
        self.assertEqual(core.notify_service('notify.mobile_app_test'), 'mobile_app_test')

    def test_legacy_sensor_state_and_attributes(self):
        with mock.patch.object(monitor, 'api_call') as post:
            monitor.set_sensor('Touchy28/more-tents', {
                'state': 'in_progress', 'progress_percent': 43, 'completed_steps': 3,
                'total_steps': 8, 'current_step': 'compile', 'current_job': 'build',
                'estimated_remaining_seconds': 30, 'active_run_count': 2,
            }, 'fake')
        args = post.call_args.kwargs['data']
        self.assertEqual(args['state'], 'running')
        attrs = args['attributes']
        for key, value in [('progress', 43), ('steps_done', 3), ('steps_total', 8),
                           ('step', 'compile'), ('job', 'build'), ('eta_seconds', 30),
                           ('active_runs', 2)]:
            with self.subTest(key=key):
                self.assertEqual(attrs[key], value)

    def test_old_queued_runs_ignored(self):
        now = core.timestamp('2026-10-12T12:00:00Z')
        old = {'status': 'queued', 'created_at': '2026-09-01T12:00:00Z'}
        self.assertFalse(monitor.is_active(old, now))
        recent = {'status': 'queued', 'created_at': '2026-10-12T11:55:00Z'}
        self.assertTrue(monitor.is_active(recent, now))

    def test_v010_history_migrates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / 'github-build-monitor-state'
            previous.mkdir()
            key = json.dumps(['touchy28/more-tents', 'Build', 'build', 'compile'])
            (previous / 'history-v1.json').write_text(
                json.dumps({'durations': {key: [12.0, 14.0]}, 'seen_job_ids': ['3']}))
            data = monitor.migrate_history(root, {})
            new_key = core.history_key('Touchy28/more-tents',
                                       {'name': 'build'}, {'name': 'compile'}, 'Build')
            self.assertEqual(data['steps'][new_key], [12.0, 14.0])
            self.assertTrue(data['v010_migration_done'])

    def test_workflow_specific_history(self):
        job, step = {'name': 'build'}, {'name': 'compile'}
        self.assertNotEqual(core.history_key('a/b', job, step, 'Web'),
                            core.history_key('a/b', job, step, 'Switch'))

    def test_disabling_activity_clears_active_tags(self):
        repo = 'Touchy28/more-tents'
        state = {'activities': {repo: {'42': {'percent': 23}}}}
        config = {'live_activity_enabled': False,
                  'live_activity_notify_service': 'notify.mobile_app_test'}
        with mock.patch.object(monitor, 'runs_for', return_value=[]), \
             mock.patch.object(monitor, 'api_call') as post:
            monitor.monitor_repository(repo, '', 'fake', config, state, {}, 100.0)
        self.assertEqual(state['activities'][repo], {})
        sent = [call.kwargs.get('data') for call in post.call_args_list]
        self.assertTrue(any(v and v.get('message') == 'clear_notification' for v in sent))

    def test_unmeasured_step_does_not_fake_time_progress(self):
        run = {'status': 'in_progress', 'name': 'Build', 'id': 10}
        job = {'name': 'build', 'status': 'in_progress', 'steps': [
            {'name': 'compile', 'status': 'in_progress',
             'started_at': '2026-10-12T00:00:00Z'}]}
        now = core.timestamp('2026-10-12T00:05:00Z')
        data = core.snapshot('Touchy28/more-tents', run, [job], {}, now=now)
        self.assertEqual(data['progress_percent'], 0)
        self.assertIsNone(data['estimated_remaining_seconds'])

    def test_legacy_live_tag_cleanup_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            olddir = root / 'github-build-monitor-state'
            olddir.mkdir()
            (olddir / 'notifications-v1.json').write_text(
                json.dumps({'Touchy28/more-tents': {'active': True, 'run_id': '42'}}))
            state = {}
            with mock.patch.object(monitor, 'notify') as send:
                monitor.clear_legacy_notifications(
                    root, state, 'notify.mobile_app_test', 'test-token')
                self.assertEqual(send.call_count, 1)
                self.assertEqual(send.call_args.args[2]['message'], 'clear_notification')
                self.assertTrue(send.call_args.args[2]['data']['tag'].startswith('ghrunner_'))
                monitor.clear_legacy_notifications(
                    root, state, 'notify.mobile_app_test', 'test-token')
                self.assertEqual(send.call_count, 1)


if __name__ == '__main__':
    unittest.main()
