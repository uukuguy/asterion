"""Actor-only delivery preserves evidence while avoiding repeated board dumps."""

import copy
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.actor_projection import (
    ActorProjectionError,
    decode_actor_frame,
    encode_actor_frame,
    project_actor_context,
    project_actor_result,
)
from asterion.applications.prime.p7.score import canonical_bytes, digest


REFERENCE = {'run_id': 'projection-run', 'attempt_id': 'projection-run',
             'level': 6, 'sequence': 150, 'observation_sha256': 'sha256:' + 'a' * 64}


def board():
    return [[0 if x < 12 or y < 8 else 12 + (x // 8 + y // 8) % 4
             for x in range(64)] for y in range(64)]


class TestActorFrameCodec(unittest.TestCase):
    def test_exact_roundtrip_shape_determinism_and_size(self):
        grid = board()
        changed = copy.deepcopy(grid)
        changed[31][22] = 255
        for frame in (grid, [grid], changed, [changed]):
            with self.subTest(layered=isinstance(frame[0][0], list), changed=frame == changed):
                original = copy.deepcopy(frame)
                encoded = encode_actor_frame(frame, REFERENCE)
                self.assertEqual(encoded['encoding'], 'palette-row-dictionary/v1')
                self.assertEqual(encoded['shape'], [1, 64, 64] if len(frame) == 1 else [64, 64])
                self.assertEqual(encoded['settled_frame_sha256'], digest(frame[0] if len(frame) == 1 else frame))
                self.assertEqual(encoded['observation_ref'], REFERENCE)
                self.assertEqual(encoded['read_api'], 'p7_research.frame(sequence)')
                self.assertEqual(decode_actor_frame(encoded), frame)
                self.assertEqual(encode_actor_frame(frame, REFERENCE), encoded)
                self.assertLess(len(canonical_bytes(encoded)), len(canonical_bytes(frame)) // 2)
                self.assertEqual(frame, original)

    def test_small_and_full_byte_palette_fall_back_losslessly(self):
        for frame in ([[[0, 1]]], [list(range(256))]):
            with self.subTest(frame_width=len(frame[0])):
                encoded = encode_actor_frame(frame, REFERENCE)
                self.assertEqual(encoded['encoding'], 'raw')
                self.assertEqual(decode_actor_frame(encoded), frame)
                projected = project_actor_context({'observation': {'frame': frame}, 'observation_ref': REFERENCE})
                self.assertEqual(projected['observation']['frame'], frame)
                self.assertEqual(projected['observation']['frame_delivery']['encoding'], 'raw')

    def test_decoder_rejects_corrupt_or_extended_encoding(self):
        encoded = encode_actor_frame([board()], REFERENCE)
        changes = (
            {'row_ids': [999] * 64}, {'shape': [1, 64, 63]},
            {'palette': [False]}, {'rows': ['?'] * 64},
            {'settled_frame_sha256': 'sha256:' + 'b' * 64}, {'unexpected': 'extension'},
        )
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(ActorProjectionError):
                    decode_actor_frame({**encoded, **change})
        for frame in ([], [[[1]], [[2]]], [[-1]], [[256]], [[True]], [[1], [1, 2]]):
            with self.subTest(invalid_frame=frame):
                with self.assertRaises(ActorProjectionError):
                    encode_actor_frame(frame, REFERENCE)

    def test_dimensions_are_bounded_before_frame_copy_or_decoder_expansion(self):
        over_limit = [[1] * 1025] * 1024
        encoded = encode_actor_frame([board()], REFERENCE)
        with patch('asterion.applications.prime.p7.actor_projection.deepcopy',
                   side_effect=AssertionError('copied before size validation')):
            with self.assertRaises(ActorProjectionError):
                project_actor_context({'observation': {'frame': over_limit}, 'observation_ref': REFERENCE})
            with self.assertRaises(ActorProjectionError):
                decode_actor_frame({**encoded, 'shape': [1, 1024, 1025]})


class TestActorProjection(unittest.TestCase):
    def test_context_and_recorded_plan_change_only_frame(self):
        context = {
            'observation_ref': REFERENCE, 'observation': {
                'frame': [board()], 'state': 'NOT_FINISHED', 'levels_completed': 5,
                'available_actions': ['ACTION3', 'ACTION6'], 'win_levels': 9,
                'input_kind': 'mixed', 'animation_ref': {'frame_count': 3}, 'animation_paged': True,
                'hud': {'visible': 12}, 'projection_truncated': True,
            },
            'workspace_revision': 'current', 'parent_revision': 'parent',
            'worldmap': {'description_zh': 'current-model'}, 'model': {'coverage': 'unknown'},
            'task': {'goal': 'level6'}, 'experience': {'latest': 'positive', 'quarantine': ['old']},
            'budget': {'actions_remaining': 23, 'deadline': 100}, 'lifecycle': {'state': 'running'},
            'needs_revision': True, 'revision_reason': 'prediction-mismatch',
            'requires_calibration': True, 'processing_blocked': True,
            'environment_result_unknown': True, 'diagnostics': [{'code': 'fault'}],
            'checkpoint': {'state': 'saved'}, 'correction': {'changed': ['counterexample']},
        }
        plan = {**context, 'status': 'recorded', 'plan_id': 'plan', 'applied_count': 2,
                'stop_reason': 'prediction-mismatch', 'feedback': [
                    {'expected': {'cells': [{'x': 22, 'y': 31, 'value': 255}]},
                     'actual': {'state': 'GAME_OVER'}, 'differences': ['value'],
                     'counterexample_sequence': 151, 'mismatch': {'kind': 'cell'}}],
                'unexecuted_steps': [{'action': 'ACTION6', 'expect': {'state': 'WIN'}}],
                'uncertain_step_index': 2, 'uncertain_step': {'action': 'ACTION6'},
                'future_feedback_extension': {'keep': True}}
        for value in (context, plan):
            with self.subTest(plan='plan_id' in value):
                original = copy.deepcopy(value)
                projected = (project_actor_result('execute_plan', {}, value)
                             if 'plan_id' in value else project_actor_context(value))
                self.assertEqual(set(projected), set(value))
                self.assertEqual(set(projected['observation']), set(value['observation']))
                self.assertEqual(decode_actor_frame(projected['observation']['frame']), value['observation']['frame'])
                projected['observation']['frame'] = copy.deepcopy(value['observation']['frame'])
                self.assertEqual(projected, value)
                self.assertEqual(value, original)
        projected = project_actor_context(context)
        projected['experience']['quarantine'].append('mutation')
        self.assertEqual(context['experience']['quarantine'], ['old'])

    def test_closed_success_ack_fields_preserve_validation_and_diagnostics(self):
        fields = {'workspace_revision': 'current', 'parent_revision': 'previous', 'scope': {'run_id': 'run'},
                  'evidence_sequences': [150], 'observation_ref': REFERENCE, 'budget': {'actions_remaining': 20},
                  'lifecycle': {'state': 'running'}, 'requires_calibration': True, 'needs_revision': True,
                  'revision_reason': 'initial', 'environment_result_unknown': True, 'processing_blocked': True,
                  'diagnostics': [{'code': 'fault'}], 'checkpoint': None, 'correction': {'changed': ['new']},
                  'projection_truncated': True}
        echoes = {'worldmap': {}, 'model': {}, 'task': {}, 'reports': [], 'observation': {'frame': [board()]},
                  'experience': {'latest': 'positive'}}
        for op, status in (('revise', 'revised'), ('publish', 'published')):
            with self.subTest(op=op):
                source = {'status': status, **fields, **echoes}
                original = copy.deepcopy(source)
                ack = project_actor_result('workspace', {'request': {'op': op}}, source)
                self.assertEqual(ack, {'status': status, **fields})
                self.assertEqual(source, original)
                with self.assertRaisesRegex(ActorProjectionError, 'requires review'):
                    project_actor_result('workspace', {'op': op}, {**source, 'unknown_extension': 'retain-or-review'})

    def test_rejected_stopped_and_small_operations_pass_through_exactly(self):
        for method, request, response in (
            ('workspace', {'op': 'revise'}, {'status': 'rejected', 'reason': 'invalid', 'diagnostics': ['fault'],
                                           'observation': {'frame': [board()]}, 'needs_revision': True}),
            ('execute_plan', {}, {'status': 'stopped', 'reason': 'paused', 'observation': {'frame': [board()]}}),
            ('execute_plan', {}, {'status': 'rejected', 'requires_calibration': True, 'observation_ref': REFERENCE}),
            ('workspace', {'op': 'focus'}, {'status': 'focused', 'task': {'goal': 'next'}}),
            ('workspace', {'op': 'checkpoint'}, {'status': 'checkpointed', 'checkpoint': {'saved': True}}),
        ):
            with self.subTest(method=method, request=request):
                self.assertEqual(project_actor_result(method, request, response), response)

    def test_historical_workspace_read_preserves_selected_revision_and_latest_observation(self):
        source = {'workspace_revision': 'historical', 'parent_revision': 'old-parent',
                  'evidence_sequences': [12], 'worldmap': {'description_zh': 'old-model'},
                  'observation_ref': REFERENCE, 'observation': {'frame': [board()]}}
        result = project_actor_result('workspace', {'op': 'read', 'revision': 'historical'}, source)
        self.assertEqual(result['workspace_revision'], 'historical')
        self.assertEqual(result['observation_ref']['sequence'], 150)
        self.assertEqual(result['evidence_sequences'], [12])
        self.assertEqual(decode_actor_frame(result['observation']['frame']), source['observation']['frame'])
