from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7.broker import ArcTransition
from asterion.applications.prime.p7.solutions import VerifiedPrefix
from tools import p7_efficiency_queue as queue


def prefix(counts, source='old'):
    transitions = []
    for level, count in enumerate(counts, 1):
        for index in range(count):
            sequence = len(transitions) + 1
            transitions.append(ArcTransition(sequence, 'ACTION1', f'b{sequence}', f'a{sequence}',
                                             level if index == count - 1 else level - 1))
    return VerifiedPrefix('test-game', 0, 3, len(counts), tuple(transitions), source, 'digest')


class TestEfficiencyQueue(unittest.TestCase):
    def setUp(self):
        self.game = {'game_id': 'test-game', 'win_levels': 3, 'baseline_actions': (10, 10, 10)}

    def test_equal_baseline_is_queued_once_below_baseline_is_not(self):
        source = prefix((10, 9, 11))
        row = {}
        queue.refresh_tasks(self.game, row, source)
        self.assertEqual(set(row['efficiency_redos']), {'1', '3'})
        self.assertEqual(queue.level_score(10, 10), 100)
        self.assertLess(queue.level_score(19, 20), 115)
        self.assertEqual(queue.level_score(9, 10), 115)
        row['efficiency_redos']['1'].update(status='no-improvement', genuine_attempts=1)
        with patch.object(queue, '_native_anchor', return_value='native-anchor'):
            task = queue.next_task(self.game, row, source, runs_root=Path('/unused'))
        self.assertEqual(task['level'], 3)
        self.assertEqual(task['anchor_run_id'], 'native-anchor')
        self.assertEqual(row['efficiency_redos']['1']['genuine_attempts'], 1)
        other = {'game_id': 'test-game', 'win_levels': 3, 'baseline_actions': (20, 20, 20)}
        row2 = {}
        queue.refresh_tasks(other, row2, prefix((19,)))
        self.assertEqual(row2['efficiency_redos'], {})

    def test_partial_progress_is_ready_and_prepares_exact_boundary(self):
        row = {}
        with patch.object(queue, '_native_anchor', return_value='native-partial'):
            task = queue.next_task(self.game, row, prefix((10,)), runs_root=Path('/unused'))
        self.assertEqual(task['level'], 1)
        self.assertEqual(task['anchor_run_id'], 'native-partial')
        self.assertIn('1', row['efficiency_redos'])
        source = prefix((10, 10, 11), 'composed')
        task = {'level': 2, 'seed': 0, 'baseline': 10, 'previous_actions': 10,
                'status': 'pending', 'genuine_attempts': 0, 'anchor_run_id': 'native'}
        prepared = queue.prepare_task(self.game, task, source)
        self.assertEqual(prepared['restoration_actions'], 10)
        self.assertEqual(prepared['source_run_id'], 'composed')
        self.assertEqual(prepared['effective_action_cap'], 20)
        self.assertEqual(queue.prepare_task(self.game, {**task, 'level': 1}, source)['source_run_id'], None)

    def test_only_improved_target_admits_a_verified_complete_saved_suffix(self):
        source = prefix((10, 10, 11))
        task = {'level': 2, 'seed': 0, 'baseline': 10, 'anchor_run_id': 'native'}
        kwargs = dict(operator_root=Path('/operator'), arc_root=Path('/arc'), game=self.game,
                      task=task, new_run_id='new', previous_prefix=source, expected_model_id='model')
        loader = 'asterion.applications.prime.p7.solutions.load_exact_prefix'
        prior = 'asterion.applications.prime.p7.solutions.load_resume_worldmap'
        compose = 'tools.recover_prime_p7_trace_race.compose_saved_route'
        with patch(loader, return_value=prefix((10, 10), 'new')), patch(prior, return_value={}), patch(compose) as materialize:
            result = queue.finish_task(**kwargs)
        self.assertEqual(result['status'], 'no-improvement')
        self.assertIsNone(result['admitted_run_id'])
        materialize.assert_not_called()
        with patch(loader, side_effect=[prefix((10, 8), 'new'), prefix((10, 8, 11), 'admitted')]), patch(prior, return_value={}), patch(compose, return_value=Path('/operator/admitted')) as materialize:
            result = queue.finish_task(**kwargs)
        self.assertEqual(result['status'], 'improved')
        self.assertEqual(result['admitted_actions'], 29)
        self.assertEqual(materialize.call_args.kwargs['suffix_run_id'], 'native')
        with patch(loader, return_value=prefix((10,), 'new')), patch(compose) as materialize:
            self.assertEqual(queue.finish_task(**kwargs)['status'], 'unfinished')
        materialize.assert_not_called()

    def test_partial_frontier_admits_directly_and_earlier_level_keeps_saved_tail(self):
        source = prefix((10, 10))
        loader = 'asterion.applications.prime.p7.solutions.load_exact_prefix'
        prior = 'asterion.applications.prime.p7.solutions.load_resume_worldmap'
        compose = 'tools.recover_prime_p7_trace_race.compose_saved_route'
        for level, candidate_counts in ((1, (8,)), (2, (10, 8))):
            task = {'level': level, 'seed': 0, 'baseline': 10, 'anchor_run_id': 'native-partial'}
            kwargs = dict(operator_root=Path('/operator'), arc_root=Path('/arc'), game=self.game,
                          task=task, new_run_id='new', previous_prefix=source, expected_model_id='model')
            result_counts = (*candidate_counts, *queue.level_counts(source)[level:])
            with self.subTest(level=level), patch(loader, side_effect=[prefix(candidate_counts, 'new'), prefix(result_counts, 'admitted')]), patch(prior, return_value={}), patch(compose, return_value=Path('/operator/admitted')) as materialize:
                result = queue.finish_task(**kwargs)
            self.assertEqual(result['status'], 'improved')
            self.assertEqual(result['admitted_levels'], 2)
            self.assertEqual(result['admitted_actions'], 18)
            if level == 2:
                materialize.assert_not_called()
            else:
                self.assertEqual(materialize.call_args.kwargs['suffix_run_id'], 'native-partial')
