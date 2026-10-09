"""Application marks board state only; Prime owns native message projection."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime


class TestP7ToolStateView(unittest.TestCase):
    def host(self, response):
        host = P7ResearchRuntime.__new__(P7ResearchRuntime)
        host._closed = False
        host.poll = lambda: {'state': 'running'}
        host.solver = SimpleNamespace(execute_plan=lambda plan: copy.deepcopy(response),
                                      workspace=lambda request: copy.deepcopy(response))
        host._context_memory = lambda **kwargs: None
        return host

    def response(self):
        return {'status': 'recorded', 'plan_id': 'plan', 'stop_reason': 'executed',
                'observation_ref': {'run_id': 'run', 'attempt_id': 'run', 'level': 1,
                                    'sequence': 3, 'observation_sha256': 'sha256:' + 'a' * 64},
                'observation': {'frame': [[[2] * 64 for _ in range(64)]],
                                'animation_ref': {'frame_count': 3}, 'animation_paged': True,
                                'state': 'NOT_FINISHED', 'levels_completed': 0},
                'feedback': [{'expected': {'cells': [{'x': 2, 'y': 3, 'value': 7}]},
                              'actual': {'state': 'NOT_FINISHED'}, 'differences': ['counterexample']}],
                'unexecuted_steps': [{'action': {'name': 'ACTION3', 'data': {}}}],
                'budget': {'actions_remaining': 99}}

    def test_marker_removes_only_archived_board_and_animation_and_preserves_feedback(self):
        response = self.response()
        original = copy.deepcopy(response)
        host = self.host(response)
        delivered = host.method_call('execute_plan', {'plan': {}}, SimpleNamespace(cancelled=False))
        self.assertIn('tool_state_view', delivered)
        marker = delivered['tool_state_view']
        self.assertEqual(set(marker), {'version', 'state_key', 'replacement_text'})
        replacement = json.loads(marker['replacement_text'])
        actual = {key: value for key, value in delivered.items() if key != 'tool_state_view'}
        observation = replacement.pop('observation')
        current = actual.pop('observation')
        self.assertEqual(replacement, actual)
        self.assertEqual(observation['frame_read']['sequence'], 3)
        self.assertEqual(observation['frame_read']['read_api'], 'p7_research.frame(sequence)')
        self.assertEqual(observation['animation_read']['observation_ref'], response['observation_ref'])
        self.assertEqual(observation['animation_read']['read_api'], 'p7_research.animation(observation_ref)')
        for field in ('frame', 'frame_delivery', 'animation_ref'):
            self.assertNotIn(field, observation)
            current.pop(field, None)
        observation.pop('frame_read')
        observation.pop('animation_read')
        self.assertEqual(observation, current)
        self.assertEqual(response, original)

    def test_notes_errors_and_unknown_effects_have_no_state_marker(self):
        for method, change in [('workspace', {}), ('execute_plan', {'status': 'rejected'}),
                               ('execute_plan', {'environment_result_unknown': True}),
                               ('execute_plan', {'processing_blocked': True}),
                               ('execute_plan', {'stop_reason': 'processing-failed'}),
                               ('execute_plan', {'stop_reason': 'environment-result-unknown'}),
                               ('execute_plan', {'uncertain_step': {'action': 'unknown'}})]:
            with self.subTest(method=method, change=change):
                response = {**self.response(), **change}
                host = self.host(response)
                with patch('asterion.applications.prime.p7.research_runtime.project_actor_result',
                           side_effect=lambda *args: copy.deepcopy(args[-1])):
                    result = host.method_call(method, {'request': {'op': 'notes'}}, SimpleNamespace(cancelled=False))
                self.assertNotIn('tool_state_view', result)

    def test_optional_view_serialization_failure_preserves_action_response(self):
        for invalid in (float('nan'), object()):
            with self.subTest(kind=type(invalid).__name__):
                response = self.response()
                response['extra_result'] = invalid
                host = self.host(response)
                with patch('asterion.applications.prime.p7.research_runtime.project_actor_result',
                           side_effect=lambda *args: args[-1]):
                    result = host.method_call('execute_plan', {'plan': {}}, SimpleNamespace(cancelled=False))
                self.assertNotIn('tool_state_view', result)
                self.assertEqual(result['feedback'], response['feedback'])
                self.assertEqual(result['observation'], response['observation'])
