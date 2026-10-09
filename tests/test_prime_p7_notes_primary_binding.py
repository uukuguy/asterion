"""P7 supplies notes and objective facts; native Prime owns archive cursors."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.prompt import build_autonomous_prompt
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal, _TraceClient


class TestNotesPrimaryBinding(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name) / 'notes-primary'
        root.mkdir()
        self.engine = _Engine()
        broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        broker.bind_history('notes-primary')
        self.host = P7ResearchRuntime(broker=broker, trace_client=_TraceClient(), run_root=root,
            run_id='notes-primary', deadline_seconds=30, event_sink=lambda *_: None,
            learner_profile='autonomous')
        self.addAsyncCleanup(self.host.close)
        self.host.set_memory_instructions('trusted immutable task')

    async def test_normal_notes_returns_v3_proposal_without_native_cursor(self):
        context = self.host.current_context()
        result = self.host.method_call('workspace', {'op': 'notes',
            'base_revision': context['workspace_revision'], 'observation_ref': context['observation_ref'],
            'text': 'Goal, return-path dependency, counterexample, unknown, program ref.'}, _Signal())
        self.assertEqual(result['status'], 'noted')
        memory = result['context_memory']
        self.assertEqual(set(memory), {'version', 'revision', 'content', 'commit'})
        self.assertEqual(memory['version'], 'asterion.prime-context-memory/v3')
        self.assertTrue(memory['commit'])
        self.assertEqual(memory['revision'], result['notes_revision'])
        state = json.loads(memory['content'].split('\n\n', 1)[1])
        self.assertEqual(state['notes']['revision'], result['notes_revision'])
        self.assertEqual(state['observation_ref'], context['observation_ref'])
        self.assertNotIn('worldmap', state)
        self.assertNotIn('model', state)
        self.assertIn('checkpoint', state)
        self.assertIn('budget', state)
        self.assertIn('worldmap', self.host.current_context())
        self.assertNotIn('context_checkpoint', result)
        self.assertEqual(result['context_interaction'], {
            'version': 'asterion.prime-context-interaction/v1',
            'effect': 'settled', 'feedback': 'ordinary'})
        self.assertEqual(self.engine.calls, [])

    async def test_optional_memory_failure_cannot_rollback_accepted_notes(self):
        context = self.host.current_context()
        with patch.object(self.host, '_context_memory', side_effect=ValueError('view unavailable')):
            result = self.host.method_call('workspace', {'op': 'notes',
                'base_revision': context['workspace_revision'], 'observation_ref': context['observation_ref'],
                'text': 'Accepted cognition remains saved.'}, _Signal())
        self.assertEqual(result['status'], 'noted')
        self.assertNotIn('context_memory', result)
        read = self.host.method_call('workspace', {'op': 'notes_read'}, _Signal())
        self.assertEqual(read['notes']['revision'], result['notes_revision'])
        self.assertEqual(read['notes']['text'], 'Accepted cognition remains saved.')
        self.assertEqual(self.engine.calls, [])

    async def test_native_archive_operations_cannot_dispatch_or_mutate_python(self):
        before = self.host.current_context()
        for request in ({'op': 'context_archive_list', 'start': 0, 'limit': 16},
                        {'op': 'context_archive_read', 'ref': {'session_id': 'opaque', 'entry_id': 'opaque'},
                         'start': 0, 'limit': 4096}):
            with self.subTest(op=request['op']):
                result = self.host.method_call('workspace', request, _Signal())
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(result['reason'], 'native-session-required')
                self.assertNotIn('context_memory', result)
                self.assertNotIn('context_checkpoint', result)
        self.assertEqual(self.host.current_context()['workspace_revision'], before['workspace_revision'])
        self.assertEqual(self.engine.calls, [])

    async def test_unknown_result_and_historical_reads_remain_unknown(self):
        context = self.host.current_context()
        self.host.method_call('workspace', {'op': 'notes', 'base_revision': context['workspace_revision'],
            'observation_ref': context['observation_ref'], 'text': 'Keep known facts.'}, _Signal())
        self.engine.raises_on = 1
        result = self.host.method_call('execute_plan', {'plan_id': 'unknown',
            'start': context['observation_ref'], 'steps': [{'action': {'name': 'ACTION1', 'data': {}}}]}, _Signal())
        self.assertEqual(result['context_interaction']['effect'], 'unknown')
        self.host.poll = lambda: {'state': 'running'}
        for op in ('notes_read', 'notes_history'):
            result = self.host.method_call('workspace', {'op': op}, _Signal())
            self.assertTrue(result['environment_result_unknown'])
            self.assertEqual(result['context_interaction']['effect'], 'unknown')
            self.assertFalse(result['context_memory']['commit'])
        self.assertEqual(len(self.engine.calls), 1)


class TestInteractionFacts(unittest.TestCase):
    def test_negative_feedback_uses_structured_evidence_without_semantic_keywords(self):
        ordinary = {'status': 'recorded', 'stop_reason': 'executed',
                    'goal': 'error mismatch danger', 'feedback': [{'differences': []}]}
        cases = [(ordinary, 'ordinary'),
                 ({**ordinary, 'feedback': [{'differences': ['cell-value']}]}, 'negative'),
                 ({**ordinary, 'precondition_feedback': [{'status': 'mismatch'}]}, 'negative'),
                 ({'status': 'rejected', 'reason': 'invalid-plan'}, 'negative')]
        for value, expected in cases:
            with self.subTest(value=value):
                original = copy.deepcopy(value)
                marker = P7ResearchRuntime._context_interaction(value, {
                    'environment_result_unknown': False, 'processing_blocked': False})
                self.assertEqual(marker['feedback'], expected)
                self.assertEqual(marker['effect'], 'settled')
                self.assertEqual(value, original)
        self.assertEqual(P7ResearchRuntime._context_interaction(ordinary, None)['effect'], 'unknown')

    def test_autonomous_prompt_explains_primary_notes_and_exact_archive_reads(self):
        text = build_autonomous_prompt()
        for fragment in ('主要工作认知', '往返路线', '重要错误和反例', '程序引用',
                         'context_archive_list', 'context_archive_read', 'session_id', 'entry_id',
                         '完整工具组', '未知结果', '16KiB'):
            self.assertIn(fragment, text)
        self.assertNotIn('更新笔记只替换状态快照', text)
        self.assertNotIn('建议用简短 NOTES', text)
