"""Known settled observations stop plan suffixes without replay or refunds."""

import copy
import json
import random
from pathlib import Path
from unittest.mock import patch

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.solver import Solver
from tests.test_prime_p7_solver import P7SolverFixture
from tests.test_prime_p7_native_broker import _Engine


CANDIDATE = {'status': 'candidate', 'dx': 0, 'dy': 4,
             'exposed_windows': [[0, 0, 2, 1]], 'matched_pairs': 140,
             'informative_pairs': 150, 'interpretation': 'pixel-translation-candidate'}
DETECTOR = 'asterion.applications.prime.p7.solver.view_change'
LIVE_RUN_ID = 'p7-live-20261009105835-2a01f0f83adf53266be81402'


class _ViewEngine(_Engine):
    def __init__(self):
        super().__init__()
        rng = random.Random(27)
        self.before = [[rng.randrange(16) for _ in range(32)] for _ in range(32)]
        self.after = [[rng.randrange(16) for _ in range(32)] for _ in range(4)] + copy.deepcopy(self.before[:-4])

    def observe(self):
        value = super().observe()
        value['frame'] = [copy.deepcopy(self.after if self.calls else self.before)]
        if len(self.calls) > 1:
            value['state'] = 'GAME_OVER'
        return value


class TestP7ObservationBoundary(P7SolverFixture):
    def setUp(self):
        super().setUp()
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history('run-1')
        self.solver = Solver(broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id='run-1', attempt_id='attempt-1',
            event_sink=lambda kind, payload: self.events.append((kind, payload)),
            learner_profile='autonomous')

    def submit(self, steps, name='boundary', **options):
        return {'plan_id': name, 'start': self.solver.current_context()['observation_ref'],
                'steps': steps, **options}

    @staticmethod
    def step(**options):
        return {'action': {'name': 'ACTION1', 'data': {}}, **options}

    def test_reset_with_wrong_prediction_cannot_continue_even_when_mismatches_allowed(self):
        self.solver.execute_plan(self.submit([self.step()], name='before-reset'))
        reset = {'action': {'name': 'RESET', 'data': {}},
                 'expect': {'cells': [{'x': 0, 'y': 0, 'value': 99}]}}
        result = self.solver.execute_plan(self.submit([reset, self.step()], stop_on_mismatch=False))
        self.assertEqual(self.engine.calls, ['ACTION1', 'RESET'])
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'reset-applied'))
        self.assertTrue(result['feedback'][0]['differences'])
        self.assertEqual(len(result['unexecuted_steps']), 1)
        self.assertEqual(result['budget']['primitive_actions'], 2)

    def test_legacy_actual_terminal_has_priority_over_wrong_prediction(self):
        self.solver.learner_profile = 'legacy'
        self.engine.game_over_after = 1
        self.revise()
        result = self.solver.execute_plan(self.plan(values=(99, 2)))
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'game-over'))
        self.assertTrue(result['feedback'][0]['differences'])
        self.assertEqual(len(self.engine.calls), 1)

    def test_candidate_returns_known_prefix_and_same_id_only_reads_result(self):
        plan = self.submit([self.step(), self.step()])
        original = copy.deepcopy(plan)
        before = copy.deepcopy(plan['start'])
        with patch(DETECTOR, return_value=CANDIDATE, create=True) as detector:
            result = self.solver.execute_plan(plan)
            self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'observation-boundary'))
            self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertEqual(detector.call_count, 1)
        self.assertEqual(plan, original)
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(result['budget']['primitive_actions'], 1)
        self.assertEqual(result['budget']['scoring']['current_level']['paid_actions'], 1)
        self.assertEqual(len(result['unexecuted_steps']), 1)
        facts = result['feedback'][0]['view_change']
        self.assertEqual(facts.get('origin'), 'derived-pixel-measurement')
        self.assertEqual(facts['before_observation_ref'], before)
        self.assertEqual(facts['after_observation_ref'], result['observation_ref'])
        self.assertEqual(result['observation_boundary']['reason'], 'view-change-candidate')
        self.assertEqual(result['observation_boundary'].get('origin'), 'application-policy')
        self.assertEqual(detector.call_args.args, ([[0, 1]], [[1, 1]]))
        with patch(DETECTOR, return_value={'status': 'no-candidate'}, create=True):
            resumed = self.solver.execute_plan(self.submit(result['unexecuted_steps'], name='continue'))
        self.assertEqual((resumed['applied_count'], resumed['stop_reason']), (1, 'executed'))
        self.assertEqual(resumed['budget']['primitive_actions'], 2)

    def test_optout_retains_candidate_evidence_without_stopping_suffix(self):
        with patch(DETECTOR, return_value=CANDIDATE, create=True):
            result = self.solver.execute_plan(self.submit([self.step(), self.step()], stop_on_view_change=False))
        self.assertEqual(result['status'], 'recorded')
        self.assertEqual((result['applied_count'], result['stop_reason']), (2, 'executed'))
        self.assertEqual(len(result['feedback']), 2)
        self.assertTrue(all(item['view_change']['status'] == 'candidate' for item in result['feedback']))
        self.assertNotIn('observation_boundary', result)

    def test_actor_checkpoint_wins_with_view_policy_disabled_and_on_last_step_is_not_a_yield(self):
        with patch(DETECTOR, return_value={'status': 'no-candidate'}, create=True):
            result = self.solver.execute_plan(self.submit([self.step(observe_after=True), self.step()],
                stop_on_view_change=False))
            final = self.solver.execute_plan(self.submit([self.step(observe_after=True)], name='last'))
        self.assertEqual(result['status'], 'recorded')
        self.assertEqual(final['status'], 'recorded')
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'observation-boundary'))
        self.assertEqual(result['observation_boundary']['reason'], 'actor-checkpoint')
        self.assertEqual((final['applied_count'], final['stop_reason']), (1, 'executed'))
        self.assertNotIn('observation_boundary', final)

    def test_candidate_on_last_step_is_recorded_without_claiming_unexecuted_suffix(self):
        with patch(DETECTOR, return_value=CANDIDATE, create=True):
            result = self.solver.execute_plan(self.submit([self.step()]))
        self.assertEqual(result['stop_reason'], 'executed')
        self.assertIn('view_change', result['feedback'][0])
        self.assertEqual(result['feedback'][0]['view_change']['status'], 'candidate')
        self.assertEqual(result['unexecuted_steps'], [])
        self.assertNotIn('observation_boundary', result)

    def test_ambiguous_unsupported_and_no_candidate_do_not_stop_plan(self):
        for status in ('ambiguous', 'unsupported', 'no-candidate'):
            with self.subTest(status=status), patch(DETECTOR, return_value={'status': status}, create=True):
                result = self.solver.execute_plan(self.submit([self.step(), self.step()], name=status))
            self.assertEqual((result['applied_count'], result['stop_reason']), (2, 'executed'))

    def test_analysis_exception_after_action_leave_preserves_known_facts(self):
        left = []
        def failure(*args):
            self.assertEqual(left[-1], 'action')
            raise RuntimeError('private detector error sentinel')
        self.control.leave = left.append
        for enabled in (True, False):
            with self.subTest(enabled=enabled), patch(DETECTOR, side_effect=failure, create=True):
                result = self.solver.execute_plan(self.submit([self.step(), self.step()],
                    name=str(enabled), stop_on_view_change=enabled))
            self.assertEqual(result['status'], 'recorded')
            self.assertEqual(result['applied_count'], 1 if enabled else 2)
            self.assertEqual(result['stop_reason'], 'observation-boundary' if enabled else 'executed')
            if enabled:
                self.assertEqual(result['observation_boundary']['reason'], 'observation-analysis-unavailable')
            self.assertEqual(result['feedback'][0]['view_change']['status'], 'unavailable')
            current = self.solver.current_context()
            self.assertFalse(current['environment_result_unknown'])
            self.assertFalse(current['processing_blocked'])
            self.assertNotIn('private detector error sentinel', json.dumps(result))

    def test_invalid_boolean_or_tail_is_rejected_before_any_dispatch(self):
        for value in (1, 'true', None):
            for field in ('stop_on_view_change', 'observe_after'):
                with self.subTest(value=value, field=field):
                    plan = self.submit([self.step(), self.step()])
                    if field == 'stop_on_view_change':
                        plan[field] = value
                    else:
                        plan['steps'][1][field] = value
                    self.assertEqual(self.solver.execute_plan(plan)['status'], 'rejected')
        self.assertEqual(self.engine.calls, [])

    def test_legacy_does_not_accept_observation_policy_fields(self):
        self.solver.learner_profile = 'legacy'
        self.revise()
        for field in ('stop_on_view_change', 'observe_after'):
            plan = self.plan(values=(1,))
            if field == 'stop_on_view_change':
                plan[field] = False
            else:
                plan['steps'][0][field] = False
            self.assertEqual(self.solver.execute_plan(plan)['status'], 'rejected')
        self.assertEqual(self.engine.calls, [])

    def test_no_current_dispatch_never_reuses_prior_applied_count_for_policy(self):
        self.engine.remove_second_after_first = True
        with patch(DETECTOR, return_value={'status': 'no-candidate'}, create=True) as detector:
            result = self.solver.execute_plan(self.submit([self.step(),
                {'action': {'name': 'ACTION2', 'data': {}}, 'observe_after': True}, self.step()]))
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'action-unavailable'))
        self.assertEqual(detector.call_count, 1)
        self.assertEqual(len(result['unexecuted_steps']), 2)
        self.assertNotIn('observation_boundary', result)

    def test_committed_action_with_derived_failure_does_not_run_policy(self):
        from asterion.applications.prime.p7.dynamic_evidence import EvidenceProcessingError
        original = self.broker.act_checked
        def after_commit(plan):
            original(plan)
            raise EvidenceProcessingError('derived-projection-failed', stage='derived-failed',
                action_sequence=1, outcome_known=True, durable=True, recovery='read-only-rebuild')
        with patch.object(self.broker, 'act_checked', side_effect=after_commit), \
                patch(DETECTOR, return_value=CANDIDATE, create=True) as detector:
            result = self.solver.execute_plan(self.submit([self.step(), self.step()]))
        detector.assert_not_called()
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'processing-failed'))
        self.assertNotIn('observation_boundary', result)
        self.assertFalse(self.solver.current_context()['environment_result_unknown'])
        self.assertTrue(self.solver.current_context()['processing_blocked'])

    def test_real_translation_returns_before_next_step_can_reach_game_over(self):
        self.engine = _ViewEngine()
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history('run-1')
        self.solver.broker = self.broker
        frames = copy.deepcopy((self.engine.before, self.engine.after))
        result = self.solver.execute_plan(self.submit([self.step(), self.step()]))
        self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'observation-boundary'))
        self.assertEqual(result['observation']['state'], 'NOT_FINISHED')
        self.assertEqual(result['feedback'][0]['view_change']['dy'], 4)
        self.assertEqual(result['feedback'][0]['view_change']['dx'], 0)
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(len(self.broker.journal), 1)
        self.assertEqual((self.engine.before, self.engine.after), frames)

    def test_maximal_legal_optout_projects_measurements_without_losing_committed_actions(self):
        from asterion.applications.prime.p7.score import canonical_bytes
        from asterion.applications.prime.p7.view_change import view_change
        rng = random.Random(29)
        board = [[rng.randrange(256) for _ in range(64)] for _ in range(64)]
        shifted = [[rng.randrange(256) for _ in range(64)] for _ in range(4)] + copy.deepcopy(board[:-4])
        measurement = view_change(board, shifted)
        self.assertEqual(measurement['status'], 'candidate')
        class Engine(_Engine):
            def observe(self):
                value = super().observe()
                value['frame'] = [copy.deepcopy(board)]
                return value
        self.engine = Engine()
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history(LIVE_RUN_ID)
        self.solver = Solver(broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name) / 'capacity', run_id=LIVE_RUN_ID,
            attempt_id=LIVE_RUN_ID, event_sink=lambda *_: None, learner_profile='autonomous')
        cells = [{'x': x, 'y': y, 'value': (board[y][x] + 1) % 256}
                 for y in range(2) for x in range(64)]
        guards = [{'x': x, 'y': y, 'value': board[y][x]}
                  for y in range(2) for x in range(64)]
        plan = self.submit([self.step(expect={'cells': cells, 'frame_sha256': 'sha256:' + '0' * 64,
            'state': 'NOT_FINISHED', 'levels_completed': 0}, before={'cells': guards}) for _ in range(20)],
                           stop_on_mismatch=False, stop_on_view_change=False)
        # Use a real bounded data measurement; keep the real Broker's action,
        # mismatch, journal, budget and plan projection paths under test.
        with patch(DETECTOR, return_value=measurement):
            try:
                result = self.solver.execute_plan(plan)
            except ValueError as error:
                self.fail(f'{len(self.engine.calls)} committed actions lost their bounded tool result: {error}')
            self.assertEqual(self.solver.execute_plan(plan), result)
        self.assertLessEqual(len(canonical_bytes(result)), 60 * 1024)
        self.assertEqual((result['applied_count'], result['stop_reason']), (20, 'executed'))
        self.assertEqual(len(self.engine.calls), 20)
        self.assertEqual(len(self.broker.journal), 20)
        self.assertEqual(result['budget']['primitive_actions'], 20)
        self.assertEqual(result['observation_ref']['sequence'], 20)
        self.assertEqual(result['observation']['frame'], [board])
        self.assertEqual(result['unexecuted_steps'], [])
        raw = self.solver._plans['boundary']['result']
        self.assertEqual(len(result['precondition_feedback']), 20)
        for item in result['precondition_feedback']:
            self.assertEqual(item['status'], 'matched')
            self.assertEqual(len(item['expected']['cells']) + item['before_cells_omitted'], 128)
        for index, item in enumerate(result['feedback']):
            facts = item['view_change']
            original = raw['feedback'][index]['view_change']
            for field in ('origin', 'status', 'dx', 'dy', 'exposed_windows',
                          'before_observation_ref', 'after_observation_ref'):
                self.assertEqual(facts[field], original[field])
            self.assertGreater(facts['measurement_fields_omitted'], 0)
            self.assertEqual(facts['measurement_read'], {
                'read_api': 'p7_research.view_change', 'before_sequence': index, 'after_sequence': index + 1})
            self.assertEqual(original['informative_pairs'], measurement['informative_pairs'])
            self.assertNotIn('measurement_fields_omitted', original)
            self.assertEqual(len(item['expected']['cells']) + item['expect_cells_omitted'], 128)
            self.assertEqual(len(item['differences']) + item['differences_omitted'],
                             len(raw['feedback'][index]['differences']))
        current = self.solver.current_context()
        self.assertFalse(current['environment_result_unknown'])
        self.assertFalse(current['processing_blocked'])

    def test_unknown_action_never_calls_detector_or_claims_boundary(self):
        self.engine.raises_on = 1
        with patch(DETECTOR, return_value=CANDIDATE, create=True) as detector:
            result = self.solver.execute_plan(self.submit([self.step(), self.step()]))
        detector.assert_not_called()
        self.assertEqual(result['stop_reason'], 'environment-result-unknown')
        self.assertNotIn('observation_boundary', result)
        self.assertTrue(self.solver.current_context()['environment_result_unknown'])

    def test_hard_stops_win_over_candidate_and_actor_checkpoint(self):
        for reason in ('game-over', 'level-advanced', 'paused'):
            with self.subTest(reason=reason):
                self.engine = _Engine(game_over_after=1 if reason == 'game-over' else None,
                                      level_after=1 if reason == 'level-advanced' else None)
                self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
                self.broker.bind_history('run-1')
                self.solver.broker = self.broker
                self.control.state = 'paused' if reason == 'paused' else 'running'
                with patch(DETECTOR, return_value=CANDIDATE, create=True):
                    result = self.solver.execute_plan(self.submit([
                        self.step(observe_after=True, expect={'cells': [{'x': 0, 'y': 0, 'value': 99}]}),
                        self.step()], name=reason, stop_on_mismatch=False))
                self.assertEqual(result['status'], 'recorded')
                self.assertEqual(result['stop_reason'], reason)
                self.assertNotIn('observation_boundary', result)
