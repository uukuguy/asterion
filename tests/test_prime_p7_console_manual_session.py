"""Application integration keeps human play independent from P7 runs."""

from copy import deepcopy
import threading

from asterion.applications.prime.p7.console_session import ConsoleSessionError
from tests.test_prime_p7_console_session import ConsoleSessionFixture


class FakeManualController:
    def __init__(self):
        self.calls = []
        self.current = {'session_id': None, 'game_id': None, 'state': 'idle',
                        'observation_version': 0, 'episode_id': 0, 'action_count': 0,
                        'snapshot': None, 'last_action': None}

    def view(self):
        return deepcopy(self.current)

    def open(self, game_id, win_levels, command_id):
        self.calls.append(('open', game_id, win_levels, command_id))
        self.current.update(session_id='manual-1', game_id=game_id, state='ready',
                            observation_version=1, snapshot={'run': {'game_id': game_id}})
        return self.view()

    def act(self, session_id, command_id, observation_version, action, data):
        self.calls.append(('action', session_id, command_id, observation_version, action, data))
        self.current['observation_version'] += 1
        self.current['action_count'] += 1
        return self.view()

    def close(self, session_id=None, command_id=None):
        self.calls.append(('close', session_id, command_id))
        self.current['state'] = 'closed'
        return self.view()

    def shutdown(self):
        self.calls.append(('shutdown',))
        self.current['state'] = 'closed'


class TestPrimeP7ConsoleManualSession(ConsoleSessionFixture):
    def test_session_exposes_manual_without_loading_game(self):
        before = self.session().view()
        self.assertIn('manual', before)
        self.assertEqual(before['manual']['state'], 'idle')
        self.assertFalse(self.calls)

    def test_manual_open_action_and_close_do_not_start_model(self):
        manual = FakeManualController()
        session = self.session(manual_controller=manual)
        opened = session.manual_open('test-1', 'open')
        self.assertEqual(opened['state'], 'ready')
        self.assertEqual(manual.calls[0], ('open', 'test-1', 2, 'open'))
        session.manual_action('manual-1', 'action', 1, 'ACTION1', {})
        self.assertEqual(session.view()['manual']['action_count'], 1)
        self.assertEqual(session.view()['state'], 'idle')
        self.assertIsNone(session.view()['run_id'])
        self.assertIsNone(session.view()['snapshot'])
        session.manual_close('manual-1', 'close')
        self.assertEqual(session.view()['manual']['state'], 'closed')
        self.assertFalse(self.calls)

    def test_canonical_game_and_model_busy_guards_precede_manual_execution(self):
        manual = FakeManualController()
        session = self.session(manual_controller=manual)
        for game_id in ('test', '../.env', 'unknown-1', None):
            with self.subTest(game_id=game_id), self.assertRaisesRegex(ConsoleSessionError, '^game-unavailable$'):
                session.manual_open(game_id, 'open')
        self.assertEqual(manual.calls, [])
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        calls = deepcopy(manual.calls)
        with self.assertRaisesRegex(ConsoleSessionError, '^session-busy$'):
            session.manual_open('test-1', 'open')
        self.assertEqual(manual.calls, calls)

    def test_start_closes_manual_before_fresh_p7_and_duplicate_is_read_only(self):
        manual = FakeManualController()
        session = self.session(manual_controller=manual)
        session.manual_open('test-1', 'open')
        started = session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        self.assertEqual(manual.calls[-1], ('close', None, None))
        calls = deepcopy(manual.calls)
        self.assertEqual(session.start('test-1', 'start'), started)
        self.assertEqual(manual.calls, calls)
        self.assertEqual(session.view()['snapshot'], None)

    def test_inflight_manual_action_rejects_start_and_view_stays_responsive(self):
        loading, release = threading.Event(), threading.Event()
        manual = FakeManualController()
        original = manual.act
        def act(*args):
            loading.set()
            release.wait(2)
            return original(*args)
        manual.act = act
        session = self.session(manual_controller=manual)
        session.manual_open('test-1', 'open')
        thread = threading.Thread(target=lambda: session.manual_action('manual-1', 'action', 1, 'ACTION1', {}))
        thread.start()
        self.assertTrue(loading.wait(1))
        self.assertEqual(session.view()['state'], 'idle')
        with self.assertRaisesRegex(ConsoleSessionError, '^session-busy$'):
            session.start('test-1', 'start')
        with self.assertRaisesRegex(ConsoleSessionError, '^session-busy$'):
            session.manual_open('test-1', 'open2')
        release.set()
        thread.join(2)
        self.assertFalse(self.calls)

    def test_manual_failure_redacts_details_and_cleanup_failure_blocks_start(self):
        manual = FakeManualController()
        def fail(*args):
            raise RuntimeError('/private/secret-sentinel')
        manual.close = fail
        session = self.session(manual_controller=manual)
        with self.assertRaisesRegex(ConsoleSessionError, '^manual-unavailable$'):
            session.start('test-1', 'start')
        self.assertFalse(self.calls)
        session.close()
        self.assertEqual(manual.calls[-1], ('shutdown',))
        with self.assertRaisesRegex(ConsoleSessionError, '^session-busy$'):
            session.manual_open('test-1', 'open')

    def test_manual_shutdown_uncertainty_survives_model_cleanup(self):
        manual = FakeManualController()
        def fail():
            raise RuntimeError('private-secret')
        manual.shutdown = fail
        session = self.session(manual_controller=manual)
        session.start('test-1', 'start')
        self.assertTrue(self.launched.wait(1))
        session.close()
        self.assertEqual(session.view()['state'], 'cleanup-unconfirmed')
        self.assertFalse(session.view()['cleanup_confirmed'])
