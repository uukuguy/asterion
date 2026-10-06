"""Read-only saved-route statistics never launch or replay a game."""
from __future__ import annotations

import json
import os
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
        self.recorders = {}
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

    def write_recording(self, name, game_id='test-1', levels=2, context_update=None, gap=False,
                        restoration_actions=0, pre_context_kind=None, duplicate_context=False):
        run = self.write_run(name)
        (run / 'summary.json').unlink()
        import shutil
        shutil.rmtree(run / 'trace')
        (run / 'trace').mkdir()
        recorder = PrimeTraceRecorder(run / 'trace')
        win = next(game['win_levels'] for game in self.catalog if game['game_id'] == game_id)
        context = {'run_id': name, 'game_id': game_id, 'model_id': 'gpt-6.1-sol',
                   'seed': 0, 'win_levels': win, 'target_level': win,
                   'restoration_actions': restoration_actions,
                   'source_run_id': 'saved-source' if restoration_actions else None}
        context.update(context_update or {})
        self.recorders[name] = recorder
        self.addCleanup(recorder.close)
        if pre_context_kind:
            recorder.append(pre_context_kind, trace_identities_for('gpt-6.1-sol'), {})
        if restoration_actions == 0:
            recorder.append('arc.run.context', trace_identities_for('gpt-6.1-sol'), context)
        for index in range(1, levels + 2):
            recorder.append('arc.action', trace_identities_for('gpt-6.1-sol'), {
                'sequence': index + int(gap and index > 1), 'action': 'ACTION1',
                'before_sha256': 'sha256:' + str(index - 1) * 64,
                'after_sha256': 'sha256:' + str(index) * 64,
                'levels_completed': min(index, levels)})
            if index == restoration_actions:
                recorder.append('arc.run.context', trace_identities_for('gpt-6.1-sol'), context)
        if duplicate_context:
            recorder.append('arc.run.context', trace_identities_for('gpt-6.1-sol'), context)
        if game_id != 'test-1':
            shutil.rmtree(run / 'research')
            scope = {'game_id': game_id, 'seed': 0, 'win_levels': win, 'run_id': name, 'attempt_id': name}
            snapshot = {'scope': scope, 'worldmap': {'description_zh': '移动', 'state_summary': '状态',
                        'rules': [], 'unknowns': [], 'competing_hypotheses': []}}
            revision = digest(snapshot)
            research = run / 'research' / digest(scope)[7:]
            (research / 'revisions').mkdir(parents=True)
            (research / 'current.json').write_text(json.dumps({'scope': scope, 'revision': revision}))
            (research / 'revisions' / (revision[7:] + '.json')).write_text(json.dumps(snapshot))
        return run

    def test_resumed_progress_accepts_exact_pre_context_restoration(self):
        for restored in (1, 2):
            with self.subTest(restored=restored):
                self.write_recording(f'restored-{restored}', levels=3, restoration_actions=restored)
        value = self.overview().build()
        self.assertEqual([run['observed_completed_levels'] for run in value['games'][0]['runs']], [3, 3])
        self.assertEqual(value['games'][0]['display_completed_levels'], 3)
        self.assertEqual(value['totals']['completed_levels'], 0)
        self.assertEqual(value['totals']['saved_route_actions'], 0)
        self.assertIsNone(value['games'][0]['resume_run_id'])

    def test_recording_activity_tracks_actual_events_and_exact_run_context(self):
        from asterion.applications.prime.p7.console_events import ConsoleEventWriter
        from tests.test_prime_p7_console_events import research_payloads
        run = self.write_recording('current', levels=2)
        writer = ConsoleEventWriter(run, run.name, 'test-1')
        payload = {**research_payloads()['compute_task'], 'level': 3, 'origin': 'calculation'}
        writer.append('compute_task', payload)
        overview = self.overview()
        activity = overview.build()['games'][0]['runs'][0]['activity']
        self.assertEqual((activity['level'], activity['phase'], activity['event_sequence']), (3, 'computing', 1))
        self.assertEqual(activity['target_level'], 6)
        self.assertNotIn('goal', activity)
        writer.append('compute_task', {**payload, 'status': 'completed'})
        with patch.object(overview, '_read_run', wraps=overview._read_run) as read_run:
            with patch('asterion.applications.prime.p7.console_overview._recorded_entries') as read_trace:
                activity = overview.build()['games'][0]['runs'][0]['activity']
        self.assertEqual(read_run.call_count, 0)
        self.assertEqual(read_trace.call_count, 0)
        self.assertEqual((activity['phase'], activity['event_sequence']), ('waiting', 2))
        rows = (run / 'console-events.jsonl').read_text().replace('"game_id":"test-1"', '"game_id":"other-1"')
        (run / 'console-events.jsonl').write_text(rows)
        self.assertIsNone(overview.build()['games'][0]['runs'][0]['activity'])

    def test_activity_requires_matching_seed_context_and_complete_event_prefix(self):
        from asterion.applications.prime.p7.console_events import ConsoleEventWriter
        from tests.test_prime_p7_console_events import research_payloads
        run = self.write_recording('wrong-seed', context_update={'seed': 1})
        writer = ConsoleEventWriter(run, run.name, 'test-1')
        writer.append('compute_task', research_payloads()['compute_task'])
        self.assertIsNone(self.overview().build()['games'][0]['runs'][0]['activity'])
        run = self.write_recording('corrupt-events')
        writer = ConsoleEventWriter(run, run.name, 'test-1')
        writer.append('compute_task', research_payloads()['compute_task'])
        with (run / 'console-events.jsonl').open('a') as handle:
            handle.write('{}\n')
        self.assertIsNone(self.overview().build()['games'][0]['runs'][0]['activity'])

    def test_restored_actions_are_waiting_and_oversized_events_are_not_read(self):
        from asterion.applications.prime.p7.console_events import ConsoleEventWriter
        run = self.write_recording('restoring', levels=2, restoration_actions=1)
        writer = ConsoleEventWriter(run, run.name, 'test-1')
        writer.append('action', {'action': 'ACTION1', 'sequence': 1, 'levels_completed': 1,
                      'before_sha256': 'sha256:' + '0' * 64, 'after_sha256': 'sha256:' + '1' * 64,
                      'decision_id': None})
        overview = self.overview()
        activity = overview.build()['games'][0]['runs'][0]['activity']
        self.assertEqual((activity['phase'], activity['target_level']), ('waiting', 6))
        with (run / 'console-events.jsonl').open('ab') as handle:
            handle.truncate(32 * 1024 * 1024 + 1)
        with patch('asterion.applications.prime.p7.console_overview.recorded_activity_events') as read:
            self.assertIsNone(overview.build()['games'][0]['runs'][0]['activity'])
        self.assertEqual(read.call_count, 0)

    def test_fresh_and_restored_context_boundaries_reject_inconsistent_journals(self):
        cases = (
            {'restoration_actions': 1, 'context_update': {'restoration_actions': 0}},
            {'restoration_actions': 1, 'context_update': {'restoration_actions': 2}},
            {'restoration_actions': 1, 'context_update': {'source_run_id': None}},
            {'restoration_actions': 1, 'context_update': {'source_run_id': 'bad/path'}},
            {'restoration_actions': 1, 'context_update': {'source_run_id': 'invalid'}},
            {'restoration_actions': 1, 'context_update': {'target_level': 1}},
            {'restoration_actions': 1, 'pre_context_kind': 'arc.usage.reported'},
            {'restoration_actions': 1, 'gap': True},
            {'restoration_actions': 1, 'duplicate_context': True},
            {'context_update': {'source_run_id': 'saved-source'}},
            {'context_update': {'restoration_actions': 1}},
            {'pre_context_kind': 'arc.usage.reported'},
        )
        import shutil
        for case in cases:
            with self.subTest(case=case):
                run = self.write_recording('invalid', levels=3, **case)
                self.assertEqual(self.overview().build()['games'][0]['display_completed_levels'], 0)
                self.recorders['invalid'].close()
                shutil.rmtree(run)

    def test_parallel_live_progress_is_display_only_and_does_not_duplicate_attempts(self):
        self.write_recording('first', levels=2)
        self.write_recording('repeated', levels=1)
        self.write_recording('second', game_id='other-1', levels=1)
        value = self.overview().build()
        self.assertEqual([game['display_completed_levels'] for game in value['games']], [2, 1])
        self.assertEqual(value['totals']['display_completed_levels'], 3)
        self.assertEqual(value['totals']['completed_levels'], 0)
        self.assertEqual(value['totals']['saved_route_actions'], 0)
        self.assertEqual(value['totals']['score'], '0.000000')
        self.assertTrue(value['games'][0]['progress_pending'])
        self.assertIsNone(value['games'][0]['resume_run_id'])

    def test_live_cache_advances_each_completed_level_and_sealed_progress_keeps_same_display(self):
        run = self.write_recording('current', levels=1)
        overview = self.overview()
        self.assertEqual(overview.build()['games'][0]['display_completed_levels'], 1)
        recorder = self.recorders['current']
        recorder.append('arc.action', trace_identities_for('gpt-6.1-sol'), {
            'sequence': 3, 'action': 'ACTION1', 'before_sha256': 'sha256:' + '2' * 64,
            'after_sha256': 'sha256:' + '3' * 64, 'levels_completed': 2})
        self.assertEqual(overview.build()['games'][0]['display_completed_levels'], 2)
        transitions = tuple(ArcTransition(index, 'ACTION1', 'sha256:' + str(index - 1) * 64,
                            'sha256:' + str(index) * 64, 1 if index < 3 else 2) for index in range(1, 4))
        marker = {'game_id': 'test-1', 'seed': 0, 'win_levels': 6, 'levels_completed': 2,
                  'primitive_actions': 3, 'terminal_reason': 'level-completed',
                  'replay_sha256': replay_sha256(transitions, terminal_reason='level-completed')}
        recorder.append('arc.run.partial', trace_identities_for('gpt-6.1-sol'), marker)
        recorder.seal()
        summary = {'schema': 'asterion.prime.p7-live-private-summary/v1', 'run_id': run.name,
                   'experiment': {'model': 'gpt-6.1-sol', 'game_id': 'test-1', 'seed': 0,
                                  'prediction_variant': 'verified'}, 'broker': None, 'completed_prefix': marker,
                   'receipt': {}, 'failure': {'type': 'CancelledError'},
                   'replay_verified': True, 'sealed_trace': True, 'cleanup_complete': True,
                   'diagnostics': {'broker_status': {'primitive_actions': 3}}}
        (run / 'summary.json').write_text(json.dumps(summary))
        game = overview.build()['games'][0]
        self.assertEqual(game['display_completed_levels'], 2)
        self.assertEqual(game['completed_levels'], 2)
        self.assertFalse(game['progress_pending'])
        self.assertEqual(game['route_actions'], 3)

    def test_live_progress_rejects_gaps_foreign_context_and_manual_context(self):
        for mutation in ({'model_id': 'foreign'}, {'run_id': 'foreign'}, {'game_id': 'other-1'}, {'manual': True}):
            with self.subTest(context=mutation):
                run = self.write_recording('invalid', context_update=mutation)
                self.assertEqual(self.overview().build()['games'][0]['display_completed_levels'], 0)
                import shutil
                shutil.rmtree(run)
        self.write_recording('gap', gap=True)
        self.assertEqual(self.overview().build()['games'][0]['display_completed_levels'], 0)

    def test_saved_progress_never_regresses_to_lower_live_attempt(self):
        self.write_run('saved', levels=4)
        self.write_recording('redo', levels=1)
        game = self.overview().build()['games'][0]
        self.assertEqual(game['display_completed_levels'], 4)
        self.assertFalse(game['progress_pending'])
        self.assertEqual(game['completed_levels'], 4)

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

    def test_saved_route_actions_count_selected_route_once_across_failed_partial_and_repeated_attempts(self):
        self.write_run('a-best', level_counts=(15, 15, 15, 15))
        self.write_run('z-repeated-restoration', level_counts=(15, 15, 15, 15))
        self.write_run('earlier-partial', levels=2)
        failed = self.write_run('failed-attempt')
        trace = failed / 'trace' / 'prime-trace.jsonl'
        trace.write_text(trace.read_text().replace('ACTION1', 'ACTION2', 1))
        value = self.overview().build()
        self.assertEqual(value['games'][0]['best_run_id'], 'a-best')
        self.assertEqual(value['games'][0]['route_actions'], 60)
        self.assertEqual(value['totals']['saved_route_actions'], 60)
        self.assertEqual(value['totals']['primitive_actions'], 4 * 98)
        self.assertEqual(value['totals']['restoration_actions'], 4 * 12)
        self.assertEqual(len(value['games'][0]['runs']), 4)

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

    def test_latest_attempt_is_separate_from_highest_saved_progress(self):
        old = self.write_run('z-older-fuller', levels=4)
        new = self.write_run('a-newer-redo', levels=1)
        os.utime(old / 'summary.json', ns=(1_000_000_000, 1_000_000_000))
        os.utime(new / 'summary.json', ns=(2_000_000_000, 2_000_000_000))
        game = self.overview().build()['games'][0]
        self.assertEqual(game['best_run_id'], old.name)
        self.assertEqual(game['completed_levels'], 4)
        self.assertEqual(game['latest_run_id'], new.name)

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
        self.assertEqual(value['totals']['saved_route_actions'], 0)
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
        for key in ('completed_levels', 'completed_games', 'saved_route_actions', 'primitive_actions',
                    'restoration_actions', 'new_solver_actions', 'actions_pending'):
            with self.subTest(counter=key):
                self.assertEqual(value['totals'][key], 0)
        self.assertEqual(value['totals']['score'], '0.000000')
        self.assertIsNone(value['games'][0]['best_run_id'])
        self.assertIsNone(value['games'][0]['resume_run_id'])
