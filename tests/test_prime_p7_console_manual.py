from copy import deepcopy
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.console_manual import ManualConsole, ManualConsoleError, _ManualEngine, _observation


class Worker:
    def __init__(self, _root=None, _game_id=None, level=1):
        self.calls = []
        self.closed = False
        self.error = False
        self.observation = {'game_id': 'test-1', 'win_levels': 2, 'levels_completed': 0, 'current_level': level,
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
        self.workers[0].observation['current_level'] = 2
        value = self.act(action='RESET')
        self.assertEqual(value['episode_id'], 2)
        self.assertEqual(value['snapshot']['run']['completed_level_count'], 1)
        self.assertEqual(value['snapshot']['levels'][0]['level'], 2)

    def test_restart_refuses_overlap_cleanup_failure_and_invalid_requests(self):
        before = self.console.view()
        for version in (True, -1, '0', None):
            with self.subTest(version=version), self.assertRaisesRegex(ManualConsoleError, '^action-invalid$'):
                self.console.restart(self.session, 'invalid', version)
        with self.console._gate:
            with self.assertRaisesRegex(ManualConsoleError, '^session-busy$'):
                self.console.restart(self.session, 'busy', 0)
        worker = self.workers[0]
        with patch.object(worker, 'close', side_effect=RuntimeError('SENTINELSECRET')):
            with self.assertRaisesRegex(ManualConsoleError, '^manual-cleanup-unconfirmed$'):
                self.console.restart(self.session, 'restart', 0)
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(self.console.view()['history'], before['history'])
        original = self.console._factory
        def factory(*args):
            self.assertTrue(worker.closed, 'old worker must close before starting replacement')
            return original(*args)
        self.console._factory = factory
        restarted = self.console.restart(self.session, 'restart', 0)
        self.assertEqual(restarted['save_status'], 'disabled')
        self.assertEqual(restarted['action_count'], 0)

    def test_direct_level_starts_with_zero_score_and_tracks_real_level(self):
        opened = self.console.open('test-1', 2, 'level-two', 2)
        self.session = opened['session_id']
        self.assertEqual(opened['level'], 2)
        self.assertEqual(opened['snapshot']['levels'][0]['level'], 2)
        self.assertEqual(opened['snapshot']['run']['completed_level_count'], 0)
        reset = self.act(action='RESET')
        self.assertEqual(reset['level'], 2)
        self.assertEqual(reset['snapshot']['run']['completed_level_count'], 0)
        self.assertEqual(reset['last_action']['action'], 'RESET')
        self.workers[-1].observation.update(levels_completed=1, state='WIN')
        won = self.act(command='win', version=1)
        self.assertEqual(won['level'], 2)
        self.assertEqual(won['snapshot']['levels'][0]['level'], 2)
        self.assertEqual(won['snapshot']['run']['completed_level_count'], 1)
        self.assertEqual(won['snapshot']['decisions'], [])

    def test_level_bounds_and_command_identity_precede_worker_replacement(self):
        for level in (0, -1, 3, True, 1.5, '2', None):
            with self.subTest(level=level), self.assertRaisesRegex(ManualConsoleError, '^level-unavailable$'):
                self.console.open('test-1', 2, 'bad', level)
        with self.assertRaisesRegex(ManualConsoleError, '^command-conflict$'):
            self.console.open('test-1', 2, 'open', 2)
        self.assertEqual(len(self.workers), 1)
        self.assertFalse(self.workers[0].closed)

    def test_open_rejects_wrong_observed_level(self):
        worker = Worker(level=1)
        self.console._factory = lambda *_args: worker
        with self.assertRaisesRegex(ManualConsoleError, '^manual-unavailable$'):
            self.console.open('test-1', 2, 'wrong-level', 2)
        self.assertTrue(worker.closed)

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
                       {'state': 'SENTINELSECRET'}, {'win_levels': True},
                       {'current_level': 0}, {'current_level': 3}, {'current_level': True}):
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


class TestManualLevelAdapter(unittest.TestCase):
    def setUp(self):
        # This SDK-shaped fixture checks adapter routing, not game mechanics.
        # The real pinned SDK / SP80 smoke independently covers actual frames.
        class Game:
            level_index = 0
            def set_level(self, index):
                self.level_index = index
            def level_reset(self):
                self.reset_count += 1
            def __init__(self):
                self.reset_count = 0
                self.current_level = SimpleNamespace(get_sprites=lambda: [self.level_index])
                self.camera = SimpleNamespace(render=lambda sprites: SimpleNamespace(tolist=lambda: [sprites]))
        class Wrapper:
            def __init__(self):
                self._game = Game()
        self.wrapper = Wrapper()
        self.observation = {'win_levels': 6, 'levels_completed': 0, 'state': 'NOT_FINISHED',
                            'available_actions': [1], 'frame': [[0]]}
        self.calls = []
        def step(action, data):
            self.calls.append((action, data))
            self.wrapper._game.set_level(3)
            return {**self.observation, 'levels_completed': 1, 'frame': [[3]]}
        self.engine = SimpleNamespace(_environment=self.wrapper, game_id='test-1',
                                      observe=lambda: deepcopy(self.observation), step=step)
        self.addCleanup(patch.stopall)
        patch.dict('sys.modules', {'arc_agi.local_wrapper': SimpleNamespace(LocalEnvironmentWrapper=Wrapper),
                                  'arcengine': SimpleNamespace(ARCBaseGame=Game)}).start()
        self.version = patch('importlib.metadata.version', side_effect=lambda name:
                             {'arc-agi': '0.9.9', 'arcengine': '0.9.3'}[name]).start()

    def test_direct_level_render_reset_and_progression_keep_sdk_score(self):
        adapter = _ManualEngine(self.engine, 3)
        initial = adapter.observe()
        self.assertEqual((initial['current_level'], initial['levels_completed'], initial['frame']), (3, 0, [[2]]))
        self.assertEqual(adapter.step('RESET', {}), initial)
        self.assertEqual(self.wrapper._game.reset_count, 1)
        self.assertEqual(self.calls, [])
        advanced = adapter.step('ACTION1', {})
        self.assertEqual((advanced['current_level'], advanced['levels_completed']), (4, 1))
        self.assertEqual(adapter.step('RESET', {}), advanced)
        self.assertEqual(self.calls, [('ACTION1', {})])
        advanced['frame'][0][0] = 9
        self.assertEqual(adapter.observe()['frame'], [[3]])

    def test_unverified_sdk_and_wrong_wrapper_fail_closed(self):
        self.version.side_effect = lambda _name: '99.0.0'
        with self.assertRaisesRegex(ManualConsoleError, '^manual-unavailable$'):
            _ManualEngine(self.engine, 3)
        self.version.side_effect = lambda name: {'arc-agi': '0.9.9', 'arcengine': '0.9.3'}[name]
        self.engine._environment = SimpleNamespace(_game=self.wrapper._game)
        with self.assertRaisesRegex(ManualConsoleError, '^manual-unavailable$'):
            _ManualEngine(self.engine, 3)

    def test_game_over_reset_restores_play_without_altering_sdk_score(self):
        adapter = _ManualEngine(self.engine, 3)
        self.observation['state'] = 'GAME_OVER'
        ended = adapter.step('ACTION1', {})
        self.assertEqual(ended['state'], 'GAME_OVER')
        reset = adapter.step('RESET', {})
        self.assertEqual((reset['state'], reset['current_level'], reset['levels_completed']),
                         ('NOT_FINISHED', 4, 1))
        self.assertEqual(self.wrapper._game.reset_count, 1)


if __name__ == '__main__':
    unittest.main()
