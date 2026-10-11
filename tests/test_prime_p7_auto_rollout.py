"""Provider-free automatic evaluation in the existing P7 computation kernel."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from asterion.applications.prime.p7.tool_dispatch import P7ToolDispatch
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal, _TraceClient


class TestRecoveredRolloutRegistration(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_invalidates_registration_replayed_by_checkpoint_source(self):
        for fail_invalidation in (False, True):
            with self.subTest(fail_invalidation=fail_invalidation):
                calls = []
                restored = SimpleNamespace(registration='replayed-checkpoint-model')
                host = P7ResearchRuntime.__new__(P7ResearchRuntime)
                host.kernel = SimpleNamespace(status=lambda: {'lost': True})
                host.solver = SimpleNamespace(checkpoint=lambda: None,
                    kernel_recovered=lambda: calls.append('recovered'))

                async def restore(previous, sources, data, signal):
                    return restored

                async def invalidate(signal):
                    self.assertIs(host.kernel, restored)
                    calls.append('invalidated')
                    if fail_invalidation:
                        raise ValueError('invalidation unavailable')
                    restored.registration = None

                host._workspace_owner = SimpleNamespace(restore_workspace=restore)
                host._rollouts = SimpleNamespace(invalidate=invalidate)
                if fail_invalidation:
                    with self.assertRaises(ValueError):
                        await host._recover_kernel(_Signal())
                    self.assertEqual(calls, ['invalidated'])
                else:
                    await host._recover_kernel(_Signal())
                    self.assertIsNone(restored.registration)
                    self.assertEqual(calls, ['invalidated', 'recovered'])


class TestP7AutoRollout(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'auto-run'
        self.root.mkdir()
        self.engine = _Engine()
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history('auto-run')
        self.host = P7ResearchRuntime(broker=self.broker, trace_client=_TraceClient(),
            run_root=self.root, run_id='auto-run', deadline_seconds=20,
            event_sink=lambda *_: None, learner_profile='autonomous', auto_rollout=True)
        self.addAsyncCleanup(self.host.close)
        self.tools = P7ToolDispatch(self.host, _TraceClient(), run_id='auto-run')

    async def model(self, end, risk='return []', extra=''):
        source = "import p7_research as r\n" + (
            "def init(board,ref): return {'tick':0,'seq':ref['sequence'],'pixel':board[0][0]}\n"
            "def move(state,action):\n state['tick']+=1\n print('model diagnostics')\n return state\n"
            "def rest(state): return state['tick']>=3\n"
            f"def end(state): {end}\n"
            f"def risk(before,after,action): {risk}\n"
            "print(r.register_rollout_model(from_frame=init,transition=move,settled=rest,terminal=end,risk_check=risk))\n"
        ) + extra
        return await self.host.execute('model', source, _Signal())

    async def plan(self, name='plan', names=('ACTION1',)):
        value = {'plan_id': name, 'start': self.host.current_context()['observation_ref'],
                 'steps': [{'action': {'name': n, 'data': {}}} for n in names],
                 'stop_on_view_change': False}
        result = await asyncio.wait_for(self.tools.call(name, 'execute_plan', value, _Signal()), 10)
        return json.loads(result['output'])

    async def test_same_kernel_fresh_snapshot_and_delayed_death_stop_batch(self):
        result = await self.model("return 'dead' if state['seq']==1 and state['tick']>=2 else None")
        self.assertEqual(result.status, 'ok')
        result = await self.plan(names=('ACTION1', 'ACTION1'))
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'model-predicted-death'))
        self.assertEqual([x['observation_ref']['sequence'] for x in result['auto_rollouts']], [0, 1])
        self.assertEqual([x['ticks'] for x in result['auto_rollouts']], [3, 2])
        self.assertEqual(self.engine.calls, ['ACTION1'])
        self.assertEqual(result['rollout_accounting']['actor_kernel_cells'], 1)
        self.assertEqual(result['rollout_accounting']['auto_kernel_cells'], 2)
        self.assertEqual(result['rollout_accounting']['actor_helper_calls'], 0)
        self.assertTrue(list((self.root/'rollout-evidence').glob('*.json.zlib')))
        self.assertNotIn('states', result['auto_rollouts'][1])

    async def test_model_missing_records_attempt_without_claiming_evaluated(self):
        result = await self.plan()
        item = result['auto_rollouts'][0]
        self.assertEqual((item['status'], item['risk'], item['reason']), ('not_evaluated', 'unassessed', 'model_missing'))
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['rollout_accounting']['auto_evaluated'], 0)

    async def test_conditional_fatal_stops_without_dispatch(self):
        await self.model('return None', "return [{'id':'local.assumption','type':'conditional_fatal','condition':'hypothesis','evidence':'model tick'}]")
        result = await self.plan()
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-conditional-fatal'))
        self.assertEqual(self.engine.calls, [])

    async def test_proactive_registered_candidate_matches_but_raw_helper_does_not(self):
        await self.model('return None', extra="print(r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}}))\n")
        result = await self.plan()
        self.assertEqual(result['auto_rollouts'][0]['matched_actor_calls'], [1])
        self.assertEqual(result['rollout_accounting']['actor_helper_calls'], 1)

    async def test_failed_actor_cell_keeps_actual_calls_on_original_revision(self):
        result = await self.model('return None', extra="r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\nraise ValueError('later')\n")
        self.assertEqual(result.status, 'error')
        result = await self.plan()
        self.assertEqual(result['auto_rollouts'][0]['matched_actor_calls'], [1])
        self.assertEqual(result['rollout_accounting']['actor_helper_calls'], 1)

    async def test_cancel_during_auto_kernel_never_dispatches_action(self):
        await self.model('return None', "import time; time.sleep(0.2); r.current(); return []")
        signal = _Signal()
        value = {'plan_id': 'cancel', 'start': self.host.current_context()['observation_ref'],
                 'steps': [{'action': {'name': 'ACTION1', 'data': {}}}]}
        pending = asyncio.create_task(self.tools.call('cancel', 'execute_plan', value, signal))
        await asyncio.sleep(0.05)
        signal.cancelled = True
        await asyncio.wait_for(pending, 5)
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(self.host.solver._plans['cancel']['result']['stop_reason'], 'cancelled')

    async def test_evidence_write_failure_cannot_erase_known_fatal_risk(self):
        from unittest.mock import patch
        await self.model("return 'dead' if state['tick']>=2 else None")
        original = Path.write_bytes
        def write(path, value):
            if path.suffix == '.zlib':
                raise OSError('artifact unavailable')
            return original(path, value)
        with patch.object(Path, 'write_bytes', write), patch.object(self.host._rollouts, '_append', side_effect=OSError('record unavailable')):
            result = await self.plan()
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-predicted-death'))
        self.assertEqual(result['auto_rollouts'][0]['risk'], 'predicted_death')
        self.assertEqual(result['auto_rollouts'][0]['evidence_status'], 'call_record_unavailable')
        self.assertEqual(self.engine.calls, [])

