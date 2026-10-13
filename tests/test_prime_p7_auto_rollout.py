"""Provider-free automatic evaluation in the existing P7 computation kernel."""
import asyncio
import builtins
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zlib

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from asterion.applications.prime.p7 import rollout as rollout_helpers
from asterion.applications.prime.p7.rollout_runtime import KERNEL_SOURCE, RolloutRuntime
from asterion.applications.prime.p7.tool_dispatch import P7ToolDispatch
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal, _TraceClient


class TestRetainedScopeBuiltins(unittest.TestCase):
    # Task51 cells 229/280/332: from_down's widened grid and reg20 ff.
    # Only the initializer is replayed; no historical transition/game runs.
    initializer = """
gravity=1
def from_down(f,ref):
 f=f.tolist() if hasattr(f,'tolist') else f
 ps=[(x,y) for y,row in enumerate(f) for x,v in enumerate(row) if v==9];py=round(sum(y for x,y in ps)/len(ps));ox=15;oy=py%6
 g=[[f[y][x] for x in range(15,58,6)] for y in range(oy,63,6)]
 return {'p':[round((sum(x for x,y in ps)/len(ps)-15)/6),(py-oy)//6],'g':g,'unknown':False,'done':False,'oy':oy}
def ff(f,ref):
 s=from_down(f,ref);s['dir']=-1 if ref['sequence']==123 else gravity
 f=f.tolist() if hasattr(f,'tolist') else f
 for j,row in enumerate(s['g']):
  for c,v in enumerate(row):
   x=15+6*c;y=s['oy']+6*j
   if v==10 and any(f[yy][xx]==12 for yy in range(max(0,y-2),min(63,y+3)) for xx in range(x-2,x+3)):row[c]=12
 x,y=s['p'];s['g'][y][x]=10
 return s
"""

    def setUp(self):
        self.reference = {'run_id':'run','attempt_id':'run','level':5,'sequence':143}
        self.namespace = {**vars(rollout_helpers), '_json':json,
                          '__builtins__':vars(builtins).copy(),
                          'current':lambda: {'observation_ref':self.reference},
                          'replay_deaths':rollout_helpers.replay_cases}
        exec(KERNEL_SOURCE, self.namespace)
        exec(self.initializer, self.namespace)
        self.frame = [[10]*64 for _ in range(64)]
        self.frame[38][15] = 9
        self.frame[20][15] = 12

    def test_archived_initializer_freezes_state_and_preserves_risk_applicability(self):
        from asterion.applications.prime.p7.score import digest
        namespace = self.namespace
        action = {'name':'ACTION4','data':{}}
        namespace['register_rollout_model'](from_frame=namespace['ff'],
            transition=lambda state, action: {**state,'done':True},
            settled=lambda state: False, terminal=lambda state: 'dead' if state['done'] else None,
            supported_actions=['ACTION4'])
        boundary = namespace['_rollout_boundary'](namespace['current']())
        assessment, result = namespace['_evaluate_registered'](self.frame,self.reference,action,boundary)
        self.assertEqual(assessment['risk'], 'predicted_death')
        extractor_id = assessment['scope_extractor_id']
        self.assertNotIn('unavailable', extractor_id)
        grid = [[10]*8 for _ in range(11)]
        grid[3][0] = 12
        expected_state = {'p':[0,6],'g':grid,'unknown':False,'done':False,'oy':2,'dir':1}
        self.assertEqual(result['initial_state_sha256'], digest(expected_state))
        with tempfile.TemporaryDirectory() as directory:
            runtime = RolloutRuntime(SimpleNamespace(kernel=SimpleNamespace(generation='g')), Path(directory))
            runtime._retain_fatal(assessment,self.reference,action,digest(self.frame),
                                  {'generation':'g','registration_id':1},'sha256:'+'a'*64,'actor')
            original_witnesses = json.dumps(runtime.retained_fatal_risks, sort_keys=True)
            changed_frame = json.loads(json.dumps(self.frame))
            changed_frame[0][0] = 5
            changed_state = json.loads(json.dumps(changed_frame))
            changed_state[38][15], changed_state[38][21] = 10, 9
            for frame, mutation, expected in (
                    (changed_frame,None,'predicted_death'),
                    (changed_state,None,'no_identified_fatal'),
                    (changed_frame,"gravity=-1",'unavailable'),
                    (changed_frame,"def from_down(f,ref): return {}",'unavailable'),
                    (changed_frame,"__builtins__['round']=lambda value: 0",'unavailable')):
                with self.subTest(mutation=mutation, expected=expected):
                    if mutation:
                        exec(mutation, namespace)
                    scope = namespace['_rollout_extract_retained_scope'](extractor_id,frame,self.reference)
                    current = {'risk':'no_identified_fatal','frame_sha256':digest(frame),
                               '_retained_scope_assessments':{extractor_id:scope}}
                    runtime._apply_retained_fatal(current,self.reference,action)
                    self.assertEqual(current['risk'], 'no_identified_fatal' if expected == 'unavailable' else expected)
                    self.assertEqual(current.get('hard_stop'), 'risk_applicability_unavailable' if expected == 'unavailable' else None)
                    if expected == 'predicted_death':
                        self.assertEqual(current['retained_fatal_risks'][0]['match'], 'initial_state')
                    self.assertEqual(json.dumps(runtime.retained_fatal_risks, sort_keys=True), original_witnesses)
                    exec(self.initializer, namespace)
                    namespace['__builtins__']['round'] = builtins.round

    def test_scope_rejects_impostor_and_unsafe_builtins(self):
        for name in ('hasattr','round','eval','exec','open','__import__'):
            with self.subTest(name=name):
                if name in ('hasattr','round'):
                    self.namespace['__builtins__'][name] = lambda *args: None
                exec(f'def probe(frame,ref): return {name}(frame)', self.namespace)
                with self.assertRaisesRegex(ValueError, 'scope dependency unsupported'):
                    self.namespace['_rollout_scope_fingerprint'](self.namespace['probe'])

    def test_scope_rejects_external_nonlocal_mutation(self):
        for mutation in ('value+=1','del value'):
            with self.subTest(mutation=mutation):
                exec(f"""
def make_initializer():
 value=1
 def initializer(frame,ref):
  nonlocal value
  {mutation}
  return {{'value':1}}
 return initializer
""", self.namespace)
                with self.assertRaisesRegex(ValueError, 'scope dependency unsupported'):
                    self.namespace['_rollout_scope_fingerprint'](self.namespace['make_initializer']())


class TestRolloutFeedback(unittest.TestCase):
    def test_retained_witness_generation_and_canonical_action_boundaries(self):
        from asterion.applications.prime.p7.score import digest
        with tempfile.TemporaryDirectory() as directory:
            runtime = RolloutRuntime(SimpleNamespace(kernel=SimpleNamespace(generation='new')), Path(directory))
            action = {'name':'ACTION6','data':{'x':21,'y':33}}
            reference = {'run_id':'run','level':2,'sequence':43}
            frame_hash = digest([[0]])
            runtime._retain_fatal({'risk':'conditional_fatal','findings':[{'evidence':'original'}],
                                   'initial_state_sha256':digest({'tick':0}),'scope_extractor_id':'1:old'},
                                  reference,action,frame_hash,
                                  {'generation':'old','registration_id':1},'sha256:'+'a'*64,'actor')
            for ref, candidate, frame, expected in (
                    ({**reference,'sequence':45}, {'data':{'y':33,'x':21},'name':'ACTION6'}, [[1]], 'unavailable'),
                    (reference, action, [[0]], 'fatal'),
                    ({**reference,'level':3}, action, [[1]], None),
                    ({**reference,'run_id':'other'}, action, [[1]], None),
                    (reference, {'name':'ACTION6','data':{'x':22,'y':33}}, [[1]], None)):
                with self.subTest(ref=ref,candidate=candidate,frame=frame):
                    result = {'risk':'unassessed','frame_sha256':digest(frame),
                              '_retained_scope_assessments':{'1:old':{'status':'available','initial_state_sha256':digest({'tick':0})}}}
                    runtime._apply_retained_fatal(result,ref,candidate)
                    self.assertEqual(result.get('hard_stop'), 'risk_applicability_unavailable' if expected == 'unavailable' else None)
                    self.assertEqual(result['risk'], 'conditional_fatal' if expected == 'fatal' else 'unassessed')
            self.assertEqual(len(runtime.retained_fatal_risks), 1)

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
            "print(r.register_rollout_model(from_frame=init,transition=move,settled=rest,terminal=end,risk_check=risk,supported_actions=['ACTION1','ACTION2']))\n"
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
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-coverage-review'), result)
        self.assertEqual(result['rollout_accounting']['auto_evaluated'], 0)

    async def test_conditional_fatal_stops_without_dispatch(self):
        await self.model('return None', "return [{'id':'local.assumption','type':'conditional_fatal','condition':'hypothesis','evidence':'model tick'}]")
        result = await self.plan()
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-conditional-fatal'))
        self.assertEqual(self.engine.calls, [])

    async def retained_model(self, *, fatal=False, initializer="return {'tick':0,'private':'retained-state-sentinel'}", extra='', covered=True, terminal='return None'):
        finding = "[{'id':'prior.contact','type':'conditional_fatal','condition':'contact hypothesis','evidence':'original witness'}]" if fatal else '[]'
        source = ("import p7_research as r\nimport json\n"
                  f"def init(board,ref): {initializer}\n"
                  "def move(state,action): state['tick']+=1; return state\n"
                  "def rest(state): return state['tick']>=1\n"
                  f"def end(state): {terminal}\n"
                  f"def risk(before,after,action): return {finding}\n"
                  f"r.register_rollout_model(from_frame=init,transition=move,settled=rest,terminal=end,risk_check=risk,supported_actions={['ACTION1','ACTION2'] if covered else None!r})\n") + extra
        return await self.host.execute('retained-model-' + str(self.host._rollouts.actor_cell_count), source, _Signal())

    async def test_retained_actor_fatal_survives_new_schema_and_different_frame(self):
        actor = await self.retained_model(fatal=True, extra="print(json.dumps(r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})))\n")
        summary = json.loads(json.loads(actor.content[0]['text'])['stdout'])
        self.assertNotIn('retained-state-sentinel', json.dumps(summary))
        first_ref = self.host.current_context()['observation_ref']
        first_revision = self.host._rollouts.actor_calls[0]['model_revision']
        # A different action changes the public frame and must remain allowed.
        await self.retained_model(initializer="return {'tick':0,'new_schema':True}")
        other = await self.plan('other-action', ('ACTION2',))
        self.assertEqual(other['applied_count'], 1, other)
        result = await self.plan('retained-action')
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-conditional-fatal'))
        assessment = result['auto_rollouts'][0]
        witness = assessment['retained_fatal_risks'][0]
        self.assertEqual(witness['observation_ref'], first_ref)
        self.assertEqual(witness['model_revision'], first_revision)
        self.assertEqual(witness['full_trace_ref'], summary['full_trace_ref'])
        self.assertEqual(witness['findings'][0]['evidence'], 'original witness')
        self.assertEqual(witness['match'], 'initial_state')
        self.assertRegex(summary['initial_state_sha256'], r'^sha256:[0-9a-f]{64}$')
        self.assertNotIn('retained-state-sentinel', json.dumps(result))
        self.assertEqual(self.engine.calls, ['ACTION2'])

    async def test_changed_scope_dependency_pauses_only_affected_action(self):
        await self.retained_model(fatal=True,
            initializer="return {'tick':0,'dep':scope_value}",
            extra="scope_value=1\nr.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\n")
        await self.retained_model(extra='scope_value=2\n')
        self.assertEqual((await self.plan('scope-other', ('ACTION2',)))['applied_count'], 1)
        result = await self.plan('scope-unavailable')
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'risk-applicability-unavailable'))
        self.assertEqual(result['auto_rollouts'][0]['hard_stop'], 'risk_applicability_unavailable')
        self.assertEqual(result['auto_rollouts'][0]['risk'], 'no_identified_fatal')
        self.assertEqual(self.engine.calls, ['ACTION2'])

    async def test_retained_scope_different_initial_state_does_not_block(self):
        await self.retained_model(fatal=True,
            initializer="return {'tick':0,'pixel':board[0][0]}",
            extra="r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\n")
        await self.retained_model()
        self.assertEqual((await self.plan('different-state', ('ACTION2',)))['applied_count'], 1)
        result = await self.plan('different-state-action')
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(len(self.host._rollouts.retained_fatal_risks), 1)

    async def test_host_predicted_death_is_retained_after_unknown_revision(self):
        await self.retained_model(terminal="return 'dead' if state['tick'] else None")
        original = await self.plan('host-fatal')
        self.assertEqual(original['stop_reason'], 'model-predicted-death')
        original_revision = original['auto_rollouts'][0]['model_revision']
        await self.retained_model(covered=False)
        other = await self.plan('host-other', ('ACTION2',))
        self.assertEqual((other['applied_count'], other['stop_reason']), (0, 'model-coverage-review'))
        result = await self.plan('host-retained')
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-predicted-death'))
        assessment = result['auto_rollouts'][0]
        self.assertEqual(assessment['model_risk'], 'unassessed')
        self.assertEqual(assessment['retained_fatal_risks'][0]['model_revision'], original_revision)
        self.assertEqual(len(self.host._rollouts.retained_fatal_risks), 1)

    async def test_registration_invalidation_keeps_retained_scope_and_deduplicates(self):
        await self.retained_model(fatal=True, extra="r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\n")
        await self.plan('same-fatal')
        self.assertEqual(len(self.host._rollouts.retained_fatal_risks), 1)
        await self.host._rollouts.invalidate(_Signal())
        await self.retained_model()
        self.assertEqual((await self.plan('after-invalidation-other', ('ACTION2',)))['applied_count'], 1)
        result = await self.plan('after-invalidation-retained')
        self.assertEqual(result['stop_reason'], 'model-conditional-fatal')

    async def test_unbound_helper_fatal_does_not_create_host_witness(self):
        await self.retained_model(fatal=True, extra="r.rollout(init(r.frame(),r.current()['observation_ref']),[{'name':'ACTION1','data':{}}],transition=move,settled=rest,terminal=end,risk_check=risk)\n")
        self.assertEqual(self.host._rollouts.retained_fatal_risks, [])
        await self.retained_model()
        self.assertEqual((await self.plan('unbound'))['applied_count'], 1)

    async def test_scope_extractor_loss_pauses_but_exact_frame_still_blocks(self):
        await self.retained_model(fatal=True, extra="r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\n")
        await self.retained_model(extra='r._rollout_scope_extractors.clear()\n')
        same = await self.plan('lost-extractor-same-frame')
        self.assertEqual(same['stop_reason'], 'model-conditional-fatal')
        self.assertEqual(same['auto_rollouts'][0]['retained_fatal_risks'][0]['match'], 'public_frame')
        self.assertEqual((await self.plan('lost-extractor-other', ('ACTION2',)))['applied_count'], 1)
        changed = await self.plan('lost-extractor-changed-frame')
        self.assertEqual(changed['stop_reason'], 'risk-applicability-unavailable')
        self.assertEqual(self.engine.calls, ['ACTION2'])

    async def test_same_pixels_with_different_reference_state_does_not_match(self):
        observe = self.engine.observe
        def same_pixels():
            observation = observe()
            observation['frame'] = [[[0, 1]]]
            return observation
        self.engine.observe = same_pixels
        await self.retained_model(fatal=True,
            initializer="return {'tick':0,'sequence':ref['sequence']}",
            extra="r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\n")
        await self.retained_model()
        self.assertEqual((await self.plan('same-pixels-other', ('ACTION2',)))['applied_count'], 1)
        result = await self.plan('same-pixels-different-reference')
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(self.engine.calls, ['ACTION2', 'ACTION1'])
        self.assertEqual(len(self.host._rollouts.retained_fatal_risks), 1)

    async def test_predicted_death_frame_fallback_is_only_conditional_fatal(self):
        await self.retained_model(terminal="return 'dead' if state['tick'] else None")
        self.assertEqual((await self.plan('original-prediction'))['stop_reason'], 'model-predicted-death')
        await self.retained_model(extra='r._rollout_scope_extractors.clear()\n')
        result = await self.plan('prediction-frame-fallback')
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-conditional-fatal'))
        witness = result['auto_rollouts'][0]['retained_fatal_risks'][0]
        self.assertEqual((witness['risk'], witness['match']), ('predicted_death', 'public_frame'))
        self.assertEqual(self.engine.calls, [])

    async def test_retained_scope_supports_nested_comprehension_builtins(self):
        await self.retained_model(fatal=True,
            initializer="return {'tick':0,'pixels':[min(row[1:]) for row in board if len(row)]}",
            extra="r.evaluate_action(r.frame(),r.current()['observation_ref'],{'name':'ACTION1','data':{}})\n")
        await self.retained_model()
        self.assertEqual((await self.plan('comprehension-other', ('ACTION2',)))['applied_count'], 1)
        result = await self.plan('comprehension-retained')
        self.assertEqual(result['stop_reason'], 'model-conditional-fatal')

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

