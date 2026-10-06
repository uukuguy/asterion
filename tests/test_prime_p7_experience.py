"""Failed research can teach without acquiring route or execution authority."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.private_trace import trace_identities_for
from asterion.applications.prime.p7.research import ResearchWorkspace
from asterion.applications.prime.p7.score import digest
from tests.test_prime_p7_solver import _Kernel, draft


class TestExperience(unittest.TestCase):
    def test_legacy_animation_bypasses_metadata_totals_and_reads_only_requested_page(self):
        from asterion.agents.prime.trace import _entry_digest
        from asterion.applications.prime.p7.console_events import SCHEMA
        from asterion.applications.prime.p7.observation_state import ObservationState
        run, _ = self.source()
        before = dict(frame=[[[0] * 64 for _ in range(64)]], available_actions=['ACTION1'],
                      levels_completed=0, win_levels=2, state='NOT_FINISHED')
        after = {**before, 'frame': [[[1] * 64 for _ in range(64)] for _ in range(95)]}
        before_hash = digest(ObservationState.from_observation(before).to_projection())
        from asterion.applications.prime.p7.broker import _snapshot_observation, _observation_digest
        after_hash = _observation_digest(_snapshot_observation(after, win_levels=2))
        payload = dict(sequence=1, action='ACTION1', before_sha256=before_hash, after_sha256=after_hash,
                       levels_completed=0, data={})
        trace = run / 'trace' / 'prime-trace.jsonl'
        previous = json.loads(trace.read_text().splitlines()[-1])
        identities = trace_identities_for('gpt-6.1-sol')
        row = dict(sequence=2, kind='arc.action', identities=dict(identities), payload=payload,
                   previous_sha256=previous['sha256'])
        row['sha256'] = _entry_digest(2, 'arc.action', identities, payload, previous['sha256'])
        with trace.open('a') as stream:
            stream.write(json.dumps(row) + '\n')
        events = [('observation', dict(source_action_sequence=0, observation_sha256=before_hash, observation=before)),
                  ('action', {**payload, 'decision_id': None}),
                  ('observation', dict(source_action_sequence=1, observation_sha256=after_hash, observation=after))]
        path = run / 'console-events.jsonl'
        path.write_text(''.join(json.dumps(dict(schema=SCHEMA, run_id=run.name, game_id='test-1',
                       sequence=i, kind=kind, payload=value)) + '\n' for i, (kind, value) in enumerate(events, 1)))
        with patch('asterion.applications.prime.p7.experience._MAX_FILE', 4096), patch('asterion.applications.prime.p7.experience._MAX_TOTAL', 32768):
            bundle = self.load()
        self.assertEqual(bundle.context()['available_count'], 1)
        stable = bundle.read(run.name, 'frame', start=1)['items'][0]
        self.assertEqual(len(stable['observation']['frame']), 1)
        self.assertEqual(stable['animation_ref']['frame_count'], 95)
        page = bundle.read(run.name, 'animation', artifact_id=after_hash, start=94, limit=1)['items'][0]
        self.assertEqual(page['start'], 94)
        self.assertEqual(len(page['frames']), 1)
        self.assertEqual(page['frames'][0][0][0], 1)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def source(self, name='failed-001', model='gpt-6.1-sol', game='test-1', seed=0):
        run = self.root / name
        run.mkdir()
        (run / 'trace').mkdir()
        recorder = PrimeTraceRecorder(run / 'trace')
        recorder.append('arc.usage.reported', trace_identities_for(model),
                        {'input_tokens': 1, 'output_tokens': 1})
        scope = dict(game_id=game, seed=seed, win_levels=2, run_id=name, attempt_id=name)
        workspace = ResearchWorkspace(root=run / 'research', scope=scope, kernel=_Kernel())
        value = draft()
        value['correction']['changed'] = ['Repeated ACTION1 did not open the gate.']
        value['correction']['counterexample_sequence'] = 0
        workspace.revise({'base_revision': workspace.revision,
                          **{k: value[k] for k in ('worldmap', 'task', 'evidence_sequences', 'correction')}}, latest=0)
        return run, workspace

    def load(self):
        from asterion.applications.prime.p7.experience import load_experience
        return load_experience(self.root, game_id='test-1', seed=0, win_levels=2,
                               model_id='gpt-6.1-sol', current_run_id='current')

    def test_unsealed_zero_action_without_finalizer_loads_correction(self):
        self.source()
        bundle = self.load()
        context = bundle.context()
        self.assertEqual(context['available_count'], 1)
        self.assertEqual(context['sources'][0]['trace_status'], 'unsealed_prefix')
        self.assertIn('did not open', context['latest']['correction']['changed'][0])
        self.assertTrue(context['advisory_only'])
        self.assertNotIn('workspace_revision', context)
        self.assertEqual(bundle.read('failed-001', 'history')['items'], [])
        context['latest']['correction']['changed'].clear()
        self.assertTrue(bundle.context()['latest']['correction']['changed'])

    def test_wrong_identity_and_corrupt_revision_do_not_enter_pool(self):
        self.source('wrong-model', model='deepseek-v4-flash')
        self.source('wrong-game', game='other-1')
        self.source('wrong-seed', seed=1)
        _, workspace = self.source('corrupt')
        path = workspace.root / 'revisions' / (workspace.revision[7:] + '.json')
        path.write_text(path.read_text().replace('Repeated', 'Different'))
        self.assertEqual(self.load().context()['available_count'], 0)

    def test_torn_tail_is_usable_but_internal_chain_tamper_is_rejected(self):
        run, _ = self.source()
        path = run / 'trace' / 'prime-trace.jsonl'
        original = path.read_bytes()
        path.write_bytes(original + b'{"sequence":')
        self.assertEqual(self.load().context()['available_count'], 1)
        path.write_bytes(original.replace(b'input_tokens', b'wrong_tokens') + b'\n')
        self.assertEqual(self.load().context()['available_count'], 0)

    def test_latest_failure_not_tied_to_success_prefix_and_reads_are_audited(self):
        self.source('failed-001')
        self.source('failed-002')
        bundle = self.load()
        current = self.root / 'current'
        current.mkdir()
        bundle.bind(current)
        self.assertEqual(bundle.context()['latest']['source_run_id'], 'failed-002')
        bundle.mark_loaded()
        bundle.read('failed-001', 'research')
        bundle.record_revision('sha256:' + 'a' * 64, {'changed': ['new correction'], 'retained': []}, [])
        audit = json.loads((current / 'research' / 'experience-consumption.json').read_text())
        self.assertTrue(audit['loaded'])
        self.assertEqual(audit['reads'][0]['source_run_id'], 'failed-001')
        self.assertEqual(audit['revisions'][0]['workspace_revision'], 'sha256:' + 'a' * 64)
        self.assertFalse(audit['revisions'][0]['program_reused'])

    def test_cell_source_is_inert_and_unknown_completion_is_preserved(self):
        from asterion.applications.prime.p7.experience import CellArchive
        run, _ = self.source()
        archive = CellArchive(run)
        source = "raise RuntimeError('never execute historical cells')"
        archive.started('cell-1', 'generation-1', source)
        archive.started('call_2|fc_abc', 'generation-1', 'result = 42')
        archive.finished('call_2|fc_abc', 'generation-1', 'error', [])
        result = self.load().read('failed-001', 'cells')
        self.assertEqual(result['items'][0]['source'], source)
        self.assertEqual(result['items'][0]['status'], 'unknown')
        self.assertEqual(result['items'][1]['status'], 'error')
        self.assertTrue(result['inert'])

    def test_source_read_stays_frozen_and_unselected_source_rejected(self):
        run, workspace = self.source()
        bundle = self.load()
        current = workspace.root / 'current.json'
        current.write_text(json.dumps({'scope': workspace.scope, 'revision': digest({})}))
        self.assertEqual(bundle.read('failed-001', 'research')['items'][0]['source_revision'], workspace.revision)
        with self.assertRaises(ValueError):
            bundle.read('../failed-001', 'cells')
        path = workspace.root / 'revisions' / (workspace.revision[7:] + '.json')
        path.write_text('{}')
        with self.assertRaises(ValueError):
            bundle.read('failed-001', 'research')

    def test_omitted_cells_remain_visible_without_summary_and_frozen(self):
        from asterion.applications.prime.p7.experience import CellArchive
        run, _ = self.source()
        archive = CellArchive(run)
        archive.started('too-large', 'generation-1', 'x' * (16 * 1024 + 1))
        bundle = self.load()
        prior = bundle.context()['latest']
        self.assertEqual(prior['cell_source_count'], 0)
        self.assertEqual(prior['missing_cell_source_count'], 1)
        omitted = run / 'research' / 'cells' / 'omitted.json'
        omitted.write_text(json.dumps({'run_id': run.name, 'omitted': 0}))
        with self.assertRaises(ValueError):
            bundle.read(run.name, 'cells')

    def test_console_experience_messages_distinguish_access_and_program_match(self):
        from asterion.applications.prime.p7.experience import CellArchive
        run, _ = self.source()
        source = "result = 'private-source-sentinel'"
        archive = CellArchive(run)
        archive.started('cell-1', 'generation-1', source)
        bundle = self.load()
        current = self.root / 'current'
        current.mkdir()
        messages = []
        bundle.bind(current, messages.append)
        bundle.mark_loaded()
        revision = 'sha256:' + 'a' * 64
        exported = {'kind': 'text', 'value': source, 'export_id': digest(source)}
        bundle.record_revision(revision, {'changed': [], 'retained': []}, [exported])
        self.assertIn('尚无', messages[-1])
        bundle.read(run.name, 'cells')
        bundle.record_revision(revision, {'changed': [], 'retained': []}, [exported])
        self.assertIn('复用已核对', messages[-1])
        self.assertIn('源码候选 1', messages[0])
        self.assertNotIn('private-source-sentinel', ''.join(messages))
        self.assertNotIn(str(self.root), ''.join(messages))


if __name__ == '__main__':
    unittest.main()
