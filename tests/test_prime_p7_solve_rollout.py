"""Standard solve uses the existing per-action rollout in its actual kernel."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.operator import build_p7_operator_resources
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal


class TestP7StandardSolveRollout(unittest.IsolatedAsyncioTestCase):
    run_mode = "solve"
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'standard-solve'
        self.root.mkdir()
        extension = self.root / 'extension.mjs'
        extension.write_text('export default function extension() {}\n')
        (self.root / 'trace').mkdir()
        self.engine = _Engine()
        self.resources = build_p7_operator_resources(
            environment={'ASTERION_PRIME_P7_RUN_MODE': self.run_mode,
                         'ASTERION_PRIME_PI_AGENT_DIR': str(Path.home() / '.pi/agent'),
                         'ASTERION_PRIME_PROVIDER': 'openai-codex',
                         'ASTERION_PRIME_MODEL': 'gpt-6.1-sol'},
            executable=Path('/usr/bin/pi'), extension_path=extension,
            working_directory=self.root, engine=self.engine,
            private_trace_root=self.root / 'trace')
        self.addAsyncCleanup(self.resources.close)
        self.host = self.resources.host_services['prime.ipython']
        self.assertIs(type(self.host), P7ResearchRuntime)
        self.tools = self.resources.application.services

    async def authorize_probes(self, limit, *, variant='verified'):
        await self.resources.close()
        self.root = self.root.parent / (self.root.name + '-authorized')
        self.root.mkdir()
        (self.root / 'trace').mkdir()
        (self.root / 'extension.mjs').write_text('export default function extension() {}\n')
        self.resources = build_p7_operator_resources(
            environment={'ASTERION_PRIME_P7_RUN_MODE': self.run_mode,
                         'ASTERION_PRIME_P7_HISTORY_VARIANT': variant,
                         'ASTERION_PRIME_PI_AGENT_DIR': str(Path.home() / '.pi/agent'),
                         'ASTERION_PRIME_PROVIDER': 'openai-codex',
                         'ASTERION_PRIME_MODEL': 'gpt-6.1-sol'},
            executable=Path('/usr/bin/pi'), extension_path=self.root / 'extension.mjs',
            working_directory=self.root, engine=self.engine,
            private_trace_root=self.root / 'trace', unknown_probe_action_limit=limit)
        self.addAsyncCleanup(self.resources.close)
        self.host = self.resources.host_services['prime.ipython']
        self.tools = self.resources.application.services

    async def model(self, *, terminal='return None', settled='return state["tick"]>=1', model_id='local-test', risk='return {"findings":[],"coverage":"covered","reason":"tested model"}', name='model', checker=True):
        code = ('import p7_research as r\n'
                'def init(board,ref): return {"tick":0,"sequence":ref["sequence"]}\n'
                'def move(state,action): state["tick"]+=1; return state\n'
                f'def rest(state): {settled}\n'
                f'def end(state): {terminal}\n'
                f'def risk(before,after,action): {risk}\n'
                'r.register_rollout_model(from_frame=init,transition=move,settled=rest,'
                f'terminal=end,risk_check={"risk" if checker else "None"},supported_actions=["ACTION1"],model_id={model_id!r})\n')
        result = await self.host.execute(name, code, _Signal())
        self.assertEqual(result.status, 'ok', result)
        return result

    async def plan(self, count=1, name='plan', **options):
        request = {'plan_id': name, 'start': self.host.current_context()['observation_ref'],
                   'steps': [{'action': {'name': 'ACTION1', 'data': {}}} for _ in range(count)],
                   'stop_on_view_change': False}
        request.update(options)
        self.last_plan_request = request
        result = await asyncio.wait_for(self.tools.call(name, 'execute_plan', request, _Signal()), 15)
        return json.loads(result['output'])

    async def test_single_primitive_registered_conditional_fatal_never_dispatches(self):
        await self.model(risk='return [{"id":"local.contact","type":"conditional_fatal",'
                        '"condition":"actor model condition","evidence":"actor model tick"}]')
        result = await self.plan()
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-conditional-fatal'))
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(result['auto_rollouts'][0]['origin'], 'host_auto')
        self.assertEqual(result['auto_rollouts'][0]['observation_ref']['sequence'], 0)

    async def test_batch_evaluates_latest_frame_before_every_primitive_and_vetoes_fatal_suffix(self):
        await self.model(terminal='return "dead" if state["sequence"]==1 else None')
        result = await self.plan(count=3)
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'model-predicted-death'))
        self.assertEqual(self.engine.calls, ['ACTION1'])
        self.assertEqual([item['observation_ref']['sequence'] for item in result['auto_rollouts']], [0, 1])
        self.assertEqual(len(result['unexecuted_steps']), 2)
        self.assertEqual(result['rollout_accounting']['auto_kernel_cells'], 2)
        self.assertEqual(result['rollout_accounting']['actor_helper_calls'], 0)
        for item in result['auto_rollouts']:
            self.assertEqual(item['origin'], 'host_auto')
            self.assertIn('elapsed_ms', item)

    async def test_actual_feedback_contradicts_registered_model_with_exact_revision_and_refs(self):
        await self.model()
        self.engine.game_over_after = 1
        result = await self.plan()
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'game-over'))
        self.assertEqual(self.engine.calls, ['ACTION1'])
        feedback = result.get('model_feedback', [])
        self.assertEqual(len(feedback), 1, result)
        self.assertEqual(feedback[0]['type'], 'model_mismatch')
        self.assertEqual((feedback[0]['before_observation_ref']['sequence'],
                          feedback[0]['after_observation_ref']['sequence']), (0, 1))
        revision = result['auto_rollouts'][0]['model_revision']
        self.assertEqual(feedback[0]['model_revision'], revision)
        self.assertEqual(self.host._rollouts.model_case_status(revision), 'counterexample_observed')

    async def test_absent_model_records_unassessed_attempt_without_claiming_success(self):
        result = await self.plan()
        assessments = result.get('auto_rollouts', [])
        self.assertEqual(len(assessments), 1, result)
        self.assertEqual((assessments[0]['status'], assessments[0]['risk'], assessments[0]['reason']),
                         ('not_evaluated', 'unassessed', 'model_missing'))
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-coverage-review'))
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(result['rollout_accounting']['auto_evaluated'], 0)


    async def unknown_model(self, **options):
        return await self.model(risk='return {"findings":[],"coverage":"unknown","reason":"contact consequence not modeled","gap_kind":"contact_unmodeled"}', **options)

    @staticmethod
    def probe_options():
        return {'purpose':'probe','goal':'Measure the unsupported contact effect',
                'assumptions':['risk: contact consequence may be fatal',
                               'cost: one paid action; possible death and recovery cost unknown']}

    async def test_unknown_automatic_microstep_pauses_current_action_and_explains_gap(self):
        await self.unknown_model(settled='return state["tick"]>=2')
        result = await self.plan(count=2)
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-coverage-review'))
        self.assertEqual(self.engine.calls, [])
        gaps = result['auto_rollouts'][0]['coverage']['gaps']
        self.assertTrue(any(x['kind']=='contact_unmodeled' and x['phase']=='automatic'
                            and x['tick']==2 and x['action_index']==0 for x in gaps))
        self.assertTrue(result['auto_rollouts'][0]['result_artifact_id'].startswith('sha256:'))
        self.assertEqual(len(result['unexecuted_steps']), 2)

    async def test_batch_keeps_covered_prefix_and_pauses_unknown_second_action(self):
        await self.model(risk='return {"findings":[],"coverage":"unknown" if after["sequence"]==1 else "covered","reason":"contact consequence"}')
        result = await self.plan(count=3)
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'model-coverage-review'))
        self.assertEqual(self.engine.calls, ['ACTION1'])
        self.assertEqual([x['observation_ref']['sequence'] for x in result['auto_rollouts']], [0,1])
        self.assertEqual(len(result['unexecuted_steps']), 2)

    async def test_explicit_probe_requires_prior_review_and_can_only_dispatch_one_matching_step(self):
        await self.unknown_model(settled='return state["tick"]>=2')
        first = await self.plan(name='unreviewed-probe', **self.probe_options())
        self.assertEqual((first['applied_count'], first['stop_reason']), (0, 'model-coverage-review'))
        for name,options,count in (
            ('multi-probe',self.probe_options(),2),
            ('blank-goal',{**self.probe_options(),'goal':''},1),
            ('missing-cost',{**self.probe_options(),'assumptions':['risk: unknown contact']},1)):
            with self.subTest(name=name):
                result=await self.plan(count=count,name=name,**options)
                self.assertEqual((result['applied_count'],result['stop_reason']),(0,'model-coverage-review'))
        # Reading model evidence changes the actor cell, not its registration.
        await self.host.execute('read-after-review', 'print(r.current())', _Signal())
        result = await self.plan(name='reviewed-probe', **self.probe_options())
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-coverage-review'))
        self.assertEqual(self.engine.calls, [])
        self.assertEqual(result['auto_rollouts'][0]['risk'], 'unassessed')
        decision = result['auto_rollouts'][0]['probe_decision']
        self.assertEqual((decision['status'], decision['reason']), ('denied', 'authorization_required'))
        self.assertEqual((decision['limit'], decision['used'], decision['remaining']), (0, 0, 0))
        self.assertIs(decision['safety_verified'], False)
        forged = await self.plan(name='actor-forged-allowance', unknown_probe_action_limit=1, **self.probe_options())
        self.assertEqual(forged['status'], 'rejected')
        self.assertEqual(self.engine.calls, [])

    async def test_probe_cannot_reuse_review_after_registration_or_bypass_new_fatal(self):
        await self.authorize_probes(1)
        await self.unknown_model()
        first=await self.plan(name='review')
        self.assertEqual(first['stop_reason'],'model-coverage-review')
        await self.unknown_model(name='same-source-new-registration')
        changed=await self.plan(name='changed-model-probe',**self.probe_options())
        self.assertEqual((changed['applied_count'],changed['stop_reason']),(0,'model-coverage-review'))
        await self.model(name='fatal-model',risk='return [{"id":"contact","type":"conditional_fatal","condition":"identified branch","evidence":"model transition"}]')
        fatal=await self.plan(name='fatal-probe',**self.probe_options())
        self.assertEqual((fatal['applied_count'],fatal['stop_reason']),(0,'model-conditional-fatal'))
        self.assertEqual(self.engine.calls,[])

    async def test_trusted_allowance_consumes_only_dispatch_and_never_replenishes(self):
        await self.authorize_probes(1)
        await self.unknown_model()
        await self.plan(name='first-review')
        request = {'name': 'allowed-probe', **self.probe_options()}
        result = await self.plan(**request)
        self.assertEqual((result['applied_count'], self.engine.calls), (1, ['ACTION1']))
        decision = result['auto_rollouts'][0]['probe_decision']
        self.assertEqual((decision['limit'], decision['used'], decision['remaining']), (1, 1, 0))
        self.assertEqual(decision['status'], 'operator-authorized-unknown-probe')
        self.assertEqual(decision['authority'], 'application-operator')
        self.assertEqual(decision['accepted_risk'], 'unknown-may-be-fatal')
        self.assertIs(decision['safety_verified'], False)
        self.assertEqual(result['budget']['unknown_probe_policy']['used'], 1)
        # Exact cached request cannot spend or dispatch twice.
        cached = self.host.solver.execute_plan(self.last_plan_request)
        self.assertEqual((cached['applied_count'], cached['stop_reason']), (result['applied_count'], result['stop_reason']))
        self.assertEqual(cached['budget']['unknown_probe_policy'], result['budget']['unknown_probe_policy'])
        self.assertEqual(self.engine.calls, ['ACTION1'])
        await self.plan(name='second-review')
        exhausted = await self.plan(name='exhausted-probe', **self.probe_options())
        self.assertEqual((exhausted['applied_count'], exhausted['stop_reason']), (0, 'model-coverage-review'))
        self.assertEqual(exhausted['auto_rollouts'][0]['probe_decision']['reason'], 'allowance_exhausted')
        self.assertEqual(self.engine.calls, ['ACTION1'])

    async def test_allowance_does_not_override_missing_failed_or_invalid_assessment(self):
        await self.authorize_probes(3)
        for index, (risk, checker) in enumerate(((None, True), ('return []', False), ('raise RuntimeError("checker failed")', True), ('return {"findings":[],"coverage":"invalid","reason":"malformed"}', True))):
            with self.subTest(risk=risk, checker=checker):
                if risk is not None:
                    await self.model(name=f'invalid-model-{index}', risk=risk, checker=checker)
                await self.plan(name=f'unavailable-review-{index}')
                result = await self.plan(name=f'unavailable-probe-{index}', **self.probe_options())
                self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'model-coverage-review'))
                self.assertEqual(result['budget']['unknown_probe_policy']['used'], 0)
        self.assertEqual(self.engine.calls, [])

    async def test_uncertain_dispatch_spends_allowance_and_cached_plan_cannot_respend(self):
        await self.authorize_probes(1)
        await self.unknown_model()
        await self.plan(name='uncertain-review')
        self.engine.raises_on = 1
        result = await self.plan(name='uncertain-probe', **self.probe_options())
        self.assertEqual(result['stop_reason'], 'environment-result-unknown')
        self.assertEqual(result['budget']['unknown_probe_policy']['used'], 1)
        cached = self.host.solver.execute_plan(self.last_plan_request)
        self.assertEqual(cached['stop_reason'], result['stop_reason'])
        self.assertEqual(cached['budget']['unknown_probe_policy'], result['budget']['unknown_probe_policy'])
        self.assertEqual(self.engine.calls, ['ACTION1'])

    async def test_unassessed_probe_death_keeps_classification_if_feedback_recording_fails(self):
        await self.authorize_probes(1)
        await self.unknown_model()
        await self.plan(name='death-review')
        def unavailable(*args, **kwargs):
            raise RuntimeError('feedback unavailable')
        self.host.solver.auto_observe = unavailable
        self.engine.game_over_after = 1
        result = await self.plan(name='death-probe', **self.probe_options())
        feedback = result['model_feedback'][0]
        self.assertEqual((feedback['type'], feedback['evidence_status']),
                         ('death_not_assessed', 'feedback_record_unavailable'))
        self.assertEqual(feedback['coverage'], result['auto_rollouts'][0]['coverage'])
        self.assertEqual(feedback['findings'], result['auto_rollouts'][0]['findings'])

    async def test_reset_does_not_spend_or_replenish_probe_allowance(self):
        await self.authorize_probes(1)
        await self.model()
        self.engine.game_over_after = 1
        await self.plan(name='covered-but-actual-death')
        reset = await self.plan(name='recover', steps=[{'action': {'name': 'RESET', 'data': {}}}])
        self.assertEqual((reset['applied_count'], reset['stop_reason']), (1, 'reset-applied'))
        policy = reset['budget']['unknown_probe_policy']
        self.assertEqual((policy['limit'], policy['used'], policy['remaining']), (1, 0, 1))
        await self.plan(name='missing-after-reset-review')
        missing = await self.plan(name='missing-after-reset-probe', **self.probe_options())
        self.assertEqual((missing['applied_count'], missing['stop_reason']), (0, 'model-coverage-review'))
        self.assertEqual(self.engine.calls, ['ACTION1', 'RESET'])

    async def test_allowance_is_application_owned_and_validated_before_resources_start(self):
        from asterion.applications.prime.p7.operator import P7OperatorError
        for limit in (True, -1, 1.5, '1', self.host._broker.game.action_cap + 1):
            with self.subTest(limit=limit), self.assertRaises(P7OperatorError):
                await self.authorize_probes(limit)
        with self.assertRaises(AttributeError):
            self.host.solver.unknown_probe_action_limit = 100

    async def test_probe_authority_cannot_be_injected_into_disabled_rollout(self):
        from asterion.applications.prime.p7.operator import P7OperatorError
        with self.assertRaises(P7OperatorError):
            await self.authorize_probes(1, variant='legacy')

    async def test_model_reregistration_rechecks_death_case_instead_of_clearing_evidence(self):
        await self.model()
        self.engine.game_over_after=1
        result=await self.plan()
        self.assertEqual(result['model_feedback'][0]['type'],'model_mismatch')
        same=await self.model(name='renamed-unchanged',model_id='renamed')
        summary=json.loads(same.content[0]['text']).get('model_backtest',{})
        self.assertEqual((summary.get('status'),summary.get('case_count')),('contradicted',1))
        self.assertEqual(summary['unresolved_count'],1)
        revised=await self.model(name='corrected-model',terminal='return "dead" if state["tick"]>=1 else None')
        summary=json.loads(revised.content[0]['text']).get('model_backtest',{})
        self.assertEqual((summary.get('status'),summary.get('case_count')),('matched',1))
        self.assertEqual(summary['unresolved_count'],0)
        records=[json.loads(x) for x in (self.root/'rollout-evidence/calls.jsonl').read_text().splitlines()]
        self.assertGreaterEqual(sum(x.get('origin')=='host_backtest' for x in records),2)

    async def test_plan_pixel_mismatch_keeps_claim_provenance_and_unresolved_case(self):
        await self.model()
        result=await self.plan(steps=[{'action':{'name':'ACTION1','data':{}},'expect':{'cells':[{'x':0,'y':0,'value':9}]}}])
        self.assertEqual(result['applied_count'],1)
        feedback=result.get('model_feedback',[])
        self.assertEqual(len(feedback),1,result)
        self.assertEqual(feedback[0]['type'],'plan_expectation_mismatch')
        revised=await self.model(name='new-label-without-board-projection',model_id='new-label')
        summary=json.loads(revised.content[0]['text']).get('model_backtest',{})
        self.assertEqual((summary.get('status'),summary.get('unresolved_count')),('not_comparable',1))



class TestP7StandardSweepRollout(TestP7StandardSolveRollout):
    run_mode = "sweep"


class TestP7StandardRolloutGuidance(unittest.TestCase):
    def test_only_enabled_modern_solve_sweep_receive_minimal_guidance(self):
        from asterion.applications.prime.p7.operator import _append_research_experiment
        from asterion.applications.prime.p7.prompt import P7_AUTO_ROLLOUT_INSTRUCTION
        for mode in ('solve', 'sweep', 'witness', 'autonomy', 'cognition', None):
            for variant in ('verified', 'legacy'):
                with self.subTest(mode=mode, variant=variant):
                    environment = {'ASTERION_PRIME_P7_HISTORY_VARIANT': variant}
                    if mode is not None:
                        environment['ASTERION_PRIME_P7_RUN_MODE'] = mode
                    text = _append_research_experiment('selected application guidance', environment)
                    if variant == 'verified' and mode in ('solve', 'sweep', None):
                        self.assertEqual(text, 'selected application guidance\n\n' + P7_AUTO_ROLLOUT_INSTRUCTION)
                    else:
                        self.assertEqual(text, 'selected application guidance')


class TestP7UnknownProbePolicy(unittest.TestCase):
    def test_malformed_assessment_cannot_be_treated_as_valid_exploration(self):
        from asterion.applications.prime.p7.rollout import rollout
        from asterion.applications.prime.p7.solver import Solver
        result = rollout({'tick': 0}, [{'name': 'ACTION1', 'data': {}}],
                         transition=lambda state, action: {'tick': 1},
                         settled=lambda state: True, terminal=lambda state: None,
                         supported_actions=['ACTION1'],
                         risk_check=lambda before, after, action: {
                             'findings': [], 'coverage': 'unknown', 'reason': 'contact unknown'})
        assessment = {'status': 'evaluated', 'risk': result['risk']['status'],
                      'coverage': result['risk']['coverage'],
                      'model_revision': {'generation': '1', 'registration_id': 1}}
        self.assertTrue(Solver._probe_eligible_assessment(assessment))
        for field, value in (('action_coverage', []), ('gaps_omitted', False),
                             ('checker_supplied', 1), ('errors', None), ('gaps', [])):
            with self.subTest(field=field):
                malformed = copy.deepcopy(assessment)
                malformed['coverage'][field] = value
                self.assertFalse(Solver._probe_eligible_assessment(malformed))
        for field in ('kind', 'phase', 'reason'):
            with self.subTest(gap_field=field):
                malformed = copy.deepcopy(assessment)
                malformed['coverage']['gaps'][0][field] = []
                self.assertFalse(Solver._probe_eligible_assessment(malformed))
