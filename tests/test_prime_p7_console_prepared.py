from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time
from unittest.mock import patch

from asterion.applications.prime.p7 import console_export
from asterion.applications.prime.p7.console_replay import replay_fingerprint
from asterion.applications.prime.p7.console_session import ConsoleSessionError
from tests.test_prime_p7_console_replay import projection, SOURCE_ID
from tests.test_prime_p7_console_session import ConsoleSessionFixture, RUN_ID


class TestPrimeP7ConsolePrepared(ConsoleSessionFixture):
    def test_prepared_animation_pages_bind_revision_and_preserve_metadata_on_missing_page(self):
        from asterion.applications.prime.p7.console_frames import FrameStore, frame_page
        root, snapshot = self.saved()
        snapshot.update(schema='asterion.arc-agi3-p7-console/v2', diagnostics=[])
        metadata = dict(timestamp='', available_actions=['ACTION1'], event_sequence=1,
                        state='NOT_FINISHED', levels_completed=0)
        store = FrameStore(root, 2)
        store.append_animation(([[i % 10]] for i in range(95)), metadata, 1)
        token = store.finish()
        page = frame_page(root, 2, None, token, 0, 32)
        bucket = snapshot['levels'][1]
        bucket.update(frames=page['frames'], frame_count=95, frame_index_offset=1,
                      frame_page=dict(start=0, limit=32, source_token=token))
        bucket['actions'][0].update(before_frame='f000001', after_frame='f000095',
                                    before_frame_index=0, after_frame_index=94)
        for event in snapshot['process_events']:
            event['frame_id'] = 'f000001'
        self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: self.fail('paged projection rebuilt'))
        manifest = session.replay_manifest(RUN_ID)
        self.assertEqual(manifest['levels'][1]['frame_count'], 95)
        detail = session.replay_level(RUN_ID, 2, manifest['revision'])
        self.assertEqual(len(detail['levels'][0]['frames']), 32)
        from asterion.applications.prime.p7.console_prepared import _detail
        crossed = deepcopy(detail)
        crossed_event = deepcopy(crossed['process_events'][0])
        crossed_event.update(level=1, frame_id='f000095', event_sequence=10000)
        crossed['process_events'].append(crossed_event)
        _detail(crossed, manifest, 2)
        crossed_event['frame_id'] = 'f000096'
        with self.assertRaises(ValueError):
            _detail(crossed, manifest, 2)
        crossed_event['frame_id'] = 'f0000095'
        with self.assertRaises(ValueError):
            _detail(crossed, manifest, 2)
        for index in (True, 95, 1):
            with self.subTest(invalid_frame_index=index):
                invalid = deepcopy(detail)
                invalid['levels'][0]['cognition_timeline'].append(
                    dict(scope='observation', frame_id='f000001', frame_index=index))
                with self.assertRaises(ValueError):
                    _detail(invalid, manifest, 2)
        last = session.replay_frames(RUN_ID, 2, manifest['revision'], token, 94, 1)
        self.assertEqual(last['frames'][0]['index'], 94)
        with self.assertRaises(ConsoleSessionError) as stale:
            session.replay_frames(RUN_ID, 2, '0' * 64, token, 94, 1)
        self.assertEqual(str(stale.exception), 'replay-stale')
        (root / 'console-frame-evidence' / (token + '.json')).unlink()
        with self.assertRaises(ConsoleSessionError) as missing:
            session.replay_frames(RUN_ID, 2, manifest['revision'], token, 94, 1)
        self.assertEqual(str(missing.exception), 'replay-frame-unavailable')
        self.assertEqual(session.replay_level(RUN_ID, 2, manifest['revision'])['levels'][0]['actions'], bucket['actions'])

    def test_prepared_replay_preserves_typed_warning_projection(self):
        from asterion.applications.prime.p7.processing_diagnostics import DiagnosticLog
        root, snapshot = self.saved()
        warning = DiagnosticLog().record({
            'diagnostic_id': 'diagnostic-1', 'code': 'derived-projection-failed',
            'severity': 'warning', 'stage': 'derived-failed', 'action_sequence': 1,
            'outcome_known': True, 'durable': True, 'observed': None, 'limit': None,
            'unit': None, 'recovery': 'read-only-rebuild',
        })
        snapshot.update(schema='asterion.arc-agi3-p7-console/v2', diagnostics=[warning])
        self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: self.fail('prepared diagnostic was discarded'))
        manifest = session.replay_manifest(RUN_ID)
        self.assertEqual(manifest['diagnostics'], [warning])
        self.assertEqual(manifest['schema'], 'asterion.arc-agi3-p7-replay-manifest/v2')
        detail = session.replay_level(RUN_ID, 2, manifest['revision'])
        self.assertEqual(detail['diagnostics'], [warning])

    def saved(self, source_id=None):
        root = self.root.resolve() / '.asterion-private' / 'prime-p7-live' / RUN_ID
        root.mkdir(parents=True, exist_ok=True)
        summary = {'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': RUN_ID,
            'sealed_trace': True, 'replay_verified': True, 'cleanup_complete': True,
            'experiment': {'game_id': 'test-1', 'seed': 0, 'model': 'gpt-6.1-sol', 'target_level': 2},
            'broker': {'game_id': 'test-1', 'seed': 0, 'win_levels': 2, 'levels_completed': 2}}
        if source_id:
            summary['diagnostics'] = {'source_run_id': source_id}
            (root.parent / source_id).mkdir(exist_ok=True)
        (root / 'summary.json').write_text(json.dumps(summary))
        snapshot = projection()
        snapshot['run'].update(completed_level_count=2, seed=0, target_level=2,
                               primitive_action_count=1, model='gpt-6.1-sol',
                               sealed_trace=True, replay_verified=True)
        for number, event in enumerate(snapshot['process_events'], 1):
            event.update(kind='observation', event_sequence=number, source_action_sequence=0,
                         payload={'source_action_sequence': 0,
                                                      'observation_sha256': 'sha256:' + 'a' * 64})
        for level in snapshot['levels']:
            for frame in level['frames']:
                frame.update(timestamp='', available_actions=['ACTION1'], event_sequence=1,
                             state='NOT_FINISHED', levels_completed=0)
            for action in level['actions']:
                action.update(name='ACTION1', data={}, levels_completed=2, changed_cells=1,
                              trace_sequence=1, visual_observations=[], source_action_sequence=1)
        for decisions in [snapshot['decisions'], *[level['decisions'] for level in snapshot['levels']]]:
            for decision in decisions:
                if 'round_index' in decision:
                    decision.update(trace_sequence=1, action_ids=[], prompt_signals=[], output_signals=[])
                else:
                    decision.update(goal='safe', basis='safe', expected='safe', source_action_sequence=0,
                                    observation_sha256='sha256:' + 'a' * 64, action_ids=['a1'], event_sequence=1)
        return root, snapshot

    def save(self, root, snapshot):
        with patch.object(console_export, 'build_console_snapshot', return_value=deepcopy(snapshot)):
            console_export.export_console(root, root / 'view.html')

    def test_saved_projection_is_ready_in_fresh_session_without_raw_builder(self):
        self.assertTrue(Path(console_export.__file__).with_name('console_prepared.py').is_file(),
                        'durable prepared replay publisher is missing')
        root, snapshot = self.saved()
        before = replay_fingerprint(root)
        self.save(root, snapshot)
        self.assertEqual(replay_fingerprint(root), before)
        (root / 'another-view.html').write_text('derived')
        self.assertEqual(replay_fingerprint(root), before)
        session = self.session(snapshot_reader=lambda _: self.fail('raw snapshot builder was invoked'))
        manifest = session.replay_manifest(RUN_ID)
        self.assertEqual(manifest['state'], 'ready')
        detail = session.replay_level(RUN_ID, 2, manifest['revision'])
        self.assertEqual(detail['levels'], snapshot['levels'][1:])
        self.assertEqual(detail['decisions'], snapshot['decisions'])
        self.assertEqual(detail['process_events'], snapshot['process_events'][:2])
        self.assertFalse(session._replay_cache._worker)

    def test_ancestor_change_invalidates_prepared_revision_and_falls_back(self):
        root, snapshot = self.saved(SOURCE_ID)
        self.save(root, snapshot)
        entered = []
        session = self.session(snapshot_reader=lambda _: entered.append(1) or snapshot)
        first = session.replay_manifest(RUN_ID)
        self.assertEqual(first['state'], 'ready')
        (root.parent / SOURCE_ID / 'console-events.jsonl').write_text('changed ancestor')
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-stale'):
            session.replay_level(RUN_ID, 2, first['revision'])
        self.assertEqual(session.replay_manifest(RUN_ID)['state'], 'loading')

    def test_manifest_does_not_read_unselected_level_and_selected_corruption_falls_back(self):
        root, snapshot = self.saved()
        self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: snapshot)
        first = session.replay_manifest(RUN_ID)
        directory = root / 'console-prepared' / first['revision']
        (directory / 'level-002.json').write_text('corrupt selected asset')
        self.assertEqual(session.replay_manifest(RUN_ID), first)
        self.assertEqual(session.replay_level(RUN_ID, 1, first['revision'])['levels'], snapshot['levels'][:1])
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-stale'):
            session.replay_level(RUN_ID, 2, first['revision'])
        (directory / 'level-002.json').unlink()
        until = time.monotonic() + 2
        while time.monotonic() < until:
            rebuilt = session.replay_manifest(RUN_ID)
            if rebuilt['state'] == 'ready':
                break
            time.sleep(.005)
        self.assertEqual(rebuilt['state'], 'ready')
        self.assertNotEqual(rebuilt['revision'], first['revision'])
        self.assertEqual(session.replay_level(RUN_ID, 2, rebuilt['revision'])['levels'], snapshot['levels'][1:])
        fresh = self.session(snapshot_reader=lambda _: self.fail('repaired durable source rebuilt again'))
        self.assertEqual(fresh.replay_manifest(RUN_ID)['revision'], rebuilt['revision'])

    def test_save_reuses_revision_and_repairs_corrupt_derived_assets(self):
        root, snapshot = self.saved()
        self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: self.fail('raw snapshot builder was invoked'))
        first = session.replay_manifest(RUN_ID)
        directory = root / 'console-prepared' / first['revision']
        original = (directory / 'manifest.json').read_bytes()
        snapshot['generated_at'] = 'new save timestamp'
        self.save(root, snapshot)
        self.assertEqual((directory / 'manifest.json').read_bytes(), original)
        (directory / 'level-002.json').write_text('corrupt')
        self.save(root, snapshot)
        repaired = session.replay_manifest(RUN_ID)
        self.assertNotEqual(repaired['revision'], first['revision'])
        self.assertEqual(session.replay_level(RUN_ID, 2, repaired['revision'])['levels'], snapshot['levels'][1:])

    def test_save_with_changing_evidence_or_failed_admission_never_publishes(self):
        root, snapshot = self.saved()

        def changing(_):
            (root / 'console-events.jsonl').write_text('writer changed evidence')
            return snapshot

        with patch.object(console_export, 'build_console_snapshot', side_effect=changing):
            console_export.export_console(root, root / 'view.html')
        self.assertFalse((root / 'console-prepared' / 'current.json').exists())
        snapshot['run']['sealed_trace'] = False
        self.save(root, snapshot)
        self.assertFalse((root / 'console-prepared' / 'current.json').exists())

    def test_verified_prefix_uses_existing_save_proof_and_preserves_full_run_flags(self):
        root, snapshot = self.saved()
        snapshot['run'].update(replay_verified=False, status='incomplete')
        with patch.object(console_export, '_verified_partial', return_value=False) as proof:
            self.save(root, snapshot)
        proof.assert_called_once()
        self.assertFalse((root / 'console-prepared' / 'current.json').exists())
        with patch.object(console_export, '_verified_partial', return_value=({'levels_completed': 2}, ())):
            self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: self.fail('prepared partial source rebuilt'))
        value = session.replay_manifest(RUN_ID)
        self.assertEqual(value['state'], 'ready')
        self.assertFalse(value['run']['replay_verified'])
        self.assertEqual(value['run']['status'], 'incomplete')
        index = json.loads((root / 'console-prepared' / 'current.json').read_text())
        self.assertEqual(index['verification_kind'], 'verified-prefix')

    def test_generations_are_bounded_and_private_or_linked_details_are_not_served(self):
        root, snapshot = self.saved()
        for index in range(4):
            if index:
                (root / 'console-events.jsonl').write_text(str(index))
            self.save(root, snapshot)
        directories = [path for path in (root / 'console-prepared').iterdir() if path.is_dir()]
        self.assertEqual(len(directories), 2)
        session = self.session(snapshot_reader=lambda _: snapshot)
        manifest = session.replay_manifest(RUN_ID)
        directory = root / 'console-prepared' / manifest['revision']
        (directory / 'level-002.json').unlink()
        (directory / 'level-002.json').symlink_to(root / 'summary.json')
        with self.assertRaisesRegex(ConsoleSessionError, 'replay-stale'):
            session.replay_level(RUN_ID, 2, manifest['revision'])
        from asterion.applications.prime.p7.console_prepared import publish_prepared
        hostile = deepcopy(snapshot)
        hostile['levels'][1]['cognition']['prompt'] = '/private/sk-prepared-secret'
        self.assertIsNone(publish_prepared(root, hostile, replay_fingerprint(root)))

    def test_nested_public_fields_reject_private_additions(self):
        from asterion.applications.prime.p7.console_prepared import publish_prepared
        root, snapshot = self.saved()
        additions = [
            ('provenance', {'run_id': SOURCE_ID, 'event_sequence': 7, 'debug': '/private/sk-prepared-secret'}),
            ('session', {'debug': '/private/sk-prepared-secret'}),
            ('world_map_facts', {'debug': '/private/sk-prepared-secret'}),
            ('updates', [{'type': 'cognition.updated', 'sequence': 1, 'changes': [], 'debug': '/private/sk-prepared-secret'}]),
            ('action_meanings', {'ACTION1': [{'status': 'certain', 'claim': 'safe', 'debug': '/private/sk-prepared-secret'}]})]
        for key, value in additions:
            with self.subTest(field=key):
                hostile = deepcopy(snapshot)
                hostile['levels'][1]['cognition'][key] = value
                self.assertIsNone(publish_prepared(root, hostile, replay_fingerprint(root)))
        for field in ('receipt', 'action-data'):
            with self.subTest(field=field):
                hostile = deepcopy(snapshot)
                if field == 'receipt':
                    hostile['levels'][1]['receipt'] = {'debug': '/private/sk-prepared-secret'}
                else:
                    hostile['levels'][1]['actions'][0]['data'] = {'debug': '/private/sk-prepared-secret'}
                self.assertIsNone(publish_prepared(root, hostile, replay_fingerprint(root)))
        self.assertFalse((root / 'console-prepared').exists())

    def test_matching_hash_with_invalid_public_shape_is_repaired_to_new_generation(self):
        root, snapshot = self.saved()
        self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: snapshot)
        first = session.replay_manifest(RUN_ID)
        base = root / 'console-prepared'
        path = base / first['revision'] / 'level-002.json'
        detail = json.loads(path.read_bytes())
        detail['levels'][0]['cognition']['provenance']['debug'] = '/private/sk-prepared-secret'
        raw = json.dumps(detail).encode()
        path.write_bytes(raw)
        index = json.loads((base / 'current.json').read_bytes())
        index['levels'][1].update(sha256=sha256(raw).hexdigest(), size=len(raw))
        (base / 'current.json').write_text(json.dumps(index))
        self.save(root, snapshot)
        repaired = session.replay_manifest(RUN_ID)
        self.assertNotEqual(repaired['revision'], first['revision'])
        fresh = self.session(snapshot_reader=lambda _: self.fail('invalid generation was reused'))
        manifest = fresh.replay_manifest(RUN_ID)
        self.assertEqual(manifest['state'], 'ready')
        value = fresh.replay_level(RUN_ID, 2, manifest['revision'])
        self.assertNotIn('debug', value['levels'][0]['cognition']['provenance'])

    def test_restored_model_evidence_keeps_original_sequence_space(self):
        from asterion.applications.prime.p7.console_prepared import _cognition, _events
        root, snapshot = self.saved()
        event = {'event_sequence': 4, 'kind': 'model_revision', 'source_action_sequence': 59,
                 'frame_id': 'f2', 'level': 2,
                 'provenance': {'run_id': SOURCE_ID, 'event_sequence': 341},
                 'payload': {'source_action_sequence': 59, 'observation_sha256': 'sha256:' + 'a' * 64,
                     'level': 2, 'workspace_revision': 'model-1', 'task_id': None, 'origin': 'actor',
                     'revision': 'model-1', 'parent_revision': None, 'description_zh': 'safe restored belief',
                     'state_summary': 'safe', 'rule_summaries': [], 'unknowns': [],
                     'coverage_summary': 'safe', 'validation_summary': 'safe', 'correction_summary': 'safe',
                     'evidence_sequences': [68],
                     'action_labels': [{'action': 'ACTION5', 'label': '旋转', 'purpose': '旋转当前形状。',
                                        'confidence': 'certain', 'evidence_sequences': [68]}]}}
        cognition = snapshot['levels'][1]['cognition']
        cognition.update(source_action_sequence=59, action_labels=deepcopy(event['payload']['action_labels']))
        snapshot['process_events'].append(deepcopy(event))
        snapshot['levels'][1]['research_timeline'].append(deepcopy(event))
        self.save(root, snapshot)
        session = self.session(snapshot_reader=lambda _: self.fail('restored model projection rebuilt'))
        manifest = session.replay_manifest(RUN_ID)
        self.assertEqual(manifest['state'], 'ready')
        detail = session.replay_level(RUN_ID, 2, manifest['revision'])
        self.assertEqual(detail['levels'][0]['research_timeline'], [event])
        self.assertEqual(detail['levels'][0]['cognition']['action_labels'], event['payload']['action_labels'])
        native_cognition = deepcopy(cognition)
        del native_cognition['provenance']
        with self.assertRaises(ValueError):
            _cognition(native_cognition)
        private_cognition = deepcopy(cognition)
        private_cognition['action_labels'][0]['purpose'] = 'token=PREPARED-SENTINEL'
        with self.assertRaises(ValueError):
            _cognition(private_cognition)
        native = deepcopy(event)
        del native['provenance']
        with self.assertRaises(ValueError):
            _events([native])
        for changes in ({'description_zh': '/private/sk-prepared-secret'},
                        {'evidence_sequences': [10**9 + 1]}, {'source_action_sequence': True},
                        {'debug': '/private/sk-prepared-secret'}):
            with self.subTest(changes=list(changes)):
                invalid = deepcopy(event)
                invalid['payload'].update(changes)
                with self.assertRaises(ValueError):
                    _events([invalid])
