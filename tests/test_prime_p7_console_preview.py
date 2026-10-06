from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.console_preview import build_preview_snapshot, ConsolePreviewError
from tests.test_prime_p7_console_session import ConsoleSessionFixture


GAME = {'game_id': 'vc33-test', 'alias': 'vc33', 'win_levels': 2, 'baseline_actions': [7, 11]}


class TestConsolePreview(unittest.TestCase):
    def test_preview_projects_real_readonly_animation_handle_to_last_frame(self):
        from asterion.applications.prime.p7.dynamic_evidence import AnimationFrames
        handle = AnimationFrames.capture(([[i % 10]] for i in range(95)))
        class Worker:
            def __init__(self, *args): pass
            def observe(self):
                return dict(game_id=GAME['game_id'], win_levels=2, levels_completed=0,
                            current_level=1, state='NOT_FINISHED', available_actions=[1], frame=handle)
            def close(self): pass
        snapshot = build_preview_snapshot(Path('/tmp'), GAME, worker_factory=Worker)
        self.assertEqual(snapshot['levels'][0]['frames'][0]['grid'], [[4]])
        self.assertEqual(len(handle), 95)

    def test_initial_projection_has_no_attempt_history_and_always_closes_worker(self):
        for selected, invalid in ((1, None), (2, None), (2, 'identity'), (2, 'level'), (2, 'progress')):
            with self.subTest(level=selected, invalid=invalid), tempfile.TemporaryDirectory() as directory:
                closed, calls = [], []
                class Worker:
                    def __init__(self, root, game_id, level):
                        calls.append((root, game_id, level))
                    def observe(self):
                        return {'game_id': 'wrong-test' if invalid == 'identity' else GAME['game_id'], 'win_levels': 2,
                                'levels_completed': 1 if invalid == 'progress' else 0,
                                'current_level': 1 if invalid == 'level' else selected, 'state': 'NOT_FINISHED',
                                'available_actions': [1, 6], 'frame': [[[9] * 64 for _ in range(64)]]}
                    def close(self):
                        closed.append(True)
                    def step(self, *_):
                        raise AssertionError('preview must not send game actions')
                    activate = step
                if invalid:
                    with self.assertRaises(ConsolePreviewError):
                        build_preview_snapshot(Path(directory), GAME, selected, worker_factory=Worker)
                else:
                    value = build_preview_snapshot(Path(directory), GAME, selected, worker_factory=Worker)
                    self.assertEqual(value['run']['status'], 'preview')
                    self.assertIsNone(value['run']['run_id'])
                    self.assertEqual(value['run']['seed'], 0)
                    self.assertEqual(value['run']['primitive_action_count'], 0)
                    self.assertEqual(value['run']['completed_level_count'], 0)
                    self.assertEqual(value['run']['target_level'], selected)
                    self.assertEqual(value['levels'][0]['level'], selected)
                    self.assertEqual(value['levels'][0]['frames'][0]['levels_completed'], selected - 1)
                    self.assertEqual(value['levels'][0]['actions'], [])
                    self.assertEqual(value['levels'][0]['decisions'], [])
                    self.assertEqual(value['levels'][0]['cognition']['scope'], 'unavailable')
                    self.assertEqual(len(value['levels'][0]['frames'][0]['grid']), 64)
                self.assertEqual(closed, [True])
                self.assertEqual(calls, [(Path(directory), GAME['game_id'], selected)])
                self.assertEqual(list(Path(directory).iterdir()), [])


class TestConsolePreviewSession(ConsoleSessionFixture):
    def test_preview_is_cached_copied_and_does_not_mutate_manual_or_start_solver(self):
        calls = []
        def reader(root, game, level):
            calls.append((root, deepcopy(game), level))
            return {'run': {'game_id': game['game_id']}, 'levels': []}
        session = self.session(catalog=(GAME,), preview_reader=reader)
        before = session.view()
        first = session.preview(GAME['game_id'])
        first['run']['game_id'] = 'mutated'
        self.assertEqual(session.preview(GAME['game_id'])['run']['game_id'], GAME['game_id'])
        self.assertEqual(len(calls), 1)
        session.preview(GAME['game_id'], 2)
        session.preview(GAME['game_id'], 2)
        self.assertEqual([call[2] for call in calls], [1, 2])
        self.assertEqual(session.view(), before)
        self.assertFalse(self.calls)
        self.assertIsNone(session._manual)
        with self.assertRaises(ValueError):
            session.preview('other-test')
        for level in (0, 3, True, '2'):
            with self.subTest(level=level), self.assertRaises(ValueError):
                session.preview(GAME['game_id'], level)
        self.assertEqual(len(calls), 2)
