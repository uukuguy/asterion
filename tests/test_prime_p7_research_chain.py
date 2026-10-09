"""Private macro research records reuse real archived computation and feedback."""
import json
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.console_events import ConsoleEventWriter, read_console_events
from asterion.applications.prime.p7.research_runtime import P7ResearchRuntime
from tests.test_prime_p7_native_broker import _Engine
from tests.test_prime_p7_research_runtime import _Signal, _TraceClient


class TestP7ResearchChain(unittest.IsolatedAsyncioTestCase):
    async def test_notes_program_counterexample_and_revision_are_private_real_evidence(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run_id = 'chain-story'
        root = Path(temporary.name) / run_id
        root.mkdir()
        broker = ArcBroker(engine=_Engine())
        broker.bind_history(run_id)
        writer = ConsoleEventWriter(root, run_id, broker.game.game_id)
        host = P7ResearchRuntime(broker=broker, trace_client=_TraceClient(), run_root=root,
            run_id=run_id, deadline_seconds=30, event_sink=writer.append,
            learner_profile='autonomous')
        self.addAsyncCleanup(host.close)
        current = host.current_context()
        note = host.method_call('workspace', {'op': 'notes',
            'base_revision': current['workspace_revision'], 'observation_ref': current['observation_ref'],
            'text': 'private-hypothesis-sentinel: movement may increment one.'}, _Signal())
        self.assertEqual(note['status'], 'noted')
        computed = await host.execute('prediction-program',
            "print('private-output-sentinel'); predicted = 9", _Signal())
        self.assertEqual(computed.status, 'ok')
        current = host.current_context()
        plan = {'plan_id': 'test-hypothesis', 'start': current['observation_ref'],
                'steps': [{'action': {'name': 'ACTION1', 'data': {}},
                           'expect': {'cells': [{'x': 0, 'y': 0, 'value': 9}]}}]}
        result = host.method_call('execute_plan', plan, _Signal())
        self.assertEqual(result['stop_reason'], 'prediction-mismatch')
        current = host.current_context()
        revised = host.method_call('workspace', {'op': 'notes',
            'base_revision': current['workspace_revision'], 'observation_ref': current['observation_ref'],
            'text': 'private-revision-sentinel: the submitted prediction was contradicted.'}, _Signal())
        self.assertEqual(revised['status'], 'noted')
        path = root / 'research' / 'research-chain.json'
        self.assertTrue(path.is_file(), 'passive macro research record is missing')
        chain = json.loads(path.read_text())
        records = chain['records']
        self.assertEqual([r['kind'] for r in records], ['notes', 'computation', 'experiment', 'notes'])
        self.assertEqual([r['origin'] for r in records],
                         ['model_statement', 'behavioral_evidence', 'behavioral_evidence', 'model_statement'])
        for record in records:
            self.assertEqual(record['causal_support'], 'unknown')
            self.assertEqual(record['interpretation'], 'unclassified')
            for reference in record['evidence_refs']:
                if 'path' in reference:
                    source = root / reference['path']
                    self.assertTrue(source.is_file())
        computation = records[1]
        cell_ref = next(ref for ref in computation['evidence_refs'] if ref['kind'] == 'cell')
        cell = json.loads((root / cell_ref['path']).read_text())
        self.assertIn('private-output-sentinel', cell['output'])
        self.assertTrue(cell_ref['output_available'])
        self.assertNotIn('private-output-sentinel', json.dumps(chain))
        experiment = records[2]
        self.assertEqual(experiment['statement']['submitted_plan'], plan)
        self.assertEqual(experiment['statement']['feedback'][0]['counterexample_sequence'], 1)
        self.assertEqual(experiment['statement']['feedback'][0]['observation_ref'], current['observation_ref'])
        self.assertEqual(records[3]['links'][0]['relation'], 'observed_after')
        public = read_console_events(root, run_id, broker.game.game_id)
        self.assertNotIn('private-hypothesis-sentinel', json.dumps(public))
        self.assertNotIn('private-output-sentinel', json.dumps(public))
        before_count = len(records)
        rejected = host.method_call('workspace', {'op': 'notes',
            'base_revision': 'sha256:' + '0' * 64, 'observation_ref': current['observation_ref'],
            'text': 'rejected-private-note'}, _Signal())
        self.assertEqual(rejected['status'], 'rejected')
        duplicate = host.method_call('execute_plan', plan, _Signal())
        self.assertEqual(duplicate['applied_count'], 1)
        self.assertEqual(len(json.loads(path.read_text())['records']), before_count)
        self.assertEqual(len(broker.journal), 1)


class TestP7ResearchChainBoundary(unittest.TestCase):
    def test_unfinished_computation_keeps_unknown_completion_and_real_archive_ref(self):
        from types import SimpleNamespace
        from asterion.agents.prime.cell_history import CellHistory
        from asterion.applications.prime.p7.research_chain import P7ResearchChain

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = SimpleNamespace(root=root / 'research' / 'scope', scope={'run_id': 'boundary'})
            chain = P7ResearchChain(run_root=root, workspace=workspace)
            history = CellHistory(root / 'research-kernel', source_limit=1024, output_limit=1024,
                                  max_records=16, max_bytes=1024 * 1024)
            kernel = SimpleNamespace(cell_history=history.history)
            for index, status in enumerate(('pending', 'lost', 'uncertain')):
                with self.subTest(status=status):
                    cell_id = history.begin('generation', 'call-' + str(index), 'private_program = 1')
                    if status != 'pending':
                        history.finish(cell_id, status)
                    chain.computation(kernel, index)
                    record = json.loads((root / 'research' / 'research-chain.json').read_text())['records'][-1]
                    self.assertEqual(record['statement']['completion'], 'unknown')
                    self.assertFalse(record['evidence_refs'][0]['output_available'])
                    self.assertEqual(record['evidence_refs'][0]['cell_id'], cell_id)
                    self.assertEqual(record['causal_support'], 'unknown')

    def test_unknown_environment_result_never_gets_counterexample_or_transition_evidence(self):
        from types import SimpleNamespace
        from asterion.applications.prime.p7.research_chain import P7ResearchChain

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            chain = P7ResearchChain(run_root=root, workspace=SimpleNamespace(
                root=root / 'research' / 'scope', scope={'run_id': 'boundary'}))
            reference = {'run_id': 'boundary', 'attempt_id': 'boundary', 'sequence': 0,
                         'level': 1, 'observation_sha256': 'sha256:' + '0' * 64}
            plan = {'plan_id': 'unknown-action', 'start': reference, 'steps': []}
            chain.experiment(plan, {'status': 'recorded', 'observation_ref': reference,
                'stop_reason': 'environment-result-unknown', 'applied_count': 0,
                'feedback': [{'actual': None, 'counterexample_sequence': None}]}, [])
            record = json.loads((root / 'research' / 'research-chain.json').read_text())['records'][0]
            self.assertFalse(record['statement']['outcome_known'])
            self.assertIsNone(record['statement']['feedback'][0]['actual'])
            self.assertFalse(any(ref['kind'] == 'transition' for ref in record['evidence_refs']))


if __name__ == '__main__':
    unittest.main()
