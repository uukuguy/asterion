from copy import deepcopy
from pathlib import Path
import threading
import unittest

from asterion.applications.prime.p7.console_manual import ManualConsole, ManualConsoleError, _observation


class Worker:
    def __init__(self, *_args):
        self.calls = []
        self.closed = False
        self.error = False
        self.observation = {'game_id': 'test-1', 'win_levels': 2, 'levels_completed': 0,
                            'state': 'NOT_FINISHED', 'available_actions': [1, 6],
                            'frame': [[[0, 1], [2, 3]]]}

    def observe(self):
        return deepcopy(self.observation)

    def step(self, action, data):
        self.calls.append((action, data))
        if self.error:
            raise RuntimeError('/private/SENTINELSECRET')
        return self.observe()

    def close(self):
        self.closed = True


class TestPrimeP7ConsoleManual(unittest.TestCase):
    def setUp(self):
        self.workers = []
        self.now = 0
        def factory(*args):
            worker = Worker(*args)
            self.workers.append(worker)
            return worker
        self.console = ManualConsole(Path('/tmp'), worker_factory=factory, clock=lambda: self.now)
        self.addCleanup(self.console.shutdown)
        self.initial = self.console.open('test-1', 2, 'open')
        self.session = self.initial['session_id']

    def act(self, command='act', version=0, action='ACTION1', data=None):
        return self.console.act(self.session, command, version, action, {} if data is None else data)

    def test_actions_are_independent_immutable_and_idempotent(self):
        first = self.act()
        self.assertEqual(first['observation_version'], 1)
        self.assertEqual(first['snapshot']['run']['status'], 'manual')
        self.assertEqual(first['snapshot']['decisions'], [])
        self.assertEqual(first['snapshot']['levels'][0]['cognition']['scope'], 'unavailable')
        first['snapshot']['levels'][0]['frames'][0]['grid'][0][0] = 9
        self.assertNotEqual(self.act()['snapshot']['levels'][0]['frames'][0]['grid'][0][0], 9)
        self.assertEqual(len(self.workers[0].calls), 1)
        with self.assertRaisesRegex(ManualConsoleError, '^command-conflict$'):
            self.act(action='RESET')
        with self.assertRaisesRegex(ManualConsoleError, '^observation-stale$'):
            self.act(command='second')

    def test_validation_rejects_stale_session_illegal_action_and_coordinates(self):
        for action, data in [('ACTION2', {}), ('ACTION6', {}), ('ACTION6', {'x': True, 'y': 1}),
                             ('ACTION6', {'x': 2, 'y': 1}), ('ACTION1', {'x': 0, 'y': 0})]:
            with self.subTest(action=action, data=data), self.assertRaises(ManualConsoleError):
                self.act(action=action, data=data)
        with self.assertRaisesRegex(ManualConsoleError, '^session-mismatch$'):
            self.console.act('old', 'old', 0, 'ACTION1', {})
        self.assertEqual(self.workers[0].calls, [])
        self.act(action='ACTION6', data={'x': 1, 'y': 1})

    def test_reset_preserves_authoritative_completed_levels(self):
        self.workers[0].observation['levels_completed'] = 1
        value = self.act(action='RESET')
        self.assertEqual(value['episode_id'], 2)
        self.assertEqual(value['snapshot']['run']['completed_level_count'], 1)
        self.assertEqual(value['snapshot']['levels'][0]['level'], 2)

    def test_engine_uncertainty_locks_session_without_retries(self):
        self.workers[0].error = True
        with self.assertRaisesRegex(ManualConsoleError, '^manual-uncertain$'):
            self.act()
        self.assertEqual(self.console.view()['state'], 'uncertain')
        self.assertTrue(self.workers[0].closed)
        with self.assertRaises(ManualConsoleError):
            self.act(command='again')
        self.assertEqual(len(self.workers[0].calls), 1)
        self.assertNotIn('SENTINELSECRET', str(self.console.view()))

    def test_busy_action_rejects_instead_of_queuing(self):
        entered, release = threading.Event(), threading.Event()
        original = self.workers[0].step
        def step(*args):
            entered.set()
            release.wait(2)
            return original(*args)
        self.workers[0].step = step
        thread = threading.Thread(target=self.act)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaisesRegex(ManualConsoleError, '^session-busy$'):
                self.act(command='queued')
        finally:
            release.set()
            thread.join(2)
        self.assertEqual(len(self.workers[0].calls), 1)

    def test_idle_expiration_and_switch_cleanup(self):
        self.now = 301
        self.console.reap_idle()
        self.assertEqual(self.console.view()['state'], 'expired')
        self.assertTrue(self.workers[0].closed)
        self.console.open('test-1', 2, 'new')
        self.console.close()
        self.assertTrue(self.workers[1].closed)
        self.assertEqual(self.console.view()['state'], 'closed')

    def test_unclean_worker_blocks_replacement(self):
        original = self.workers[0].close
        def fail():
            raise RuntimeError('/private/SENTINELSECRET')
        self.workers[0].close = fail
        try:
            with self.assertRaisesRegex(ManualConsoleError, '^manual-cleanup-unconfirmed$'):
                self.console.open('test-1', 2, 'next')
            self.assertEqual(len(self.workers), 1)
            self.assertEqual(self.console.view()['state'], 'uncertain')
        finally:
            self.workers[0].close = original

    def test_multiframe_sdk_animation_and_private_fields(self):
        observation = self.workers[0].observe()
        observation['frame'] = [[[0, 1], [2, 3]]] * 63 + [[[4, 5], [6, 7]]]
        self.assertEqual(_observation(observation, 'test-1', 2)['frame'], [[4, 5], [6, 7]])
        for change in ({'frame': observation['frame'] * 2}, {'secret': 'SENTINELSECRET'},
                       {'state': 'SENTINELSECRET'}, {'win_levels': True}):
            with self.subTest(change=tuple(change)), self.assertRaisesRegex(ManualConsoleError, '^manual-unavailable$'):
                _observation({**observation, **change}, 'test-1', 2)

    def test_total_deadline_and_action_cap_do_not_extend_on_activity(self):
        self.now = 1799
        self.console._last_action = 1798
        self.act()
        self.now = 1800
        with self.assertRaisesRegex(ManualConsoleError, '^manual-expired$'):
            self.act(command='late', version=1)
        self.assertTrue(self.workers[0].closed)
        self.console.open('test-1', 2, 'restart')
        self.session = self.console.view()['session_id']
        self.console._view['action_count'] = 1000
        with self.assertRaisesRegex(ManualConsoleError, '^manual-expired$'):
            self.act(command='over-cap')


if __name__ == '__main__':
    unittest.main()
