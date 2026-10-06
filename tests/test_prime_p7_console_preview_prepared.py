from copy import deepcopy
import json
import os
import signal
from unittest.mock import patch

from asterion.applications.prime.p7.console_session import ConsoleSessionError
from tests.test_prime_p7_console_preview import GAME
from tests.test_prime_p7_console_session import ConsoleSessionFixture


class TestPreparedConsolePreview(ConsoleSessionFixture):
    def resources(self):
        self.root = self.root.resolve()
        resource = self.root / 'environment_files' / 'vc33' / 'test'
        resource.mkdir(parents=True)
        (resource / 'metadata.json').write_text(json.dumps(GAME))
        (resource / 'vc33.py').write_text('raise AssertionError("must not import game source")')
        return resource

    def worker(self, calls, change=None):
        class Worker:
            def __init__(worker, root, game_id, level):
                calls.append(('open', game_id, level))
                worker.level = level

            def observe(worker):
                if change:
                    change()
                return {'game_id': GAME['game_id'], 'win_levels': 2, 'levels_completed': 0,
                        'current_level': worker.level, 'state': 'NOT_FINISHED',
                        'available_actions': [1, 6], 'frame': [[9] * 64 for _ in range(64)]}

            def close(worker):
                calls.append(('close', worker.level))

            def step(worker, *_):
                raise AssertionError('initial preparation must not send actions')

            activate = step
        return Worker

    def prepared(self):
        from asterion.applications.prime.p7.console_preview_prepared import prepare_preview_catalog
        resource, calls = self.resources(), []
        result = prepare_preview_catalog(self.root, self.root, catalog=(GAME,), worker_factory=self.worker(calls))
        return resource, calls, result

    def test_batch_prepares_every_level_and_fresh_default_session_only_reads_ready_files(self):
        _, calls, result = self.prepared()
        self.assertEqual(result['ready'], 2)
        self.assertEqual(result['failed'], 0)
        self.assertEqual([row for row in calls if row[0] == 'open'],
                         [('open', GAME['game_id'], 1), ('open', GAME['game_id'], 2)])
        with patch('asterion.applications.prime.p7.console_manual._Worker.__init__',
                   side_effect=AssertionError('ready request started SDK worker')) as engine:
            session = self.session(catalog=(GAME,))
            for level in (1, 2):
                value = session.preview(GAME['game_id'], level)
                self.assertEqual(value['run']['status'], 'preview')
                self.assertEqual(value['run']['completed_level_count'], 0)
                self.assertEqual(value['run']['primitive_action_count'], 0)
                self.assertFalse(value['run']['replay_verified'])
                self.assertFalse(value['run']['sealed_trace'])
                bucket = value['levels'][0]
                self.assertEqual(bucket['level'], level)
                self.assertEqual(bucket['frames'][0]['levels_completed'], level - 1)
                self.assertEqual(bucket['actions'], [])
                self.assertEqual(bucket['decisions'], [])
                self.assertIsNone(bucket['receipt'])
                self.assertEqual(bucket['cognition'], {'scope': 'unavailable', 'updates': []})
                value['levels'][0]['frames'][0]['grid'][0][0] = 0
                self.assertEqual(session.preview(GAME['game_id'], level)['levels'][0]['frames'][0]['grid'][0][0], 9)
            engine.assert_not_called()
        self.assertFalse(self.calls)

    def test_request_missing_corrupt_or_source_changed_is_unavailable_without_lazy_engine(self):
        resource, _, _ = self.prepared()
        forbidden = patch('asterion.applications.prime.p7.console_manual._Worker.__init__',
                          side_effect=AssertionError('invalid request started SDK worker'))
        engine = forbidden.start()
        self.addCleanup(forbidden.stop)
        session = self.session(catalog=(GAME,))
        session.preview(GAME['game_id'], 1)
        directory = self.root / '.asterion-private' / 'prime-p7-live' / 'console-previews'
        path = directory / f"{GAME['game_id']}--1.json"
        valid = path.read_bytes()
        record = json.loads(valid)
        cases = [None, b'corrupt', {**record, 'sdk': {'arc-agi': 'wrong', 'arcengine': '0.9.3'}},
                 {**record, 'level': 2}, {**record, 'debug': '/private/sk-preview-secret'}]
        for changed in cases:
            with self.subTest(value=type(changed).__name__):
                if path.exists():
                    path.unlink()
                if changed is not None:
                    path.write_bytes(changed if type(changed) is bytes else json.dumps(changed).encode())
                with self.assertRaisesRegex(ConsoleSessionError, 'preview-unavailable'):
                    session.preview(GAME['game_id'], 1)
        path.write_bytes(valid)
        record['observation']['private'] = '/private/sk-preview-secret'
        from asterion.applications.prime.p7.console_manual_saves import digest
        record['observation_sha256'] = digest(record['observation'])
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ConsoleSessionError, 'preview-unavailable'):
            session.preview(GAME['game_id'], 1)
        path.unlink()
        os.mkfifo(path)
        def timed_out(*_):
            raise AssertionError('preview file-type rejection blocked')
        previous = signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(2)
        try:
            from asterion.applications.prime.p7.console_preview import ConsolePreviewError
            from asterion.applications.prime.p7.console_preview_prepared import read_prepared_preview
            with self.assertRaisesRegex(ConsolePreviewError, 'preview-unavailable'):
                read_prepared_preview(self.root, self.root, GAME, 1)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
            path.unlink()
        engine.assert_not_called()
        path.write_bytes(valid)
        (resource / 'vc33.py').write_text('changed source')
        with self.assertRaisesRegex(ConsoleSessionError, 'preview-unavailable'):
            session.preview(GAME['game_id'], 1)

    def test_batch_is_resumable_and_never_publishes_source_changed_during_observation(self):
        from asterion.applications.prime.p7.console_preview_prepared import prepare_preview_catalog
        resource, calls, _ = self.prepared()
        result = prepare_preview_catalog(self.root, self.root, catalog=(GAME,),
            worker_factory=lambda *_: self.fail('valid prepared level reconstructed'))
        self.assertEqual(result['ready'], 2)
        self.assertEqual(result['cached'], 2)
        (resource / 'vc33.py').write_text('first new version')
        calls = []
        def changing():
            code = resource / 'vc33.py'
            code.write_text(code.read_text() + ' changed again')
        result = prepare_preview_catalog(self.root, self.root, catalog=(GAME,),
            worker_factory=self.worker(calls, changing))
        self.assertEqual(result['failed'], 2)
        self.assertEqual([row for row in calls if row[0] == 'close'], [('close', 1), ('close', 2)])
        session = self.session(catalog=(GAME,))
        with self.assertRaisesRegex(ConsoleSessionError, 'preview-unavailable'):
            session.preview(GAME['game_id'], 2)

    def test_source_symlink_and_matching_hash_noninitial_observation_are_rejected(self):
        _, _, _ = self.prepared()
        from asterion.applications.prime.p7.console_manual_saves import digest
        directory = self.root / '.asterion-private' / 'prime-p7-live' / 'console-previews'
        path = directory / f"{GAME['game_id']}--1.json"
        original = json.loads(path.read_bytes())
        session = self.session(catalog=(GAME,))
        for field, value in (('levels_completed', 1), ('current_level', 2), ('state', 'WIN'),
                             ('frame', [[True]]), ('available_actions', [6, 1])):
            with self.subTest(field=field):
                record = deepcopy(original)
                record['observation'][field] = value
                record['observation_sha256'] = digest(record['observation'])
                path.write_text(json.dumps(record))
                with self.assertRaisesRegex(ConsoleSessionError, 'preview-unavailable'):
                    session.preview(GAME['game_id'], 1)
        path.unlink()
        path.symlink_to(directory / f"{GAME['game_id']}--2.json")
        with self.assertRaisesRegex(ConsoleSessionError, 'preview-unavailable'):
            session.preview(GAME['game_id'], 1)
