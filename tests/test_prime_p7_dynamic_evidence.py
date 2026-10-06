"""Provider-free regression coverage for complete animation evidence."""
import unittest
from asterion.applications.prime.p7.broker import _snapshot_observation, _observation_digest
from asterion.applications.prime.p7.score import digest
from asterion.applications.prime.p7.observation_state import ObservationState


class TestDynamicEvidence(unittest.TestCase):
    def test_long_animation_preserves_legacy_canonical_digest(self):
        for count, pixel in ((57, 255), (95, 0)):
            with self.subTest(count=count):
                frame = [[[pixel] * 64 for _ in range(64)] for _ in range(count)]
                raw = dict(available_actions=['ACTION1'], frame=frame,
                           levels_completed=0, state='GAME_OVER', win_levels=7)
                expected = ObservationState.from_observation({**raw, 'frame': frame[-1:]}).to_projection()
                expected['frame'] = frame
                snapshot = _snapshot_observation(raw, win_levels=7)
                self.assertEqual(_observation_digest(snapshot), digest(expected))
                self.assertEqual(len(snapshot.frame), count)
                self.assertEqual(snapshot.frame[-1], tuple(map(tuple, frame[-1])))

    def test_metadata_and_defaults_keep_the_original_digest(self):
        raw = dict(available_actions=['ACTION1', 'ACTION6'], frame=[[[1, 255]], [[2, 0]]],
                   levels_completed=0, state='NOT_FINISHED', win_levels=7,
                   hud={'label': '动画', 'fraction': 1.25}, events=[{'kind': 'tick'}])
        expected = ObservationState.from_observation(raw).to_projection()
        self.assertEqual(_observation_digest(_snapshot_observation(raw, win_levels=7)), digest(expected))

    def test_lazy_animation_exceeds_old_total_limits_with_small_reference(self):
        from hashlib import sha256
        from asterion.applications.prime.p7.dynamic_evidence import AnimationFrames
        from asterion.applications.prime.p7.score import canonical_bytes
        count = 8200
        one = [[255] * 2048]
        frames = AnimationFrames.capture((one for _ in range(count)))
        reference = frames.reference()
        self.assertGreater(reference['byte_count'], 64 * 1024 * 1024)
        self.assertEqual(len(frames), count)
        self.assertLess(len(canonical_bytes(reference)), 1024)
        expected = sha256(b'[')
        encoded = canonical_bytes(one)
        for index in range(count):
            expected.update((b',' if index else b'') + encoded)
        expected.update(b']')
        self.assertEqual(reference['sha256'], 'sha256:' + expected.hexdigest())
        self.assertEqual(frames.page(count - 1), [tuple(map(tuple, one))])

    def test_persist_release_reopen_and_corruption_are_explicit(self):
        from pathlib import Path
        import tempfile
        from asterion.applications.prime.p7.dynamic_evidence import AnimationFrames, EvidenceProcessingError
        from asterion.applications.prime.p7.broker import persist_observation, read_observation
        raw = dict(available_actions=['ACTION1'], frame=[[[1, 2]], [[3, 4]]],
                   levels_completed=0, state='NOT_FINISHED', win_levels=7, hud={'secret': 'private-metadata'})
        observation = _snapshot_observation(raw, win_levels=7)
        temporary_arena = observation.frame._root
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ref = persist_observation(observation, root)
            self.assertFalse(temporary_arena.exists())
            self.assertTrue(observation.frame.durable)
            self.assertEqual(read_observation(root, ref), observation)
            self.assertNotIn('private-metadata', str(ref))
            frames = AnimationFrames.open(root, ref['animation_ref'])
            page = frames._root / 'nodes' / frames.reference()['frames_root_sha256']
            page.write_bytes(b'forged')
            with self.assertRaises(EvidenceProcessingError) as caught:
                frames.page(0)
            self.assertEqual(caught.exception.stage, 'derived-failed')
            self.assertTrue(caught.exception.durable)
            self.assertNotIn(str(root), str(caught.exception.diagnostic))

    def test_known_local_failure_never_dispatches_again_and_unknown_stays_unknown(self):
        from unittest.mock import patch
        from tests.test_prime_p7_native_broker import _broker
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError, ArcBrokerError
        broker, engine = _broker()
        with patch.object(broker, '_record_semantic_action', side_effect=OSError('/private/sentinel')):
            with self.assertRaises(EvidenceProcessingError) as caught:
                broker.act(('ACTION1',))
        self.assertTrue(caught.exception.outcome_known)
        self.assertEqual(caught.exception.stage, 'derived-failed')
        self.assertEqual(len(broker.journal), 1)
        with self.assertRaises(ArcBrokerError):
            broker.act(('ACTION1',))
        self.assertEqual(len(engine.calls), 1)
        broker, engine = _broker(raises_on=1)
        with self.assertRaises(EvidenceProcessingError) as unknown:
            broker.act(('ACTION1',))
        self.assertFalse(unknown.exception.outcome_known)
        self.assertEqual(unknown.exception.stage, 'dispatched-no-reply')

    def test_recording_reader_streams_animation_without_changing_metadata(self):
        from pathlib import Path
        import json
        import tempfile
        from asterion.applications.prime.p7.recording_stream import recording_rows
        from asterion.applications.prime.p7.dynamic_evidence import AnimationFrames
        raw = {'data': {'frame': [[[255] * 64 for _ in range(64)]] * 95,
                        'action_input': {'id': 'ACTION1', 'data': {}}, 'note': '动画'}, 'timestamp': 'fixture'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recording.jsonl'
            path.write_text(json.dumps(raw) + '\n' + json.dumps(raw))
            rows = recording_rows(path)
            first = next(rows)
            self.assertIsInstance(first['data']['frame'], AnimationFrames)
            self.assertEqual(len(first['data']['frame']), 95)
            self.assertEqual(first['data']['note'], '动画')
            self.assertEqual(next(rows)['data']['frame'], first['data']['frame'])
            self.assertEqual(next(recording_rows(path, include_frames=False))['data']['frame'], None)

    def test_cancel_and_deadline_are_distinct_from_missing_reply(self):
        import time
        from asterion.applications.prime.p7.dynamic_evidence import AnimationFrames, EvidenceProcessingError
        for kwargs, code in (({'cancelled': lambda: True}, 'evidence-cancelled'),
                             ({'deadline': time.monotonic() - 1}, 'evidence-deadline-exceeded')):
            with self.subTest(code=code), self.assertRaises(EvidenceProcessingError) as failure:
                AnimationFrames.capture([[[1]]], **kwargs)
            self.assertEqual(failure.exception.diagnostic['code'], code)
            self.assertEqual(failure.exception.stage, 'reply-received-unvalidated')
            self.assertFalse(failure.exception.outcome_known)

    def test_invalid_recording_recovery_preserves_gap_and_later_rows(self):
        import json
        import tempfile
        from pathlib import Path
        from asterion.applications.prime.p7.recording_stream import recording_rows
        valid = json.dumps({'data': {'frame': [[[1]]], 'action_input': {'id': 'RESET', 'data': {}}}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recording.jsonl'
            path.write_text(valid + '\n{"unfinished":\n' + valid + '\n')
            rows = list(recording_rows(path, recover_invalid=True))
            self.assertEqual(len(rows), 3)
            self.assertIsNone(rows[1])
            self.assertEqual(rows[2]['data']['frame'][0], ((1,),))
            with self.assertRaises(ValueError):
                list(recording_rows(path))

    def test_scope_binding_and_known_persistence_failure(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from tests.test_prime_p7_native_broker import _Engine
        from asterion.applications.prime.p7.broker import ArcBroker, persist_observation, read_observation
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError, ArcBrokerError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'run-test' / 'animation-evidence'
            engine = _Engine()
            engine.evidence_root = root
            broker = ArcBroker(engine=engine)
            scope = {'run_id': 'run-test', 'game_id': engine.game_id, 'seed': 0, 'sequence': 0}
            ref = persist_observation(broker.observe(), root, scope=scope)
            self.assertEqual(read_observation(root, ref, expected_scope=scope), broker.observe())
            with self.assertRaises(EvidenceProcessingError):
                read_observation(root, ref, expected_scope={**scope, 'sequence': 1})
            with patch('asterion.applications.prime.p7.broker.persist_observation',
                       side_effect=EvidenceProcessingError('evidence-write-failed')):
                with self.assertRaises(EvidenceProcessingError) as failure:
                    broker.act(('ACTION1',))
            self.assertTrue(failure.exception.outcome_known)
            self.assertFalse(failure.exception.durable)
            self.assertEqual(failure.exception.stage, 'validated-not-durable')
            self.assertEqual(broker.journal, ())
            with self.assertRaises(ArcBrokerError):
                broker.act(('ACTION1',))
            self.assertEqual(len(engine.calls), 1)

    def test_adapter_invalid_reply_is_not_missing_reply(self):
        from types import SimpleNamespace
        from asterion.applications.prime.p7.live import ArcadeEngine
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
        with self.assertRaises(EvidenceProcessingError) as failure:
            ArcadeEngine._snapshot(SimpleNamespace(available_actions=[]))
        self.assertEqual(failure.exception.stage, 'reply-received-invalid')
        self.assertEqual(failure.exception.diagnostic['code'], 'engine-response-invalid')

    def test_corrupt_existing_action_binding_cannot_claim_durable_commit(self):
        import tempfile
        from pathlib import Path
        from tests.test_prime_p7_native_broker import _Engine
        from asterion.applications.prime.p7.broker import ArcBroker
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / 'run-test' / 'animation-evidence'
            engine = _Engine()
            engine.evidence_root = root
            ArcBroker(engine=engine).act(('ACTION1',))
            next((root / 'actions').iterdir()).write_bytes(b'corrupt')
            following = _Engine()
            following.evidence_root = root
            broker = ArcBroker(engine=following)
            with self.assertRaises(EvidenceProcessingError) as failure:
                broker.act(('ACTION1',))
            self.assertTrue(failure.exception.outcome_known)
            self.assertFalse(failure.exception.durable)
            self.assertEqual(broker.journal, ())

    def test_authenticated_page_open_does_not_read_the_whole_animation(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from asterion.applications.prime.p7.dynamic_evidence import AnimationFrames
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            frames = AnimationFrames.capture([[[1]], [[2]]])
            reference = frames.persist(root)
            with patch.object(AnimationFrames, 'canonical_chunks', side_effect=AssertionError('whole read')):
                page = AnimationFrames.open(root, reference, verify_full=False).page(1)
            self.assertEqual(page, [((2,),)])
