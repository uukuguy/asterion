"""Read-only saved-route statistics never launch or replay a game."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.private_trace import trace_identities_for
from asterion.applications.prime.p7.score import digest, replay_sha256


class TestConsoleOverview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.runs = self.root / 'runs'
        self.catalog = ({'game_id': 'test-1', 'alias': 'test', 'win_levels': 6,
                         'baseline_actions': (20,) * 6},
                        {'game_id': 'other-1', 'alias': 'other', 'win_levels': 2,
                         'baseline_actions': (20,) * 2})

    def write_run(self, name='selected', model='gpt-6.1-sol', levels=4, level_counts=None):
        run = self.runs / name
        (run / 'trace').mkdir(parents=True)
        recorder = PrimeTraceRecorder(run / 'trace')
        transitions = []
        for sequence in range(1, 99):
            completed = (sum(sequence >= sum(level_counts[:index]) for index in range(1, levels + 1))
                         if level_counts is not None else min(levels, sequence * levels // 67))
            item = ArcTransition(sequence, 'ACTION1', 'sha256:' + 'a' * 64,
                                 'sha256:' + 'b' * 64, completed)
            transitions.append(item)
            recorder.append('arc.action', trace_identities_for(model), {
                'sequence': sequence, 'action': item.action, 'before_sha256': item.before_sha256,
                'after_sha256': item.after_sha256, 'levels_completed': completed})
        from asterion.applications.prime.p7.solutions import _truncate
        prefix = _truncate(tuple(transitions), levels)
        marker = {'game_id': 'test-1', 'seed': 0, 'win_levels': 6, 'levels_completed': levels,
                  'primitive_actions': len(prefix), 'terminal_reason': 'level-completed',
                  'replay_sha256': replay_sha256(prefix, terminal_reason='level-completed')}
        recorder.append('arc.run.partial', trace_identities_for(model), marker)
        recorder.seal()
        summary = {'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': name,
                   'experiment': {'model': model, 'game_id': 'test-1', 'seed': 0,
                                  'prediction_variant': 'verified'},
                   'broker': None, 'completed_prefix': marker, 'receipt': {},
                   'failure': {'type': 'RuntimeError', 'message': 'sk-sentinel-secret'},
                   'replay_verified': True, 'sealed_trace': True, 'cleanup_complete': True,
                   'diagnostics': {'broker_status': {'primitive_actions': 98},
                                   'restoration_actions': 12, 'new_solver_actions': 86}}
        (run / 'summary.json').write_text(json.dumps(summary))
        scope = {'game_id': 'test-1', 'seed': 0, 'win_levels': 6, 'run_id': name, 'attempt_id': name}
        world = {'description_zh': '移动', 'state_summary': '四关', 'rules': [],
                 'unknowns': [], 'competing_hypotheses': []}
        snapshot = {'scope': scope, 'worldmap': world}
        revision = digest(snapshot)
        research = run / 'research' / digest(scope)[7:]
        (research / 'revisions').mkdir(parents=True)
        (research / 'current.json').write_text(json.dumps({'scope': scope, 'revision': revision}))
        (research / 'revisions' / (revision[7:] + '.json')).write_text(json.dumps(snapshot))
        return run

    def overview(self):
        from asterion.applications.prime.p7.console_overview import ConsoleOverview
        return ConsoleOverview(self.runs, self.catalog)

    def test_full_roster_partial_score_and_full_attempt_actions(self):
        self.write_run()
        self.write_run('wrong-model', model='deepseek-v4-flash')
        overview = self.overview()
        with patch('asterion.applications.prime.p7.solutions._fresh_engine', side_effect=AssertionError):
            value = overview.build()
        game = value['games'][0]
        self.assertEqual(game['score'], '47.619048')
        self.assertEqual(value['totals']['score'], '23.809524')
        self.assertEqual(value['totals']['total_games'], 2)
        self.assertEqual(value['totals']['primitive_actions'], 98)
        self.assertEqual(value['totals']['restoration_actions'], 12)
        self.assertEqual(game['route_actions'], 67)
        self.assertEqual(game['resume_run_id'], 'selected')
        self.assertEqual(len(game['runs']), 1)
        self.assertNotIn('sk-sentinel-secret', json.dumps(value))

    def test_tamper_invalidates_display_cache_and_resume(self):
        run = self.write_run()
        overview = self.overview()
        self.assertEqual(overview.build()['games'][0]['completed_levels'], 4)
        trace = run / 'trace' / 'prime-trace.jsonl'
        trace.write_text(trace.read_text().replace('ACTION1', 'ACTION2', 1))
        game = overview.build()['games'][0]
        self.assertEqual(game['completed_levels'], 0)
        self.assertEqual(game['status'], 'unverified')
        self.assertIsNone(game['resume_run_id'])
        self.assertEqual(overview.build()['totals']['primitive_actions'], 98)

    def test_research_revision_changes_invalidate_resume_eligibility(self):
        run = self.write_run()
        overview = self.overview()
        self.assertEqual(overview.build()['games'][0]['resume_run_id'], 'selected')
        current = next((run / 'research').glob('*/current.json'))
        current.write_text('{}')
        self.assertIsNone(overview.build()['games'][0]['resume_run_id'])

    def test_unsealed_recording_counts_actions_without_granting_progress(self):
        run = self.write_run()
        (run / 'summary.json').unlink()
        (run / 'trace' / 'prime-trace.seal.json').unlink()
        trace = run / 'trace' / 'prime-trace.jsonl'
        trace.write_text('\n'.join(trace.read_text().splitlines()[:-1]) + '\n')
        value = self.overview().build()
        game = value['games'][0]
        self.assertEqual(game['recording_run_id'], 'selected')
        self.assertEqual(game['completed_levels'], 0)
        self.assertIsNone(game['resume_run_id'])
        self.assertEqual(value['totals']['primitive_actions'], 98)
        self.assertEqual(value['totals']['actions_pending'], 98)
        self.assertEqual(value['totals']['new_solver_actions'], 0)
        self.assertIs(game['runs'][0]['counts_pending'], True)

    def test_same_progress_uses_higher_score_before_shorter_route(self):
        self.write_run('shorter', level_counts=(1, 1, 1, 40))
        self.write_run('stronger', level_counts=(15, 15, 15, 15))
        game = self.overview().build()['games'][0]
        self.assertEqual(game['best_run_id'], 'stronger')
        self.assertEqual(game['resume_run_id'], 'stronger')
        self.assertEqual(game['score'], '47.619048')
        self.assertEqual(game['route_actions'], 60)

    def test_pre_worldmap_run_is_excluded_from_every_current_statistic(self):
        import shutil
        run = self.write_run('old-same-model')
        shutil.rmtree(run / 'research')
        value = self.overview().build()
        self.assertEqual(value['scope']['history_scope'], 'worldmap-p7')
        self.assertEqual(value['games'][0]['runs'], [])
        self.assertEqual(value['games'][0]['status'], 'unplayed')
        for key in ('completed_levels', 'completed_games', 'primitive_actions',
                    'restoration_actions', 'new_solver_actions', 'actions_pending'):
            with self.subTest(counter=key):
                self.assertEqual(value['totals'][key], 0)
        self.assertEqual(value['totals']['score'], '0.000000')
        self.assertIsNone(value['games'][0]['best_run_id'])
        self.assertIsNone(value['games'][0]['resume_run_id'])
