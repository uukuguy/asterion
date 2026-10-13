"""Standard solve uses the existing per-action rollout in its actual kernel."""
import asyncio
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

    async def model(self, *, terminal='return None', risk='return {"findings":[],"coverage":"covered","reason":"tested model"}', name='model'):
        code = ('import p7_research as r\n'
                'def init(board,ref): return {"tick":0,"sequence":ref["sequence"]}\n'
                'def move(state,action): state["tick"]+=1; return state\n'
                'def rest(state): return state["tick"]>=1\n'
                f'def end(state): {terminal}\n'
                f'def risk(before,after,action): {risk}\n'
                'r.register_rollout_model(from_frame=init,transition=move,settled=rest,'
                'terminal=end,risk_check=risk,supported_actions=["ACTION1"],model_id="local-test")\n')
        result = await self.host.execute(name, code, _Signal())
        self.assertEqual(result.status, 'ok', result)

    async def plan(self, count=1, name='plan'):
        request = {'plan_id': name, 'start': self.host.current_context()['observation_ref'],
                   'steps': [{'action': {'name': 'ACTION1', 'data': {}}} for _ in range(count)],
                   'stop_on_view_change': False}
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
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['rollout_accounting']['auto_evaluated'], 0)


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
