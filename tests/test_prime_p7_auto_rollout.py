"""Provider-free automatic evaluation in the existing P7 computation kernel."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zlib

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from asterion.applications.prime.p7.rollout_runtime import RolloutRuntime
from asterion.applications.prime.p7.tool_dispatch import P7ToolDispatch
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal, _TraceClient


class TestRolloutFeedback(unittest.TestCase):
    def test_known_actual_death_preserves_mismatch_and_uncertainty_with_archive_failure(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            runtime = RolloutRuntime(SimpleNamespace(), Path(directory))
            self.assertTrue(callable(getattr(runtime, 'record_feedback', None)))
            before, after = {'sequence': 25}, {'sequence': 26}
            action = {'name': 'ACTION6', 'data': {'x': 39, 'y': 33}}
            revision = {'generation': 'g', 'registration_id': 1, 'last_actor_cell_id': 'cell:a'}
            assessment = {'status': 'evaluated', 'risk': 'no_identified_fatal',
                          'outcome': 'settled',
                          'model_revision': revision, 'result_artifact_id': 'sha256:'+'a'*64}
            result = runtime.record_feedback(assessment, before, after, action, 'GAME_OVER')
            self.assertEqual(result['type'], 'model_mismatch')
            self.assertEqual(result['before_observation_ref'], before)
            self.assertEqual(result['after_observation_ref'], after)
            self.assertEqual(result['full_trace_ref'], assessment['result_artifact_id'])
            self.assertEqual(result['model_revision'], revision)
            self.assertEqual(runtime.model_case_status(revision), 'counterexample_observed')
            self.assertEqual(runtime.model_case_status({**revision,'last_actor_cell_id':'cell:b'}), 'counterexample_observed')
            self.assertIsNone(runtime.record_feedback(assessment, before, after, action, 'NOT_FINISHED'))
            with patch.object(runtime, '_append', side_effect=OSError('archive unavailable')):
                result = runtime.record_feedback({'risk':'unassessed'}, before, after, action, 'GAME_OVER')
            self.assertEqual(result['type'], 'death_not_assessed')
            self.assertEqual(result['evidence_status'], 'feedback_record_unavailable')
            for outcome in ('settled', 'goal', 'collision', 'unknown'):
                with self.subTest(outcome=outcome):
                    result = runtime.record_feedback({'status':'evaluated','risk':'unassessed','outcome':outcome}, before, after, action, 'GAME_OVER')
                    self.assertEqual(result['type'], 'death_not_assessed' if outcome == 'unknown' else 'model_mismatch')

    def test_current_run_death_case_matches_only_same_pixels_level_and_action(self):
        from asterion.applications.prime.p7.score import digest
        with tempfile.TemporaryDirectory() as directory:
            runtime = RolloutRuntime(SimpleNamespace(_closed=False), Path(directory))
            frame = [[15, 10]]
            action = {'name':'ACTION6','data':{'x':39,'y':33}}
            before = {'sequence':25,'level':2}
            after = {'sequence':26,'level':2}
            runtime.record_feedback({'status':'evaluated','risk':'unassessed','outcome':'unknown',
                                     'frame_sha256':digest(frame)}, before, after, action, 'GAME_OVER')
            for pixels, level, candidate, expected in (
                    (frame,2,action,True), ([[15,11]],2,action,False),
                    (frame,3,action,False), (frame,2,{'name':'ACTION3','data':{}},False)):
                with self.subTest(pixels=pixels,level=level,candidate=candidate):
                    result = runtime.evaluate({'frame':[pixels]}, {'sequence':99,'level':level}, candidate)
                    self.assertEqual(result['risk'], 'conditional_fatal' if expected else 'unassessed')
                    if expected:
                        self.assertEqual(result['findings'][0]['evidence']['after_observation_ref'], after)
                        self.assertEqual(result['findings'][0]['evidence']['source'], 'current_run_death_case')


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

    async def test_actor_death_backtest_summary_retains_full_trace_and_internal_results(self):
        source = """import p7_research as r
import json
def move(s,a): s['tick']+=1; return s
def rest(s): return s['tick']>=4
def end(s): return 'dead' if s['tick']>=3 else None
case={'sequence':26,'initial_state':{'tick':0,'f':[[15]*64 for _ in range(64)]},
      'actions':[{'name':'ACTION1','data':{}}],'expected_outcome':'dead'}
result=r.replay_cases([case],transition=move,settled=rest,terminal=end)
print(json.dumps(result))
"""
        result = await self.host.execute('compact', source, _Signal())
        self.assertEqual(result.status, 'ok')
        output = json.loads(result.content[0]['text'])['stdout']
        summary = json.loads(output)
        self.assertIn('full_trace_ref', summary)
        self.assertLess(len(output), 8192)
        backtest = summary['backtests'][0]
        self.assertEqual((backtest['expected_outcome'], backtest['predicted_outcome'], backtest['status']),
                         ('dead', 'dead', 'checked'))
        self.assertNotIn('state', backtest['rollout'])
        self.assertNotIn('states', backtest['rollout'])
        path = self.root / 'rollout-evidence' / (summary['full_trace_ref'][7:] + '.json.zlib')
        packed = path.read_bytes()
        self.assertEqual('sha256:' + hashlib.sha256(packed).hexdigest(), summary['full_trace_ref'])
        raw = json.loads(zlib.decompress(packed))
        self.assertGreater(len(repr(raw)), 86000)
        self.assertEqual(raw['backtests'][0]['risk'], backtest['risk'])
        self.assertEqual(raw['backtests'][0]['rollout']['state']['f'][0], [15]*64)
        calls = [json.loads(line) for line in (self.root/'rollout-evidence/calls.jsonl').read_text().splitlines()]
        self.assertEqual([item['operation'] for item in calls], ['replay_cases'])
        self.assertEqual(calls[0]['full_trace_ref'], summary['full_trace_ref'])
        read = await self.host.execute('read', "print(json.dumps(r.read_rollout_trace(result['full_trace_ref'],section=['backtests',0,'rollout','state','f'],start=32,limit=32)))", _Signal())
        page = json.loads(json.loads(read.content[0]['text'])['stdout'])
        self.assertEqual((page['total'], page['next_start']), (64, None))
        self.assertEqual(page['items'], [[15]*64 for _ in range(32)])
        full = await self.host.execute('full', "x=r.replay_cases([case],transition=move,settled=rest,terminal=end,full=True)\nprint(len(x['backtests'][0]['rollout']['states']))", _Signal())
        self.assertEqual(json.loads(full.content[0]['text'])['stdout'].strip(), '4')
        scalar = await self.host.execute('scalar', "print('state' in r.rollout(1,[],transition=lambda s,a:s,settled=lambda s:True,terminal=lambda s:None))", _Signal())
        self.assertEqual(json.loads(scalar.content[0]['text'])['stdout'].strip(), 'False')

