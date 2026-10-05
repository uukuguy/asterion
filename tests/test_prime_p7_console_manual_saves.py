"""Private HUMAN recovery replays genuine actions, never P7 evidence."""
from contextlib import ExitStack
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.console_manual import ManualConsole, ManualConsoleError


class ReplayWorker:
    def __init__(self, root, game, level):
        self.closed = False
        self.calls = []
        self.position = 0
        self.value = {'game_id': game, 'win_levels': 3, 'levels_completed': 0,
                      'current_level': level, 'state': 'NOT_FINISHED',
                      'available_actions': [1, 2], 'frame': [[level, 0]]}

    def observe(self):
        return deepcopy(self.value)

    def step(self, action, data):
        self.calls.append((action, deepcopy(data)))
        if action == 'RESET':
            self.position = 0
        else:
            self.position += 1
        if action == 'ACTION2':
            self.value['current_level'] += 1
            self.value['levels_completed'] += 1
            self.position = 0
        self.value['frame'] = [[self.value['current_level'], self.position % 16]]
        return self.observe()

    def close(self):
        self.closed = True


class TestPrimeP7ConsoleManualSaves(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve() / 'saves'
        self.arc_root = Path(self.directory.name).resolve() / 'arc'
        game = self.arc_root / 'environment_files' / 'test' / '1'
        game.mkdir(parents=True)
        (game / 'metadata.json').write_text('{}')
        (game / 'test.py').write_text('# fixture game identity')
        self.workers = []

    def console(self):
        def factory(*args):
            worker = ReplayWorker(*args)
            self.workers.append(worker)
            return worker
        console = ManualConsole(self.arc_root, worker_factory=factory, save_root=self.root)
        self.addCleanup(console.shutdown)
        return console

    def action(self, console, command, action='ACTION1'):
        view = console.view()
        return console.act(view['session_id'], command, view['observation_version'], action, {})

    def test_switch_and_restart_restore_actual_pose_history_and_new_identity(self):
        console = self.console()
        first = console.open('test-1', 3, 'open')
        ack = self.action(console, 'move')
        self.assertNotIn('history', ack)
        console.open('test-1', 3, 'other', 3)
        resumed = console.open('test-1', 3, 'return')
        self.assertTrue(resumed['restored'])
        self.assertEqual(resumed['save_status'], 'saved')
        self.assertEqual(resumed['saved_levels'], [1, 3])
        self.assertNotEqual(first['session_id'], resumed['session_id'])
        self.assertEqual(resumed['snapshot']['levels'][0]['frames'][0]['grid'], [[1, 1]])
        self.assertEqual(len(resumed['history']), 2)
        self.assertEqual(resumed['history'][1]['last_action']['action'], 'ACTION1')
        console.shutdown()
        restarted = self.console().open('test-1', 3, 'restart')
        self.assertEqual(restarted['history'], resumed['history'])
        self.assertEqual(self.workers[-1].calls, [('ACTION1', {})])

    def restart(self, console, command='restart'):
        self.assertTrue(callable(getattr(console, 'restart', None)), 'restart must be implemented')
        view = console.view()
        return console.restart(view['session_id'], command, view['observation_version'])

    def test_restart_clears_only_actual_current_slot_and_preserves_origin_prefix(self):
        console = self.console()
        console.open('test-1', 3, 'third', 3)
        self.action(console, 'third-move')
        console.open('test-1', 3, 'one')
        self.action(console, 'one-move')
        prefix = (self.root / 'test-1--1.json').read_bytes()
        third = (self.root / 'test-1--3.json').read_bytes()
        self.action(console, 'advance', 'ACTION2')
        self.action(console, 'two-move')
        before = console.view()
        restarted = self.restart(console)
        self.assertNotEqual(restarted['session_id'], before['session_id'])
        self.assertEqual((restarted['level'], restarted['action_count'], restarted['observation_version'],
                          restarted['episode_id']), (2, 0, 0, 1))
        self.assertEqual(restarted['snapshot']['run']['completed_level_count'], 0)
        self.assertEqual(restarted['snapshot']['levels'][0]['frames'][0]['grid'], [[2, 0]])
        self.assertEqual(len(restarted['history']), 1)
        self.assertIsNone(restarted['last_action'])
        self.assertFalse(restarted['restored'])
        self.assertEqual(restarted['save_status'], 'saved')
        self.assertEqual((self.root / 'test-1--1.json').read_bytes(), prefix)
        self.assertEqual((self.root / 'test-1--3.json').read_bytes(), third)
        record = json.loads((self.root / 'test-1--2.json').read_text())
        self.assertEqual(record['origin_level'], 2)
        self.assertEqual(record['steps'], [])
        self.assertTrue(all(worker.closed for worker in self.workers[:-1]))
        self.assertFalse(self.workers[-1].closed)
        console.shutdown()
        recovered = self.console().open('test-1', 3, 'recover', 2)
        self.assertEqual(recovered['history'], restarted['history'])

    def test_restart_duplicate_is_read_only_and_stale_requests_fail_before_cleanup(self):
        console = self.console()
        console.open('test-1', 3, 'one')
        self.action(console, 'move')
        before = console.view()
        restarted = self.restart(console)
        self.action(console, 'after')
        current = console.view()
        self.assertEqual(console.restart(before['session_id'], 'restart', before['observation_version']), restarted)
        self.assertEqual(console.view(), current)
        for session_id, version, code in ((before['session_id'], 1, 'session-mismatch'),
                                          (current['session_id'], 0, 'observation-stale')):
            with self.subTest(code=code), self.assertRaisesRegex(ManualConsoleError, '^' + code + '$'):
                console.restart(session_id, 'stale-' + code, version)
        self.assertEqual(len(self.workers), 2)
        self.assertFalse(self.workers[-1].closed)

    def test_restart_startup_failure_retains_durable_history_and_is_recoverable(self):
        console = self.console()
        console.open('test-1', 3, 'one')
        self.action(console, 'move')
        before = console.view()
        durable = (self.root / 'test-1--1.json').read_bytes()
        factory = console._factory
        def wrong(*args):
            worker = factory(*args)
            worker.value['levels_completed'] = 1
            return worker
        console._factory = wrong
        with self.assertRaisesRegex(ManualConsoleError, '^manual-unavailable$'):
            self.restart(console)
        self.assertEqual((self.root / 'test-1--1.json').read_bytes(), durable)
        self.assertEqual(console.view()['session_id'], before['session_id'])
        self.assertEqual(console.view()['history'], before['history'])
        self.assertEqual(console.view()['state'], 'uncertain')
        self.assertTrue(all(worker.closed for worker in self.workers))
        console._factory = factory
        self.assertEqual(self.restart(console)['action_count'], 0)

    def test_restart_save_failure_retains_prior_slot_and_does_not_publish_new_session(self):
        for failure in ('replace', 'directory-fsync'):
            with self.subTest(failure=failure):
                console = self.console()
                console.open('test-1', 3, 'one')
                self.action(console, 'move')
                before = console.view()
                durable = (self.root / 'test-1--1.json').read_bytes()
                target = 'os.replace' if failure == 'replace' else 'os.fsync'
                effect = OSError('/private/SENTINELSECRET') if failure == 'replace' else [None, OSError('secret')]
                with patch(target, side_effect=effect):
                    with self.assertRaisesRegex(ManualConsoleError, '^manual-save-failed$'):
                        self.restart(console)
                self.assertEqual((self.root / 'test-1--1.json').read_bytes(), durable)
                self.assertEqual(console.view()['session_id'], before['session_id'])
                self.assertEqual(console.view()['history'], before['history'])
                self.assertEqual(console.view()['state'], 'uncertain')
                self.assertIsNone(console._worker)
                self.assertNotIn('SENTINELSECRET', str(console.view()))
                self.assertEqual(self.restart(console)['save_status'], 'saved')
                console.shutdown()

    def test_restart_explicitly_discards_unsaved_pose_and_handles_win(self):
        console = self.console()
        console.open('test-1', 3, 'one')
        with patch('os.replace', side_effect=OSError('secret')):
            self.assertEqual(self.action(console, 'unsaved')['save_status'], 'failed')
        self.assertEqual(self.restart(console)['action_count'], 0)
        self.workers[-1].value.update(state='WIN', levels_completed=3)
        self.action(console, 'win')
        won = console.view()
        self.assertEqual(won['snapshot']['levels'][0]['frames'][0]['available_actions'], [])
        restarted = self.restart(console, 'restart-win')
        self.assertEqual(restarted['snapshot']['run']['completed_level_count'], 0)
        self.assertEqual(restarted['history'][0]['frame']['state'], 'NOT_FINISHED')

    def test_advance_keeps_origin_prefix_and_previous_playable_pose_and_reset_score(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        self.action(console, 'move')
        self.action(console, 'advance', 'ACTION2')
        self.action(console, 'reset', 'RESET')
        restored = console.open('test-1', 3, 'return-two', 2)
        self.assertEqual(restored['snapshot']['run']['completed_level_count'], 1)
        self.assertEqual(restored['episode_id'], 2)
        self.assertEqual(self.workers[-1].calls, [('ACTION1', {}), ('ACTION2', {}), ('RESET', {})])
        previous = console.open('test-1', 3, 'return-one', 1)
        self.assertEqual(previous['snapshot']['levels'][0]['frames'][0]['grid'], [[1, 1]])
        self.assertEqual(previous['snapshot']['run']['completed_level_count'], 0)

    def test_disk_failure_keeps_only_unsaved_worker_and_retries_same_ack(self):
        console = self.console()
        opened = console.open('test-1', 3, 'open')
        with patch('os.replace', side_effect=OSError('/private/SENTINELSECRET')):
            ack = self.action(console, 'move')
            self.assertEqual(ack['save_status'], 'failed')
            with self.assertRaisesRegex(ManualConsoleError, '^manual-save-failed$'):
                console.open('test-1', 3, 'switch', 2)
            self.assertFalse(self.workers[0].closed)
            self.assertEqual(len(self.workers), 1)
        retry = console.act(opened['session_id'], 'move', 0, 'ACTION1', {})
        self.assertEqual(retry['save_status'], 'saved')
        self.assertEqual(retry['last_action'], ack['last_action'])
        self.assertEqual(len(self.workers[0].calls), 1)
        resumed = console.open('test-1', 3, 'switch', 2)
        self.assertEqual(resumed['save_status'], 'saved')
        self.assertNotIn('SENTINELSECRET', str(console.view()))

    def test_divergent_or_incompatible_records_fail_without_overwrite(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        self.action(console, 'move')
        console.close()
        path = next(self.root.glob('*.json'))
        original = path.read_text()
        record = json.loads(original)
        record['sdk']['arcengine'] = '99'
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ManualConsoleError, '^manual-save-invalid$'):
            console.open('test-1', 3, 'incompatible')
        self.assertEqual(json.loads(path.read_text()), record)
        path.write_text(original)
        real_factory = console._factory
        def divergent(*args):
            worker = real_factory(*args)
            worker.value['frame'] = [[9, 9]]
            return worker
        console._factory = divergent
        with self.assertRaisesRegex(ManualConsoleError, '^manual-restore-failed$'):
            console.open('test-1', 3, 'divergent')
        self.assertEqual(path.read_text(), original)
        self.assertTrue(self.workers[-1].closed)

    def test_automatic_entry_preserves_existing_level_until_explicit_new_action(self):
        console = self.console()
        console.open('test-1', 3, 'two', 2)
        self.action(console, 'two-move')
        path = self.root / 'test-1--2.json'
        original = path.read_text()
        console.open('test-1', 3, 'one')
        advanced = self.action(console, 'advance', 'ACTION2')
        self.assertEqual(advanced['save_status'], 'pending')
        self.assertEqual(path.read_text(), original)
        resumed = console.open('test-1', 3, 'back-two', 2)
        self.assertEqual(resumed['snapshot']['levels'][0]['frames'][0]['grid'], [[2, 1]])
        console.open('test-1', 3, 'back-one')
        self.action(console, 'advance-again', 'ACTION2')
        self.action(console, 'new-two', 'RESET')
        resumed = console.open('test-1', 3, 'back-two-again', 2)
        self.assertEqual(resumed['snapshot']['run']['completed_level_count'], 1)
        self.assertEqual(resumed['episode_id'], 2)
        self.assertEqual(resumed['save_status'], 'saved')

    def test_source_drift_and_symlink_storage_reject_before_closing_live_worker(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        self.action(console, 'move')
        (self.arc_root / 'environment_files/test/1/test.py').write_text('# changed')
        with self.assertRaisesRegex(ManualConsoleError, '^manual-save-invalid$'):
            console.open('test-1', 3, 'source-drift')
        self.assertFalse(self.workers[-1].closed)
        actual = self.root.with_name('actual-saves')
        self.root.rename(actual)
        self.root.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(ManualConsoleError, '^manual-save-invalid$'):
            console.open('test-1', 3, 'symlink')
        self.assertFalse(self.workers[-1].closed)

    def test_history_and_journal_limits_are_bounded_and_preserve_saved_prefix(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        with patch('asterion.applications.prime.p7.console_manual._ACTION_CAP', 2000):
            for index in range(1002):
                self.action(console, 'move-' + str(index))
        view = console.view()
        self.assertEqual(len(view['history']), 1001)
        self.assertEqual(view['history'][0]['observation_version'], 2)
        self.assertEqual(view['history'][-1]['observation_version'], 1002)
        self.assertNotIn('history', console._commands['move-1001'][1])
        self.assertEqual(len(json.loads(next(self.root.glob('*.json')).read_text())['steps']), 1002)
        with patch('asterion.applications.prime.p7.console_manual.MAX_STEPS', 1002), \
                patch('asterion.applications.prime.p7.console_manual._ACTION_CAP', 2000):
            with self.assertRaisesRegex(ManualConsoleError, '^manual-save-limit$'):
                self.action(console, 'over-limit')
        self.assertEqual(len(self.workers[-1].calls), 1002)

    def test_journal_capacity_rejects_before_sdk_action(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        size = next(self.root.glob('*.json')).stat().st_size
        with patch('asterion.applications.prime.p7.console_manual_saves.MAX_BYTES', size + 1):
            with self.assertRaisesRegex(ManualConsoleError, '^manual-save-limit$'):
                self.action(console, 'too-large')
        self.assertEqual(self.workers[0].calls, [])
        self.assertEqual(console.view()['observation_version'], 0)

    def test_poll_does_not_publish_settled_pose_as_saved_before_atomic_commit(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        import os
        replace = os.replace
        def blocked(*args):
            entered.set()
            release.wait(2)
            return replace(*args)
        polled = []
        def poll():
            polled.append(console.view())
            returned.set()
        with patch('os.replace', side_effect=blocked):
            action = threading.Thread(target=lambda: self.action(console, 'move'))
            action.start()
            self.assertTrue(entered.wait(1))
            reader = threading.Thread(target=poll)
            reader.start()
            try:
                self.assertFalse(returned.wait(0.05))
            finally:
                release.set()
                action.join(2)
                reader.join(2)
        self.assertEqual(polled[0]['save_status'], 'saved')
        self.assertEqual(polled[0]['observation_version'], 1)

    def test_initial_save_failure_can_retry_open_without_replacing_worker(self):
        console = self.console()
        with patch('os.replace', side_effect=OSError('private-secret')):
            opened = console.open('test-1', 3, 'open')
        self.assertEqual(opened['save_status'], 'failed')
        retried = console.open('test-1', 3, 'open')
        self.assertEqual(retried['save_status'], 'saved')
        self.assertEqual(retried['session_id'], opened['session_id'])
        self.assertEqual(len(self.workers), 1)
        self.assertEqual(self.workers[0].calls, [])

    def test_worker_replay_phase_does_not_spend_child_live_cap_and_resets_timer(self):
        from asterion.applications.prime.p7 import console_manual as module
        worker = ReplayWorker(None, 'test-1', 1)
        engine = SimpleNamespace(close=lambda: None)
        game = SimpleNamespace(game_id='test-1', win_levels=3)
        commands = [{'action': 'ACTION1', 'data': {}, 'replay': True}] * 2 + [
            {'activate': True}] + [{'action': 'ACTION1', 'data': {}}] * 2
        stdin = SimpleNamespace(buffer=io.BytesIO(b''.join(
            json.dumps(command).encode() + b'\n' for command in commands)))
        outputs = []
        class Output(io.BytesIO):
            def close(self):
                if not getattr(self, 'recorded', False):
                    outputs.append(json.loads(self.getvalue()))
                    self.recorded = True
        with ExitStack() as stack:
            for target, value in (
                ('sys.argv', ['manual', '--arc-root', '/tmp', '--game-id', 'test-1', '--recordings', '/tmp']),
                ('sys.stdin', stdin),
            ):
                stack.enter_context(patch(target, value))
            stack.enter_context(patch.object(module, '_ACTION_CAP', 2))
            timers = stack.enter_context(patch.object(module.signal, 'setitimer'))
            stack.enter_context(patch.object(module.os, 'dup', return_value=99))
            stack.enter_context(patch.object(module.os, 'dup2'))
            stack.enter_context(patch.object(module.os, 'close'))
            stack.enter_context(patch.object(module.os, 'fdopen', side_effect=lambda *args: Output()))
            stack.enter_context(patch.object(module.select, 'select', return_value=([stdin], [], [])))
            stack.enter_context(patch.object(module, '_ManualEngine', return_value=worker))
            stack.enter_context(patch('asterion.applications.prime.p7.game.resolve_game_selection', return_value=game))
            stack.enter_context(patch('asterion.applications.prime.p7.live.ArcadeEngine', return_value=engine))
            self.assertEqual(module.main(), 0)
        self.assertEqual(len(worker.calls), 4)
        self.assertEqual(len(outputs), 6)
        self.assertEqual([call.args[1] for call in timers.call_args_list], [60, 1800])

    def test_replay_does_not_spend_activation_action_budget(self):
        console = self.console()
        console.open('test-1', 3, 'open')
        for index in range(3):
            self.action(console, 'move-' + str(index))
        with patch('asterion.applications.prime.p7.console_manual._ACTION_CAP', 2):
            restored = console.open('test-1', 3, 'return')
            self.assertEqual(restored['action_count'], 3)
            self.action(console, 'fresh-1')
            self.action(console, 'fresh-2')
            with self.assertRaisesRegex(ManualConsoleError, '^manual-expired$'):
                self.action(console, 'fresh-3')
