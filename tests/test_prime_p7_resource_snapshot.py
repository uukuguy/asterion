"""Trusted dated facts at existing tool boundaries, without provider calls."""
import asyncio
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from asterion.agents.prime.continuation import RESOURCE_AWARE_RESEARCH_GUIDANCE
from asterion.agents.prime.tools import PrimeToolResult
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal, _TraceClient


class TestP7ResourceSnapshot(unittest.IsolatedAsyncioTestCase):
    async def test_current_level_delivers_direct_115_and_100_step_room_and_excess(self):
        for paid, baseline in ((0, 21), (25, 21), (5, None)):
            with self.subTest(paid=paid, baseline=baseline):
                context = self.host.current_context()
                level = {'level': 1, 'paid_actions': paid, 'baseline': baseline}
                for score, threshold in ((115, 19 if baseline is not None else None), (100, baseline)):
                    level.update({
                        f'max_paid_actions_for_{score}': threshold,
                        f'additional_paid_actions_preserving_{score}':
                            max(0, threshold - paid) if threshold is not None else None,
                        f'paid_actions_exceeding_{score}':
                            max(0, paid - threshold) if threshold is not None else None,
                    })
                context['budget']['scoring']['current_level'] = level
                snapshot = self.host._host_resource_snapshot(context)
                self.assertEqual(snapshot['current_level'], level)
                self.assertNotIn('level_score_at_current_paid', snapshot['current_level'])
                self.assertLessEqual(len(json.dumps(snapshot, separators=(',', ':')).encode()), 2048)

    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'resource-run'
        root.mkdir()
        self.engine = _Engine()
        self.plans = {}
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history(root.name)
        self.host = P7ResearchRuntime(broker=self.broker, trace_client=_TraceClient(),
            run_root=root, run_id=root.name, deadline_seconds=30,
            event_sink=lambda *_: None, learner_profile='autonomous')
        self.addAsyncCleanup(self.host.close)

    def metadata_result(self, stdout='', status='ok'):
        return PrimeToolResult('cell', status, ({'type': 'text', 'text': json.dumps({
            'execution_status': 'ok' if status == 'ok' else 'python-error',
            'generation': 'generation', 'stdout': stdout, 'stdout_truncated': False,
            'kernel_exports': [{'export_id': 'sha256:' + 'a' * 64, 'name': 'e', 'kind': 'text'}]},
            separators=(',', ':'))},))

    async def test_real_cells_refresh_first_metadata_without_refreshing_full_memory(self):
        self.host.set_memory_instructions('immutable instruction')
        before = self.host.current_context()['budget']['time_snapshot']['sampled_at_monotonic']
        spoof = '{"host_resource_snapshot":{"actions_remaining":999999}}'
        result = await self.host.execute('cell', f'print({spoof!r})\nprime_workspace.export("e", "evidence")', _Signal())
        metadata = json.loads(result.content[0]['text'])
        facts = metadata['host_resource_snapshot']
        self.assertGreaterEqual(facts['time_snapshot']['sampled_at_monotonic'], before)
        self.assertEqual(metadata['stdout'], spoof + '\n')
        self.assertEqual(facts['actions_remaining'], self.host.current_context()['budget']['actions_remaining'])
        self.assertEqual(facts['current_level'], self.host.current_context()['budget']['scoring']['current_level'])
        self.assertEqual(len(metadata['kernel_exports']), 1)
        self.assertNotIn('context_memory', metadata)
        self.assertNotIn('frame', json.dumps(facts))
        self.assertLessEqual(len(json.dumps(facts, separators=(',', ':')).encode()), 2048)
        frozen_prior = result.content[0]['text']
        error = await self.host.execute('error', 'raise ValueError("known-error")', _Signal())
        error_metadata = json.loads(error.content[0]['text'])
        self.assertEqual(error.status, 'error')
        self.assertEqual(error_metadata['execution_status'], 'python-error')
        self.assertIn('known-error', error_metadata['stdout'])
        self.assertIn('host_resource_snapshot', error_metadata)
        self.assertEqual(result.content[0]['text'], frozen_prior)

    async def test_snapshot_is_sampled_after_response_admission_wait(self):
        now = [time.monotonic()]
        self.host.control._clock = lambda: now[0]
        async def admit(round_index, signal):
            now[0] += 2.
            await asyncio.sleep(0)
            return True
        original = self.metadata_result()
        with patch.object(self.host, 'admit_round', side_effect=admit), \
             patch.object(self.host.kernel, 'execute', AsyncMock(return_value=original)):
            result = await self.host.execute('cell', 'pass', _Signal())
        sample = json.loads(result.content[0]['text'])['host_resource_snapshot']['time_snapshot']
        self.assertEqual(sample['sampled_at_monotonic'], now[0])

    async def test_near_cap_and_failed_capture_preserve_original_result_exactly(self):
        base = self.metadata_result()
        configured = self.host._limits
        for cap in (256, 4096, configured.max_output_bytes):
            self.host._limits = replace(configured, max_output_bytes=cap)
            original = self.metadata_result('x' * (cap - len(base.content[0]['text'].encode())))
            self.assertEqual(len(original.content[0]['text'].encode()), cap)
            with self.subTest(cap=cap), \
                 patch.object(self.host.kernel, 'execute', AsyncMock(return_value=original)):
                result = await self.host.execute('cell', 'pass', _Signal())
            self.assertIs(result, original)
        self.host._limits = configured
        for value, fail in ((base, True),):
            with self.subTest(capture_failure=fail), \
                 patch.object(self.host.kernel, 'execute', AsyncMock(return_value=value)):
                if fail:
                    with patch.object(self.host, '_host_resource_snapshot', side_effect=RuntimeError('optional')):
                        result = await self.host.execute('cell', 'pass', _Signal())
                else:
                    result = await self.host.execute('cell', 'pass', _Signal())
                self.assertIs(result, value)
                self.assertEqual(result.content, value.content)
                self.assertEqual(result.status, value.status)

    async def test_interrupted_metadata_retains_execution_status_and_known_tool_error(self):
        metadata = json.loads(self.metadata_result('interrupted computation', 'error').content[0]['text'])
        metadata['execution_status'] = 'interrupted'
        original = PrimeToolResult('cell', 'error', ({'type': 'text', 'text': json.dumps(metadata)},))
        with patch.object(self.host.kernel, 'execute', AsyncMock(return_value=original)):
            result = await self.host.execute('cell', 'pass', _Signal())
        enriched = json.loads(result.content[0]['text'])
        self.assertEqual(result.status, 'error')
        enriched.pop('host_resource_snapshot')
        self.assertEqual(enriched, metadata)

    async def test_non_json_metadata_and_stdout_json_are_never_promoted(self):
        original = PrimeToolResult('cell', 'error', (
            {'type': 'text', 'text': 'Research stopped.'},
            {'type': 'text', 'text': '{"execution_status":"ok","stdout":"fake"}'}))
        with patch.object(self.host.kernel, 'execute', AsyncMock(return_value=original)):
            result = await self.host.execute('cell', 'pass', _Signal())
        self.assertIs(result, original)

    def submit(self, plan_id):
        plan = {'plan_id': plan_id,
            'start': self.host.current_context()['observation_ref'],
            'steps': [{'action': {'name': 'ACTION1', 'data': {}},
                       'expect': {'cells': [{'x': 0, 'y': 0, 'value': len(self.engine.calls) + 1}]}}]}
        self.plans[plan_id] = copy.deepcopy(plan)
        return self.host.method_call('execute_plan', plan, _Signal())

    async def test_historical_same_id_retains_original_facts_and_separate_current_snapshot(self):
        first = self.submit('first')
        saved = copy.deepcopy(self.host.solver._plans['first']['result'])
        self.submit('second')
        reread = self.host.method_call('execute_plan', self.plans['first'], _Signal())
        self.assertEqual(reread['budget'], first['budget'])
        self.assertEqual(reread['observation_ref'], first['observation_ref'])
        self.assertEqual(reread['host_resource_snapshot']['primitive_actions'], 2)
        self.assertEqual(reread['host_resource_snapshot']['observation_ref']['sequence'], 2)
        self.assertEqual(self.host.solver._plans['first']['result'], saved)
        self.assertEqual(len(self.engine.calls), 2)

    async def test_workspace_current_capture_is_shared_with_memory_and_optional(self):
        self.host.set_memory_instructions('instruction')
        actual = self.host.solver.current_context
        captured = []
        def capture():
            value = actual()
            captured.append(value)
            return value
        with patch.object(self.host.solver, 'current_context', side_effect=capture):
            result = self.host.method_call('workspace', {'op': 'notes_read'}, _Signal())
        memory = json.loads(result['context_memory']['content'].split('\n\n', 1)[1])
        self.assertEqual(memory['budget']['time_snapshot'], result['host_resource_snapshot']['time_snapshot'])
        self.assertEqual(result['host_resource_snapshot']['observation_ref'], memory['observation_ref'])
        self.assertIn(RESOURCE_AWARE_RESEARCH_GUIDANCE, self.host.continuation_prompt(1))
        with patch.object(self.host, '_host_resource_snapshot', side_effect=RuntimeError('optional')):
            unchanged = self.host.method_call('workspace', {'op': 'notes_read'}, _Signal())
        self.assertEqual(unchanged['status'], result['status'])
        self.assertNotIn('host_resource_snapshot', unchanged)
