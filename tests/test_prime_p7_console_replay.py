from __future__ import annotations

import json
from copy import deepcopy
import threading
import time
from unittest.mock import patch

from asterion.applications.prime.p7.console_session import ConsoleSessionError
from tests.test_prime_p7_console_session import ConsoleSessionFixture, RUN_ID


SOURCE_ID = 'p7-live-20261004123456-' + 'b' * 24


def projection(run_id=RUN_ID):
    return {
        'schema': 'asterion.arc-agi3-p7-console/v1', 'generated_at': 'fixed',
        'run': {'run_id': run_id, 'game_id': 'test-1', 'win_levels': 2, 'status': 'successful'},
        'levels': [
            {'level': 1, 'status': 'successful', 'frames': [{'id': 'f1', 'grid': [[1]]}],
             'actions': [], 'decisions': [{'id': 'prior', 'source': 'p7_decision'}],
             'cognition': {'scope': 'observation', 'stable_description': 'first'},
             'cognition_timeline': [], 'research_timeline': [], 'receipt': None},
            {'level': 2, 'status': 'successful', 'frames': [{'id': 'f2', 'grid': [[2]]}],
             'actions': [{'id': 'a1', 'decision_id': 'prior', 'before_frame': 'f1', 'after_frame': 'f2'}],
             'decisions': [], 'cognition': {'scope': 'observation', 'stable_description': 'second',
                                          'provenance': {'run_id': SOURCE_ID, 'event_sequence': 7}},
             'cognition_timeline': [], 'research_timeline': [], 'receipt': None}],
        'decisions': [{'id': 'prior', 'source': 'p7_decision'}, {'id': 'round', 'round_index': 1}],
        'process_events': [{'level': 1, 'frame_id': 'f2', 'kind': 'cognition'},
                           {'level': 2, 'frame_id': 'f1', 'kind': 'plan'},
                           {'level': 1, 'frame_id': 'f1', 'kind': 'plan'}], 'warnings': []}


class TestPrimeP7ConsoleReplay(ConsoleSessionFixture):
    def run_root(self, run_id=RUN_ID, **diagnostics):
        root = self.root / '.asterion-private' / 'prime-p7-live' / run_id
        root.mkdir(parents=True, exist_ok=True)
        (root / 'summary.json').write_text(json.dumps({'diagnostics': diagnostics}))
        return root

    def ready(self, session, run_id=RUN_ID):
        until = time.monotonic() + 2
        while time.monotonic() < until:
            value = session.replay_manifest(run_id)
            if value['state'] == 'ready':
                return value
            time.sleep(.005)
        self.fail('replay manifest did not become ready')

    def test_manifest_is_nonblocking_single_flight_and_details_preserve_references(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        self.run_root()
        source = projection()

        def read(_):
            calls.append(1)
            entered.set()
            release.wait(2)
            return source

        session = self.session(snapshot_reader=read)
        self.assertTrue(hasattr(session, 'replay_manifest'), 'progressive replay API is missing')
        self.addCleanup(release.set)
        loading = session.replay_manifest(RUN_ID)
        self.assertEqual(loading['state'], 'loading')
        self.assertIsNone(loading['run'])
        self.assertTrue(entered.wait(1))
        self.assertEqual(session.replay_manifest(RUN_ID), loading)
        self.assertEqual(session.view()['state'], 'idle')
        release.set()
        manifest = self.ready(session)
        self.assertEqual(len(calls), 1)
        self.assertEqual(manifest['levels'][1]['frame_count'], 1)
        self.assertNotIn('grid', json.dumps(manifest))
        self.assertNotIn('second', json.dumps(manifest))
        detail = session.replay_level(RUN_ID, 2, manifest['revision'])
        self.assertEqual(detail['levels'], source['levels'][1:])
        self.assertEqual(detail['decisions'], source['decisions'])
        self.assertEqual(detail['process_events'], source['process_events'][:2])
        self.assertEqual(detail['replay_revision'], manifest['revision'])
        detail['levels'][0]['frames'][0]['grid'][0][0] = 99
        manifest['run']['game_id'] = 'mutated'
        self.assertEqual(session.replay_level(RUN_ID, 2, manifest['revision'])['levels'][0]['frames'][0]['grid'], [[2]])
        self.assertEqual(session.replay_manifest(RUN_ID)['run']['game_id'], 'test-1')

    def test_explicit_source_and_absent_siblings_invalidate_but_unrelated_runs_do_not(self):
        self.run_root(source_run_id=SOURCE_ID)
        source = self.run_root(SOURCE_ID)
        calls = []
        session = self.session(snapshot_reader=lambda _: calls.append(1) or projection())
        manifest = self.ready(session)
        unrelated = self.run_root('p7-live-20261003123456-' + 'c' * 24)
        (unrelated / 'console-events.jsonl').write_text('unrelated')
        self.assertEqual(session.replay_manifest(RUN_ID)['revision'], manifest['revision'])
        (source / 'console-events.jsonl').write_text('changed source')
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-stale'):
            session.replay_level(RUN_ID, 2, manifest['revision'])
        changed = self.ready(session)
        self.assertNotEqual(changed['revision'], manifest['revision'])
        sibling = source.parent / f'cognition-live-{SOURCE_ID}-cognition.jsonl'
        sibling.write_text('new cognition')
        self.assertNotEqual(self.ready(session)['revision'], changed['revision'])
        self.assertEqual(len(calls), 3)

    def test_native_context_and_launch_fallback_sources_are_dependencies(self):
        root, source = self.run_root(), self.run_root(SOURCE_ID)
        (root / 'summary.json').unlink()
        trace = root / 'trace'
        trace.mkdir()
        (trace / 'prime-trace.jsonl').write_text(json.dumps({'kind': 'arc.run.context',
            'payload': {'source_run_id': SOURCE_ID}}) + '\n')
        session = self.session(snapshot_reader=lambda _: projection())
        first = self.ready(session)
        (source / 'console-events.jsonl').write_text('changed')
        self.assertNotEqual(self.ready(session)['revision'], first['revision'])
        (trace / 'prime-trace.jsonl').unlink()
        launch = root.parent / 'launches'
        launch.mkdir()
        (launch / (RUN_ID + '.json')).write_text(json.dumps({'source_run_id': SOURCE_ID}))
        second = self.ready(session)
        (source / 'console-events.jsonl').write_text('changed again')
        self.assertNotEqual(self.ready(session)['revision'], second['revision'])

    def test_changed_evidence_during_build_never_publishes_mixed_revision(self):
        root = self.run_root()
        entered, release = threading.Event(), threading.Event()
        calls = []

        def read(_):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                release.wait(2)
            return projection()

        session = self.session(snapshot_reader=read)
        self.addCleanup(release.set)
        session.replay_manifest(RUN_ID)
        self.assertTrue(entered.wait(1))
        (root / 'console-events.jsonl').write_text('changed')
        release.set()
        value = self.ready(session)
        self.assertEqual(value['state'], 'ready')
        self.assertEqual(len(calls), 2)

    def test_failure_is_redacted_and_explicit_retry_can_start_again(self):
        self.run_root()
        calls = []

        def read(_):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError('/private/sk-replay-secret')
            return projection()

        session = self.session(snapshot_reader=read)
        session.replay_manifest(RUN_ID)
        until = time.monotonic() + 2
        while time.monotonic() < until:
            try:
                session.replay_manifest(RUN_ID)
            except ConsoleSessionError as error:
                self.assertEqual(str(error), 'replay-unavailable')
                break
            time.sleep(.005)
        else:
            self.fail('failed build was not exposed')
        self.assertEqual(self.ready(session)['state'], 'ready')
        self.assertEqual(len(calls), 2)

    def test_invalid_identity_symlink_level_revision_and_closed_session_fail(self):
        root = self.run_root()
        session = self.session(snapshot_reader=lambda _: projection())
        value = self.ready(session)
        for level, revision in ((0, value['revision']), (3, value['revision']), (True, value['revision']),
                                (2, 'bad'), (2, value['revision'].upper())):
            with self.subTest(level=level, revision=revision):
                with self.assertRaises(ConsoleSessionError):
                    session.replay_level(RUN_ID, level, revision)
        (root / 'console-events.jsonl').symlink_to(root / 'summary.json')
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-unavailable'):
            session.replay_manifest(RUN_ID)
        session.close()
        with self.assertRaises(ConsoleSessionError):
            session.replay_manifest(RUN_ID)

    def test_valid_source_observations_do_not_decode_unused_sdk_grids(self):
        from asterion.applications.prime.p7.console_events import ConsoleEventWriter
        from asterion.applications.prime.p7.console_snapshot import build_console_snapshot
        from asterion.applications.prime.p7.observation_state import ObservationState
        from asterion.applications.prime.p7.score import digest
        root = self.run_root()
        sdk = root / 'recordings' / 'session'
        sdk.mkdir(parents=True)
        (sdk / 'test.jsonl').write_text('{}\n')
        observation = {'available_actions': ['ACTION1'], 'frame': [[[1]]],
                       'levels_completed': 0, 'win_levels': 2, 'state': 'NOT_FINISHED'}
        ConsoleEventWriter(root, RUN_ID, 'test-1').append('observation', {
            'source_action_sequence': 0, 'observation': observation,
            'observation_sha256': digest(ObservationState.from_observation(observation).to_projection())})
        (root / 'summary.json').unlink()
        with patch('asterion.applications.prime.p7.console_snapshot._observation',
                   side_effect=AssertionError('unused SDK grids were decoded')):
            self.assertEqual(build_console_snapshot(root)['levels'][0]['frames'][0]['grid'], [[1]])

    def test_pending_game_selection_is_replaced_and_ready_cache_evicts_oldest(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        ids = [RUN_ID] + ['p7-live-20261003123456-' + letter * 24 for letter in 'bcdef']
        for run_id in ids:
            self.run_root(run_id)

        def read(path):
            calls.append(path.name)
            if path.name == RUN_ID:
                entered.set()
                release.wait(2)
            return projection(path.name)

        session = self.session(snapshot_reader=read)
        self.addCleanup(release.set)
        session.replay_manifest(RUN_ID)
        self.assertTrue(entered.wait(1))
        session.replay_manifest(ids[1])
        session.replay_manifest(ids[2])
        release.set()
        self.ready(session, ids[2])
        self.assertEqual(calls[:2], [RUN_ID, ids[2]])
        first = session.replay_manifest(RUN_ID)
        for run_id in (ids[1], *ids[3:]):
            self.ready(session, run_id)
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-stale'):
            session.replay_level(RUN_ID, 2, first['revision'])

    def test_close_waits_for_owned_reader_and_prevents_late_publication(self):
        entered, release = threading.Event(), threading.Event()
        self.run_root()

        def read(_):
            entered.set()
            release.wait(2)
            return projection()

        session = self.session(snapshot_reader=read)
        self.addCleanup(release.set)
        session.replay_manifest(RUN_ID)
        self.assertTrue(entered.wait(1))
        closed = threading.Thread(target=session.close)
        closed.start()
        release.set()
        closed.join(1)
        self.assertFalse(closed.is_alive())
        self.assertFalse(session._replay_cache._ready)
        with self.assertRaises(ConsoleSessionError):
            session.replay_manifest(RUN_ID)

    def test_dependency_cycles_and_excessive_cache_entries_fail_closed(self):
        from asterion.applications.prime.p7.console_replay import ReplayProjectionCache
        self.run_root(source_run_id=SOURCE_ID)
        self.run_root(SOURCE_ID, source_run_id=RUN_ID)
        session = self.session(snapshot_reader=lambda _: projection())
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-unavailable'):
            session.replay_manifest(RUN_ID)
        root = self.run_root()
        cache = ReplayProjectionCache(lambda _: projection(), {'test-1'})
        self.addCleanup(cache.close)
        with patch('asterion.applications.prime.p7.console_replay._CACHE_BYTES', 1):
            cache.manifest(root.resolve())
            until = time.monotonic() + 2
            while time.monotonic() < until:
                try:
                    cache.manifest(root.resolve())
                except ValueError:
                    break
                time.sleep(.005)
            else:
                self.fail('oversized projection was not rejected')

    def test_long_source_chain_shared_dag_and_cycle_preserve_dependency_fences(self):
        from asterion.applications.prime.p7.console_replay import replay_fingerprint
        ids = [f'p7-live-20261003123456-{number:024x}' for number in range(12)]
        roots = [self.run_root(run_id, **({'source_run_id': ids[index + 1]} if index + 1 < len(ids) else {}))
                 for index, run_id in enumerate(ids)]
        # The later branch shares an already visited ancestor of the main chain.
        self.run_root(ids[0], source_run_id=ids[1], recovered_from=ids[5])
        before = replay_fingerprint(roots[0].resolve())
        self.assertEqual(before, replay_fingerprint(roots[0].resolve()))
        summary_paths = {str(root.resolve() / 'summary.json') for root in roots}
        self.assertTrue(summary_paths <= dict(before).keys())
        (roots[-1] / 'console-events.jsonl').write_text('{}\n')
        self.assertNotEqual(before, replay_fingerprint(roots[0].resolve()))
        with patch('asterion.applications.prime.p7.console_replay._MAX_PATHS', 2):
            with self.assertRaisesRegex(ValueError, 'replay unavailable'):
                replay_fingerprint(roots[0].resolve())
        self.run_root(ids[-1], source_run_id=ids[0])
        with self.assertRaisesRegex(ValueError, 'replay unavailable'):
            replay_fingerprint(roots[0].resolve())

    def test_paged_level_keeps_cross_level_events_on_unloaded_frames(self):
        from asterion.applications.prime.p7.console_replay import projection_level
        snapshot = projection()
        snapshot['levels'][1].update(frame_page={}, frame_count=95, frame_index_offset=1,
                                     frames=[{'id': 'f000001', 'grid': [[1]]}])
        event = {'level': 1, 'frame_id': 'f000095', 'kind': 'model_revision',
                 'payload': {'action_labels': [{'id': 'label-1'}]}}
        foreign = {**event, 'frame_id': 'f000096'}
        snapshot['process_events'] = [event, foreign]
        detail = projection_level(snapshot, 2, 'revision')
        self.assertEqual(detail['process_events'], [event])

    def test_trace_source_after_large_row_and_without_newline_invalidates_cache(self):
        from asterion.applications.prime.p7.console_replay import replay_fingerprint
        root = self.run_root()
        source = self.run_root(SOURCE_ID)
        trace = root / 'trace'
        trace.mkdir()
        (trace / 'prime-trace.jsonl').write_text(
            json.dumps({'kind': 'prime.model.round', 'payload': {'text': 'x' * 66000}}) + '\n'
            + json.dumps({'kind': 'arc.run.context', 'payload': {'source_run_id': SOURCE_ID}}))
        before = replay_fingerprint(root.resolve())
        (source / 'console-events.jsonl').write_text('{}\n')
        self.assertNotEqual(before, replay_fingerprint(root.resolve()))

    def test_reader_still_alive_after_close_reports_cleanup_unconfirmed(self):
        entered, release = threading.Event(), threading.Event()
        self.run_root()

        def read(_):
            entered.set()
            release.wait(2)
            return projection()

        session = self.session(snapshot_reader=read)
        self.addCleanup(release.set)
        session.replay_manifest(RUN_ID)
        self.assertTrue(entered.wait(1))
        worker = session._replay_cache._worker
        with patch.object(worker, 'join'):
            session.close()
        self.assertEqual(session.view()['state'], 'cleanup-unconfirmed')
        self.assertFalse(session.view()['cleanup_confirmed'])
        release.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())

    def sealed_root(self, run_id):
        root = self.run_root(run_id)
        (root / 'summary.json').write_text(json.dumps({
            'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': run_id,
            'experiment': {'game_id': 'test-1', 'seed': 0, 'model': 'gpt-6.1-sol'},
            'sealed_trace': True, 'replay_verified': True, 'cleanup_complete': True}))
        return root

    def test_foreground_replaces_pending_prewarm_and_prewarm_never_overwrites_foreground(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        ids = [RUN_ID] + ['p7-live-20261003123456-' + letter * 24 for letter in 'bcd']
        roots = [self.sealed_root(run_id) for run_id in ids]

        def read(path):
            calls.append(path.name)
            if path.name == RUN_ID:
                entered.set()
                release.wait(2)
            result = projection(path.name)
            result['run'].update(sealed_trace=True, replay_verified=True, completed_level_count=1)
            return result

        session = self.session(snapshot_reader=read)
        self.assertTrue(hasattr(session._replay_cache, 'prewarm'), 'bounded prewarm API is missing')
        self.addCleanup(release.set)
        session.replay_manifest(RUN_ID)
        self.assertTrue(entered.wait(1))
        session._replay_cache.prewarm(roots[1].resolve())
        session.replay_manifest(ids[2])
        session._replay_cache.prewarm(roots[3].resolve())
        release.set()
        self.ready(session, ids[2])
        self.assertEqual(calls, [RUN_ID, ids[2]])

    def test_overview_seeds_existing_best_and_prewarms_only_new_verified_sealed_source(self):
        ids = [RUN_ID] + ['p7-live-20261003123456-' + letter * 24 for letter in 'bc']
        for run_id in ids:
            self.sealed_root(run_id)
        calls = []
        entered = threading.Event()

        def read(path):
            calls.append(path.name)
            entered.set()
            result = projection(path.name)
            result['run'].update(sealed_trace=True, replay_verified=True, completed_level_count=1)
            return result

        session = self.session(snapshot_reader=read)
        value = {'scope': {'seed': 0, 'model_id': 'gpt-6.1-sol'}, 'games': [{
            'game_id': 'test-1', 'win_levels': 2, 'completed_levels': 1, 'best_run_id': RUN_ID,
            'active_run_id': None, 'runs': [{'run_id': RUN_ID, 'status': 'partial',
                'verified': True, 'sealed_trace': True, 'completed_levels': 1}]}]}

        class Reader:
            def build(self, **_):
                return deepcopy(value)

        session._overview_reader = Reader()
        session.overview()
        self.assertEqual(calls, [])
        game = value['games'][0]
        game['best_run_id'] = ids[1]
        game['runs'][0].update(run_id=ids[1], verified=False, sealed_trace=False)
        session.overview()
        session.overview()
        self.assertEqual(calls, [])
        game['best_run_id'] = ids[2]
        game['runs'][0].update(run_id=ids[2], verified=True, sealed_trace=True)
        session.overview()
        self.assertTrue(entered.wait(1), 'new verified source was not prewarmed')
        self.ready(session, ids[2])
        session.overview()
        self.assertEqual(calls, [ids[2]])

    def test_unsealed_or_active_candidate_cannot_be_prewarmed(self):
        root = self.run_root()
        calls = []
        session = self.session(snapshot_reader=lambda path: calls.append(path.name) or projection())
        self.assertTrue(hasattr(session._replay_cache, 'prewarm'), 'bounded prewarm API is missing')
        self.assertFalse(session._replay_cache.prewarm(root.resolve()))
        self.assertEqual(calls, [])
        value = {'scope': {'seed': 0, 'model_id': 'gpt-6.1-sol'}, 'games': [{
            'game_id': 'test-1', 'win_levels': 2, 'completed_levels': 1, 'best_run_id': None,
            'active_run_id': None, 'runs': []}]}

        class Reader:
            def build(self, **_):
                return deepcopy(value)

        session._overview_reader = Reader()
        session.overview()
        self.sealed_root(RUN_ID)
        value['games'][0].update(best_run_id=RUN_ID, active_run_id=RUN_ID,
                                runs=[{'run_id': RUN_ID, 'status': 'running', 'verified': True,
                                       'sealed_trace': True, 'completed_levels': 1}])
        session.overview()
        self.assertEqual(calls, [])
