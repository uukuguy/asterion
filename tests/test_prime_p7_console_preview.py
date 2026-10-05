from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.console_preview import build_preview_snapshot, ConsolePreviewError
from tests.test_prime_p7_console_session import ConsoleSessionFixture


GAME = {'game_id': 'vc33-test', 'alias': 'vc33', 'win_levels': 2, 'baseline_actions': [7, 11]}


class TestConsolePreview(unittest.TestCase):
    def test_initial_projection_has_no_attempt_history_and_always_closes_worker(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                closed, calls = [], []
                class Worker:
                    def __init__(self, root, game_id, level):
                        calls.append((root, game_id, level))
                    def observe(self):
                        return {'game_id': 'wrong-test' if invalid else GAME['game_id'], 'win_levels': 2,
                                'levels_completed': 0, 'current_level': 1, 'state': 'NOT_FINISHED',
                                'available_actions': [1, 6], 'frame': [[[9] * 64 for _ in range(64)]]}
                    def close(self):
                        closed.append(True)
                    def step(self, *_):
                        raise AssertionError('preview must not send game actions')
                    activate = step
                if invalid:
                    with self.assertRaises(ConsolePreviewError):
                        build_preview_snapshot(Path(directory), GAME, worker_factory=Worker)
                else:
                    value = build_preview_snapshot(Path(directory), GAME, worker_factory=Worker)
                    self.assertEqual(value['run']['status'], 'preview')
                    self.assertIsNone(value['run']['run_id'])
                    self.assertEqual(value['run']['seed'], 0)
                    self.assertEqual(value['run']['primitive_action_count'], 0)
                    self.assertEqual(value['levels'][0]['actions'], [])
                    self.assertEqual(value['levels'][0]['decisions'], [])
                    self.assertEqual(value['levels'][0]['cognition']['scope'], 'unavailable')
                    self.assertEqual(len(value['levels'][0]['frames'][0]['grid']), 64)
                self.assertEqual(closed, [True])
                self.assertEqual(calls, [(Path(directory), GAME['game_id'], 1)])
                self.assertEqual(list(Path(directory).iterdir()), [])


class TestConsolePreviewSession(ConsoleSessionFixture):
    def test_preview_is_cached_copied_and_does_not_mutate_manual_or_start_solver(self):
        calls = []
        def reader(root, game):
            calls.append((root, deepcopy(game)))
            return {'run': {'game_id': game['game_id']}, 'levels': []}
        session = self.session(catalog=(GAME,), preview_reader=reader)
        before = session.view()
        first = session.preview(GAME['game_id'])
        first['run']['game_id'] = 'mutated'
        self.assertEqual(session.preview(GAME['game_id'])['run']['game_id'], GAME['game_id'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(session.view(), before)
        self.assertFalse(self.calls)
        self.assertIsNone(session._manual)
        with self.assertRaises(ValueError):
            session.preview('other-test')
        self.assertEqual(len(calls), 1)
