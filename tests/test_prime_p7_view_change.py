"""Bounded literal view translation, and action-free committed history reads."""
import asyncio
import copy
import importlib
import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.research_bridge import ResearchReadServer


def scene():
    rng = random.Random(29)
    return [[0 if rng.random() < .6 else rng.randrange(1, 8)
             for _ in range(64)] for _ in range(64)]


def shifted(frame, dx, dy):
    height, width = len(frame), len(frame[0])
    return [[frame[y-dy][x-dx] if 0 <= y-dy < height and 0 <= x-dx < width else 0
             for x in range(width)] for y in range(height)]


class TestP7ViewChange(unittest.TestCase):
    def measure(self, before, after):
        name = 'asterion.applications.prime.p7.view_change'
        self.assertIsNotNone(importlib.util.find_spec(name), 'bounded view detector is missing')
        return importlib.import_module(name).view_change(before, after)

    def test_exact_axis_translations_report_literal_direction_and_exposed_bounds(self):
        before = scene()
        for dx, dy, window in ((6, 0, [0, 0, 6, 64]), (-6, 0, [58, 0, 64, 64]),
                               (0, 6, [0, 0, 64, 6]), (0, -6, [0, 58, 64, 64])):
            with self.subTest(dx=dx, dy=dy):
                after = shifted(before, dx, dy)
                value = self.measure(before, after)
                self.assertEqual(value['status'], 'candidate')
                self.assertEqual((value['dx'], value['dy']), (dx, dy))
                self.assertEqual(value['exposed_windows'], [window])
                self.assertEqual(value['matched_pairs'], value['informative_pairs'])
                self.assertLessEqual(value['candidate_count'], 129)
                self.assertLessEqual(value['checked_pairs'], 528384)
                self.assertLessEqual(len(json.dumps(value, separators=(',', ':')).encode()), 2048)
                self.assertNotIn('pixels', value)

    def test_static_local_edits_and_player_motion_do_not_become_view_candidates(self):
        original = scene()
        player = copy.deepcopy(original)
        moved = copy.deepcopy(original)
        edited = copy.deepcopy(original)
        for y in range(30, 34):
            for x in range(30, 34):
                player[y][x] = 15
                moved[y][x+4] = 15
                edited[y][x] = 8
        for before, after in ((original, original), (original, edited), (player, moved)):
            with self.subTest(case=after is original):
                value = self.measure(before, after)
                self.assertEqual(value['status'], 'no-candidate')
                self.assertNotIn('dx', value)
                self.assertEqual(value['exposed_windows'], [])

    def test_flat_and_periodic_textures_retain_ambiguity(self):
        flat = [[4] * 64 for _ in range(64)]
        periodic = [[(x+y) % 2 for x in range(64)] for y in range(64)]
        for before, after in ((flat, flat), (periodic, [[1-v for v in row] for row in periodic])):
            with self.subTest(flat=before is flat):
                value = self.measure(before, after)
                self.assertEqual(value['status'], 'ambiguous')
                self.assertNotIn('dx', value)
                self.assertEqual(value['exposed_windows'], [])

    def test_joint_modal_tie_is_deterministic_and_colors_are_not_roles(self):
        periodic = [[(x+y) % 2 for x in range(64)] for y in range(64)]
        value = self.measure(periodic, [[1-v for v in row] for row in periodic])
        self.assertEqual(value['modal_color'], 0)
        before = scene()
        palette = {0: 255, **{v: 8-v for v in range(1, 8)}}
        recolored = [[palette[v] for v in row] for row in before]
        shifted_colors = shifted(recolored, 6, 0)
        for row in shifted_colors:
            row[:6] = [255] * 6
        measured = self.measure(recolored, shifted_colors)
        self.assertEqual((measured['status'], measured['dx']), ('candidate', 6))

    def test_foreground_union_and_zero_use_each_alignments_actual_denominator(self):
        before = scene()
        after = shifted(before, 6, 0)
        for y in range(10, 30):
            for x in range(10, 50):
                if before[y][x-6] == 0 and (x+y) % 11 == 0:
                    after[y][x] = 10
        value = self.measure(before, after)
        self.assertEqual(value['status'], 'candidate')
        self.assertGreater(value['informative_pairs'], value['before_overlap_informative'])
        self.assertNotEqual(value['zero_informative_pairs'], value['informative_pairs'])
        self.assertGreaterEqual(value['before_overlap_informative']*2, value['informative_before'])
        self.assertGreaterEqual(value['matched_pairs']*2, value['informative_after'])

    def test_low_score_competitor_is_retained_for_uniqueness_margin(self):
        rng = random.Random(0)
        tile = [[0 if rng.random() < .6 else rng.randrange(1, 8)
                 for _ in range(64)] for _ in range(12)]
        before = [tile[y % 12][:] for y in range(64)]
        before[31] = [0 if rng.random() < .6 else rng.randrange(1, 8) for _ in range(64)]
        after = shifted(before, 0, 6)
        for row in after:
            for x in range(64):
                if rng.random() < .07:
                    row[x] = rng.randrange(8)
        value = self.measure(before, after)
        self.assertEqual(value['status'], 'ambiguous')
        self.assertEqual(value['reason'], 'competing-alignments')
        self.assertGreaterEqual(value['matched_pairs']/value['informative_pairs'], .85)
        self.assertLess(value['runner_matched_pairs']/value['runner_informative_pairs'], .85)

    def test_shapes_cell_cap_and_validation_stay_bounded_without_coercion(self):
        for before, after in (([[0]*65 for _ in range(64)], [[0]*65 for _ in range(64)]),
                              ([[0]*64 for _ in range(64)], [[0]*63 for _ in range(64)])):
            with self.subTest(shape=len(after[0])):
                value = self.measure(before, after)
                self.assertEqual(value['status'], 'unsupported')
                self.assertEqual(value['checked_pairs'], 0)
        for invalid in ([], [[True]], [[1.0]], [[256]], [[-1]], [[0], [0, 1]]):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.measure(invalid, [[0]])

    def test_inputs_outputs_are_detached_and_full_animation_is_not_analyzed(self):
        before = scene()
        after = shifted(before, 0, 6)
        snapshot = copy.deepcopy((before, after))
        value = self.measure([[[255]], before], [[[255]], after])
        self.assertEqual(value['status'], 'candidate')
        value['exposed_windows'][0][0] = 99
        self.assertEqual((before, after), snapshot)
        self.assertEqual(self.measure(before, after)['exposed_windows'], [[0, 0, 64, 6]])

    def test_oversized_dimensions_return_before_copying_or_validating_grid(self):
        name = 'asterion.applications.prime.p7.view_change'
        self.assertIsNotNone(importlib.util.find_spec(name))
        detector = importlib.import_module(name)
        with patch.object(detector, 'grid', side_effect=AssertionError('must not copy oversized data')):
            value = detector.view_change([[0]*65 for _ in range(64)], [[0]*65 for _ in range(64)])
            self.assertEqual(value['status'], 'unsupported')
            self.assertEqual(value['checked_pairs'], 0)


class TestP7ViewChangeRead(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('asterion.applications.prime.p7.view_change'),
                             'bounded view detector is missing')
        from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
        from tests.test_prime_p7_research_runtime import _TraceClient
        from tests.test_prime_p7_research_transition import _Engine
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.runner = asyncio.Runner()
        self.addCleanup(self.runner.close)
        root = Path(tmp.name).resolve() / 'view-story'
        root.mkdir()
        self.engine = _Engine()
        game = P7GameSelection(self.engine.game_id, self.engine.seed, target_level=2,
                              _metadata_win_levels=7, _metadata_baseline_actions=(1,) * 7)
        self.broker = ArcBroker(engine=self.engine, game=game, action_profile='autonomous')
        self.broker.bind_history(root.name)
        self.host = P7ResearchRuntime(broker=self.broker, trace_client=_TraceClient(),
            run_root=root, run_id=root.name, deadline_seconds=30, event_sink=lambda *_: None)
        self.addCleanup(lambda: self.runner.run(self.host.close()))

    def test_history_read_reuses_exact_committed_refs_without_engine_calls(self):
        before = self.host.current_context()['observation_ref']
        self.broker.act(('ACTION2',))
        after = self.host.current_context()['observation_ref']
        reads = self.host._read_server
        value = reads.dispatch({'method': 'view_change', 'args': [0, None]})
        self.assertEqual(value['status'], 'ok')
        measurement = value['value']
        self.assertEqual((measurement['before_sequence'], measurement['after_sequence']), (0, 1))
        self.assertEqual(measurement['before_observation_ref'], before)
        self.assertEqual(measurement['after_observation_ref'], after)
        self.broker.act(('ACTION1',))
        historical = reads.dispatch({'method': 'view_change', 'args': [0, 1]})
        self.assertEqual(historical, value)
        self.assertEqual(len(self.engine.calls), 2)
        measurement['before_observation_ref']['sequence'] = 99
        self.assertEqual(reads.dispatch({'method': 'view_change', 'args': [0, 1]}), historical)

    def test_wire_rejects_invalid_sequences_before_reading(self):
        reads = self.host._read_server
        self.assertIn('view_change', reads._readers)
        with patch.dict(reads._readers, context=lambda: self.fail('invalid read'),
                        frame=lambda *_: self.fail('invalid read')):
            for args in ([], [0], [0, None, 1], [None, None], [False, None],
                         [-1, None], ['0', None], [0, False], [0, 1.0], [0, -1]):
                with self.subTest(args=args):
                    self.assertEqual(reads.dispatch({'method': 'view_change', 'args': args})['status'], 'rejected')
        self.assertEqual(self.engine.calls, [])

    def test_initial_read_and_generated_module_use_existing_transport(self):
        module = {}
        exec(self.host._read_server.start(), module)
        self.assertTrue(callable(module.get('view_change')))
        value = module['view_change'](0)
        ref = self.host.current_context()['observation_ref']
        self.assertEqual(value['before_observation_ref'], ref)
        self.assertEqual(value['after_observation_ref'], ref)
        self.assertEqual(self.engine.calls, [])

    def test_unresolved_transaction_cannot_be_used_as_committed_view_evidence(self):
        from asterion.applications.prime.p7.action_journal import ActionJournal
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        journal = ActionJournal(Path(tmp.name).resolve()/'transactions', {'run_id': self.host.solver.run_id})
        self.engine.action_journal = journal
        with patch.object(journal, 'commit', side_effect=OSError('private fault')):
            with self.assertRaises(EvidenceProcessingError):
                self.broker.act(('ACTION2',))
        result = self.host._read_server.dispatch({'method': 'view_change', 'args': [0, 1]})
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(self.engine.calls), 1)

    def test_omitted_after_resolves_current_sequence_once(self):
        calls = []
        current = {'sequence': 1, 'run_id': 'read-once', 'attempt_id': 'read-once',
                   'level': 1, 'observation_sha256': 'sha256:'+'1'*64}
        before = {**current, 'sequence': 0, 'observation_sha256': 'sha256:'+'0'*64}
        def context():
            calls.append('context')
            return {'observation_ref': {**current, 'sequence': len(calls)}}
        frames = {0: scene(), 1: shifted(scene(), 6, 0)}
        reads = ResearchReadServer(context=context, history=lambda *_: [],
            frame=lambda seq: frames[seq], artifact=lambda _: None,
            transition=lambda seq: {'before_observation_ref': before, 'after_observation_ref': current})
        self.addCleanup(reads.close)
        value = reads.dispatch({'method': 'view_change', 'args': [0, None]})
        self.assertEqual(value['status'], 'ok')
        self.assertEqual(value['value']['after_sequence'], 1)
        self.assertEqual(value['value']['after_observation_ref'], current)
        self.assertEqual(calls, ['context'])
