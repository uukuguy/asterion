"""Autonomous research choices preserve real action authority."""
import copy
from pathlib import Path

from asterion.applications.prime.p7.broker import ArcBroker
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.solver import Solver
from asterion.applications.prime.p7.dynamic_evidence import ArcBrokerError, EvidenceProcessingError
from asterion.applications.prime.p7.transition_model import ActionExpectation
from unittest.mock import patch
from tests.test_prime_p7_solver import P7SolverFixture
from tests.test_prime_p7_guard_probe import _NoEffectClickEngine


class TestP7AutonomousSolver(P7SolverFixture):
    def setUp(self):
        super().setUp()
        self.broker = ArcBroker(engine=self.engine, action_profile='autonomous')
        self.broker.bind_history('run-1')
        self.solver = Solver(broker=self.broker, kernel=self.kernel, control=self.control,
            workspace_root=Path(self.directory.name), run_id='run-1', attempt_id='attempt-1',
            event_sink=lambda kind, payload: self.events.append((kind, payload)), learner_profile='autonomous')

    def minimal(self, name='plan-1', steps=None, **options):
        return {'plan_id': name, 'start': self.solver.current_context()['observation_ref'],
                'steps': steps or [{'action': {'name': 'ACTION1', 'data': {}}}], **options}

    def test_minimal_unpredicted_action_needs_no_notes_or_compute_kernel(self):
        self.kernel.lost = True
        result = self.solver.execute_plan(self.minimal())
        self.assertEqual(result['status'], 'recorded')
        self.assertEqual(result['applied_count'], 1)
        self.assertEqual(result['stop_reason'], 'executed')
        self.assertFalse(result['feedback'][0]['prediction_present'])
        self.assertEqual(result['feedback'][0]['mismatch_kind'], 'unknown')
        self.assertFalse(result['needs_revision'])

    def test_supplied_stale_revision_reference_and_invalid_tail_never_dispatch(self):
        current = self.minimal()
        variants = [dict(current, workspace_revision='sha256:'+'f'*64),
                    dict(current, start=dict(current['start'], sequence=10)),
                    dict(current, steps=current['steps']+[{'action': {'name': 'ACTION6', 'data': {'x': -1, 'y': 2}}}])]
        for plan in variants:
            with self.subTest(plan=plan):
                self.assertEqual(self.solver.execute_plan(plan)['status'], 'rejected')
        self.assertEqual(self.engine.calls, [])

    def test_known_mismatch_can_stop_or_continue_without_revision_gate(self):
        steps = [{'action': {'name': 'ACTION1', 'data': {}},
                  'expect': {'cells': [{'x': 0, 'y': 0, 'value': 99}]}},
                 {'action': {'name': 'ACTION1', 'data': {}}}]
        stopped = self.solver.execute_plan(self.minimal(steps=steps))
        self.assertEqual(stopped['status'], 'recorded')
        self.assertEqual((stopped['applied_count'], stopped['stop_reason']), (1, 'prediction-mismatch'))
        self.assertFalse(stopped['needs_revision'])
        continued = self.solver.execute_plan(self.minimal('next', steps=steps, stop_on_mismatch=False))
        self.assertEqual((continued['applied_count'], continued['stop_reason']), (2, 'executed'))
        self.assertEqual(continued['feedback'][0]['mismatch_kind'], 'state')
        self.assertFalse(continued['feedback'][1]['prediction_present'])

    def test_idempotent_minimal_submission_and_unknown_effect_halt(self):
        plan = self.minimal()
        first = self.solver.execute_plan(plan)
        self.assertEqual(first['status'], 'recorded')
        self.assertEqual(first['applied_count'], 1)
        self.assertEqual(self.solver.execute_plan(plan), first)
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(self.solver.execute_plan(dict(plan, steps=plan['steps']*2))['status'], 'rejected')
        def uncertain(*args):
            raise RuntimeError('private engine error')
        self.engine.step = uncertain
        result = self.solver.execute_plan(self.minimal('uncertain'))
        self.assertEqual(result['stop_reason'], 'environment-result-unknown')
        self.assertEqual(self.solver.execute_plan(self.minimal('after'))['status'], 'rejected')
        self.assertTrue(self.solver.current_context()['environment_result_unknown'])

    def test_autonomous_broker_records_no_effect_without_coordinate_or_novelty_gate(self):
        engine = _NoEffectClickEngine()
        broker = ArcBroker(engine=engine, game=P7GameSelection('ls20-9607627b', 0, 2), action_profile='autonomous')
        broker.bind_history('autonomous-observations')
        step = {'action': {'name': 'ACTION6', 'data': {'x': 1, 'y': 1}}, 'expect': {}}
        for _ in range(36):
            result = broker.act_checked([copy.deepcopy(step)])
            self.assertEqual((result['applied_count'], result['stop_reason']), (1, 'executed'))
            self.assertTrue(result['feedback'][0]['no_effect'])
            self.assertFalse(result['feedback'][0]['prediction_present'])
        self.assertEqual(len(engine.calls), 36)
        self.assertEqual(broker.last_outcome_summary()['attempts']['ACTION6'], 36)
        self.assertEqual(broker.last_outcome_summary()['no_effect']['ACTION6'], 3)
        self.assertEqual(broker.experience_diagnostics()['prediction_matches'], 0)
        engine.advance_on_move = True
        broker.act_checked([{'action': {'name': 'ACTION1', 'data': {}}, 'expect': {}}])
        result = broker.act_checked([step])
        self.assertEqual(result['applied_count'], 1)

    def test_optional_predictions_still_validate_when_supplied(self):
        for expect in ({'state': 'NOT_FINISHED'}, {'levels_completed': 0}, {}):
            with self.subTest(expect=expect):
                result = self.solver.execute_plan(self.minimal(str(len(self.engine.calls)), steps=[
                    {'action': {'name': 'ACTION1', 'data': {}}, 'expect': expect}]))
                self.assertEqual(result['status'], 'recorded')
                self.assertEqual(result['applied_count'], 1)
        malformed = self.minimal('bad', steps=[{'action': {'name': 'ACTION1', 'data': {}},
                                             'expect': {'cells': [{'x': 0, 'y': 0, 'value': True}]}}])
        self.assertEqual(self.solver.execute_plan(malformed)['status'], 'rejected')

    def test_reset_and_level_change_stop_suffix_without_mandatory_revision(self):
        self.engine.level_after = 1
        self.broker = ArcBroker(engine=self.engine, game=P7GameSelection(self.engine.game_id, 0, 2),
                                action_profile='autonomous')
        self.broker.bind_history('run-1')
        self.solver.broker = self.broker
        action = {'action': {'name': 'ACTION1', 'data': {}}}
        advance = self.solver.execute_plan(self.minimal('advance', steps=[action, action]))
        self.assertEqual((advance['applied_count'], advance['stop_reason']), (1, 'level-advanced'))
        self.assertFalse(advance['needs_revision'])
        self.assertEqual(self.solver.execute_plan(self.minimal('after-advance'))['applied_count'], 1)
        reset = self.solver.execute_plan(self.minimal('reset', steps=[
            {'action': {'name': 'RESET', 'data': {}}}, action]))
        self.assertEqual((reset['applied_count'], reset['stop_reason']), (1, 'reset-applied'))
        self.assertFalse(reset['needs_revision'])
        self.solver.kernel_recovered()
        self.assertFalse(self.solver.current_context()['requires_calibration'])
        self.assertEqual(self.solver.execute_plan(self.minimal('after-reset'))['applied_count'], 1)

    def test_pause_and_final_guard_rejection_retain_unexecuted_current_step(self):
        self.control.state = 'paused'
        result = self.solver.execute_plan(self.minimal('paused'))
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'paused'))
        self.assertEqual(len(result['unexecuted_steps']), 1)
        self.control.state = 'running'
        failure = EvidenceProcessingError('action-not-dispatched', stage='not-dispatched', outcome_known=True)
        with patch.object(self.broker, 'act_checked', side_effect=failure):
            result = self.solver.execute_plan(self.minimal('guard'))
        self.assertEqual(result['applied_count'], 0)
        self.assertEqual(len(result['unexecuted_steps']), 1)
        self.assertFalse(self.solver.current_context()['environment_result_unknown'])

    def test_certified_replay_requires_predictions_and_exact_before_state(self):
        witness = ActionExpectation(action='ACTION1', data=(), prior_state_sha256='sha256:'+'1'*64,
            after_state_sha256='sha256:'+'2'*64, after_frame_sha256='sha256:'+'3'*64,
            changed_cells=(), levels_completed=0, state='NOT_FINISHED')
        with self.assertRaises(ArcBrokerError):
            self.broker.act_checked([{'action': {'name': 'ACTION1', 'data': {}}, 'expect': {}}],
                                    replay_expectations=(witness,))
        result = self.broker.act_checked([{'action': {'name': 'ACTION1', 'data': {}},
                                          'expect': {'frame_sha256': 'sha256:'+'4'*64}}],
                                         replay_expectations=(witness,))
        self.assertEqual((result['applied_count'], result['stop_reason']), (0, 'route-expectation-mismatch'))
        self.assertEqual(self.engine.calls, [])
