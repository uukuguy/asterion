"""Research entry points are usable without a compulsory note transaction."""
import json
import unittest

from asterion.applications.prime.p7 import prompt
from asterion.applications.prime.p7.research_bridge import ResearchReadServer
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime


class TestAutonomousResearchInterface(unittest.TestCase):
    def test_trusted_current_state_exists_before_first_note(self):
        host = P7ResearchRuntime.__new__(P7ResearchRuntime)
        host._memory_instructions = 'trusted task'
        host.actor_context = lambda: {'notes': None, 'observation_ref': {'sequence': 0}}
        result = host._context_memory(commit=False)
        self.assertEqual(result['version'], 'asterion.prime-context-memory/v2')
        self.assertIsNone(result['revision'])
        self.assertFalse(result['commit'])
        self.assertEqual(json.loads(result['content'].split('\n\n', 1)[1])['observation_ref']['sequence'], 0)

    def test_read_module_import_current_geometry_and_diff_work_without_actions(self):
        frames = [[[4, 4], [1, 0]], [[4, 2], [1, 0]]]
        server = ResearchReadServer(context=lambda: {'observation_ref': {'sequence': 1}},
            frame=lambda seq: frames[seq], history=lambda *args: [], artifact=lambda ref: {})
        self.addCleanup(server.close)
        namespace = {}
        exec(server.start(), namespace)
        self.assertEqual(namespace['frame'](), frames[1])
        self.assertEqual(namespace['current']()['observation_ref']['sequence'], 1)
        self.assertIn('text', namespace['render']())
        self.assertEqual(namespace['diff'](0)['changed_cell_count'], 1)
        self.assertTrue(namespace['geometry']()['components'])
        self.assertEqual(server.dispatch({'method': 'act', 'args': []})['status'], 'rejected')

    def test_prompt_has_executable_import_and_optional_research(self):
        text = prompt.build_autonomous_prompt()
        self.assertIn('import p7_research as r', text)
        self.assertIn('r.render()', text)
        self.assertIn('stop_on_mismatch', text)
        self.assertNotIn('needs_revision=true', text)


class TestOperatorTaskBudget(unittest.TestCase):
    def test_guest_wall_origin_expires_despite_stalled_monotonic_clock(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from asterion.applications.prime.p7 import operator
        wall = [1000.0]
        with patch.object(operator.time, 'monotonic', return_value=100.0), \
             patch.object(operator.time, 'time', side_effect=lambda: wall[0]):
            budget = operator._task_budget({'ASTERION_PRIME_P7_RUN_MODE': 'witness',
                operator._WITNESS_EPOCH_ENV: '1000'}, 1000, 900)
            settlement = operator._settlement_budget(budget)
            signal = operator._WitnessDeadlineSignal(SimpleNamespace(cancelled=False), budget)
            self.assertFalse(signal.cancelled)
            wall[0] = 1900
            self.assertTrue(signal.cancelled)
            self.assertFalse(settlement.expired())
            wall[0] = 2080
            self.assertTrue(settlement.expired())
            wall[0] = 1000
            self.assertTrue(signal.cancelled)

    def test_restricted_budget_rejects_absent_or_expired_wall_origin(self):
        from unittest.mock import patch
        from asterion.applications.prime.p7 import operator
        with patch.object(operator.time, 'monotonic', return_value=100.0), \
             patch.object(operator.time, 'time', return_value=2000.0):
            for value in (None, 'nan', '3000', '1000'):
                env = {'ASTERION_PRIME_P7_RUN_MODE': 'witness'}
                if value is not None:
                    env[operator._WITNESS_EPOCH_ENV] = value
                with self.subTest(value=value), self.assertRaises(operator.P7OperatorError):
                    operator._task_budget(env, 1000, 900)


class TestAutonomousRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_real_kernel_import_then_unpredicted_action_refreshes_trusted_state(self):
        import tempfile
        from pathlib import Path
        from asterion.applications.prime.p7.broker import ArcBroker
        from tests.test_prime_p7_native_broker import _Engine
        from tests.test_prime_p7_research_runtime import _TraceClient, _Signal
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / 'run-autonomous'
        root.mkdir()
        engine = _Engine()
        broker = ArcBroker(engine=engine, action_profile='autonomous')
        broker.bind_history(root.name)
        host = P7ResearchRuntime(broker=broker, trace_client=_TraceClient(), run_root=root,
            run_id=root.name, deadline_seconds=30, event_sink=lambda *_: None,
            learner_profile='autonomous')
        self.addAsyncCleanup(host.close)
        host.set_memory_instructions(prompt.build_autonomous_prompt())
        code = 'import p7_research as r\nassert r.frame() == [[0, 1]]\nprint(r.render())'
        computed = await host.execute('read-first', code, _Signal())
        self.assertEqual(computed.status, 'ok')
        result = host.method_call('execute_plan', {
            'plan_id': 'first-direct-action', 'start': host.current_context()['observation_ref'],
            'steps': [{'action': {'name': 'ACTION1', 'data': {}}}],
        }, _Signal())
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['stop_reason'], 'executed')
        self.assertFalse(result['feedback'][0]['prediction_present'])
        memory = result['context_memory']
        self.assertIsNone(memory['revision'])
        current = json.loads(memory['content'].split('\n\n')[-1])
        self.assertEqual(current['observation_ref']['sequence'], 1)
        # A transport failure after a possible effect remains inspectable.
        from asterion.applications.prime.p7.action_journal import ActionJournal
        engine.action_journal = ActionJournal(root / 'action-journal', {'run_id': root.name})
        def lost_reply(*args):
            raise RuntimeError('engine reply lost')
        engine.step = lost_reply
        uncertain = host.method_call('execute_plan', {
            'plan_id': 'unknown-action', 'start': host.current_context()['observation_ref'],
            'steps': [{'action': {'name': 'ACTION1', 'data': {}}}],
        }, _Signal())
        self.assertEqual(uncertain['stop_reason'], 'environment-result-unknown')
        self.assertTrue(host.current_context()['environment_result_unknown'])
        self.assertTrue(engine.action_journal.has_unresolved)
        self.assertEqual(host.current_context()['observation_ref']['sequence'], 1)

