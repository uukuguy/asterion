"""Current-run case revision checks with the actual registered kernel helpers."""

import contextlib
import io
import inspect
import json
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from asterion.applications.prime.p7 import rollout as helpers
from asterion.applications.prime.p7.rollout_runtime import KERNEL_SOURCE, RolloutRuntime
from asterion.applications.prime.p7.score import digest


ACTION = {'name': 'ACTION1', 'data': {}}


class TestRolloutBacktests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.before = {'run_id': 'run', 'attempt_id': 'attempt', 'level': 1, 'sequence': 0}
        self.after = {**self.before, 'sequence': 1}
        self.context = {'observation_ref': self.before, 'notes_boundary': {'reset_sequence': 0}}
        self.owner = SimpleNamespace(
            _closed=False, kernel=SimpleNamespace(generation='g', status=lambda: {'lost': False}),
            solver=SimpleNamespace(current_context=lambda: self.context),
            control=SimpleNamespace(enter=lambda operation: True, leave=lambda operation: None),
            poll=lambda: {'state': 'running'},
        )
        def committed(sequence):
            ref = self.before if sequence == 0 else self.after
            projection = {'frame': [[[sequence]]], 'state': 'GAME_OVER' if sequence else 'NOT_FINISHED', 'levels_completed': 0}
            return SimpleNamespace(**projection), ref
        self.owner._committed_observation = committed
        self.module = ModuleType('p7_research')
        self.namespace = self.module.__dict__
        self.namespace.update({
            **vars(helpers), '_json': json, 'current': lambda: self.context,
            'replay_deaths': helpers.replay_cases,
        })
        exec(KERNEL_SOURCE, self.namespace)
        self.runtime = RolloutRuntime(self.owner, self.root)
        self.calls = []
        async def cell(code, signal, prefix):
            self.calls.append(prefix)
            with patch.dict('sys.modules', {'p7_research': self.module}), contextlib.redirect_stdout(io.StringIO()) as output:
                exec(code, self.namespace)
            return json.loads(output.getvalue()), 'host:' + str(len(self.calls))
        self.runtime._cell = cell

    def register(self, *, terminal=None, label='local', risk_check=...):
        return self.namespace['register_rollout_model'](
            from_frame=lambda frame, ref: {'tick': 0, 'source_sequence': ref['sequence']},
            transition=lambda state, action: {**state, 'tick': state['tick'] + 1},
            settled=lambda state: True, terminal=terminal or (lambda state: None),
            risk_check=(lambda before, after, action: []) if risk_check is ... else risk_check,
            supported_actions=['ACTION1'], model_id=label,
        )

    def death_feedback(self):
        self.runtime.record_feedback(
            {'status': 'evaluated', 'outcome': 'settled', 'risk': 'no_identified_fatal',
             'model_revision': self.runtime.revision(self.runtime.registration),
             'frame_sha256': digest([[0]])}, self.before, self.after, ACTION, 'GAME_OVER',
        )

    async def test_renaming_rechecks_and_revision_correction_matches_without_retaining_historical_fatal(self):
        self.assertTrue(callable(getattr(self.runtime, 'snapshot_backtest', None)))
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        self.death_feedback()
        self.context['observation_ref'] = self.after
        self.register(label='renamed')
        await self.runtime.collect_actor_calls(None, 'actor:renamed')
        summary = self.runtime.snapshot_backtest()
        self.assertEqual((summary['status'], summary['case_count'], summary['unresolved_count']), ('contradicted', 1, 1))
        self.assertEqual(summary['cases'][0]['before_observation_ref'], self.before)
        self.assertNotEqual(self.runtime.model_case_status(summary['model_revision']), 'not_checked')
        self.namespace['_last_auto_rollout_result'] = {'sentinel': 'current-only'}
        self.register(terminal=lambda state: 'dead' if state['tick'] else None)
        await self.runtime.collect_actor_calls(None, 'actor:corrected')
        summary = self.runtime.snapshot_backtest()
        self.assertEqual((summary['status'], summary['unresolved_count']), ('matched', 0))
        self.assertEqual(self.namespace['_last_auto_rollout_result'], {'sentinel': 'current-only'})
        self.assertEqual(self.runtime.retained_fatal_risks, [])
        self.assertEqual(self.runtime.auto_attempts, 0)
        records = [json.loads(line) for line in (self.runtime.root / 'calls.jsonl').read_text().splitlines()]
        self.assertEqual(sum(item.get('origin') == 'host_backtest' for item in records), 2)

    async def test_plan_claim_stays_distinct_unresolved_and_survives_same_root_recovery(self):
        self.assertIn('step_feedback', inspect.signature(self.runtime.record_feedback).parameters)
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        feedback = {'expected': {'cells': [{'x': 0, 'y': 0, 'value': 9}]},
                    'differences': [{'field': 'cell', 'x': 0, 'y': 0, 'expected': 9, 'actual': 1}],
                    'actual': {'state': 'NOT_FINISHED', 'frame_sha256': digest([[1]])}}
        record = self.runtime.record_feedback(
            {'model_revision': self.runtime.revision(self.runtime.registration), 'frame_sha256': digest([[0]])},
            self.before, self.after, ACTION, 'NOT_FINISHED', step_feedback=feedback,
        )
        self.assertEqual(record['type'], 'plan_expectation_mismatch')
        self.assertEqual(record['expected'], feedback['expected'])
        recovered = RolloutRuntime(self.owner, self.root)
        recovered._cell = self.runtime._cell
        self.context['observation_ref'] = self.after
        self.context['notes_boundary']['reset_sequence'] = 1
        self.register(label='after-reset')
        await recovered.collect_actor_calls(None, 'actor:reset')
        summary = recovered.snapshot_backtest()
        self.assertEqual((summary['status'], summary['case_count'], summary['unresolved_count']), ('not_comparable', 1, 1))
        self.assertEqual(summary['cases'][0]['type'], 'plan_expectation_mismatch')
        self.assertEqual(summary['cases'][0]['differences'], feedback['differences'])
        self.assertEqual(self.namespace['_registered_rollout_model']['boundary']['reset_sequence'], 1)

    async def test_case_version_recheck_missing_frame_and_run_scope(self):
        self.assertTrue(callable(getattr(self.runtime, 'snapshot_backtest', None)))
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        self.owner._committed_observation = lambda sequence: (_ for _ in ()).throw(ValueError('unavailable'))
        self.death_feedback()
        self.register(label='next')
        await self.runtime.collect_actor_calls(None, 'actor:next')
        summary = self.runtime.snapshot_backtest()
        self.assertEqual((summary['status'], summary['case_count'], summary['unresolved_count']), ('unavailable', 1, 1))
        self.context['observation_ref'] = {**self.after, 'run_id': 'another-run'}
        self.assertEqual(self.runtime.snapshot_backtest()['case_count'], 0)

    async def test_initial_terminal_does_not_match_unexecuted_historical_action(self):
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        self.death_feedback()
        self.context['observation_ref'] = self.after
        self.register(terminal=lambda state: 'dead')
        await self.runtime.collect_actor_calls(None, 'actor:initial-dead')
        summary = self.runtime.snapshot_backtest()
        self.assertEqual((summary['status'], summary['unresolved_count']), ('unknown', 1))
        self.assertEqual(summary['cases'][0]['reason'], 'initial_terminal_no_transition')

    async def test_partial_death_backtest_retains_risk_and_coverage_without_terminal_claim(self):
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        self.death_feedback()
        fatal = {'id': 'view-fatal', 'type': 'conditional_fatal',
                 'condition': 'contact may be fatal', 'evidence': 'declared model finding'}
        for findings, expected_risk in (([], 'unassessed'), ([fatal], 'conditional_fatal')):
            with self.subTest(risk=expected_risk):
                self.register(risk_check=lambda before, after, action: {
                    'findings': findings, 'coverage': 'unknown',
                    'reason': 'outside modeled view', 'gap_kind': 'view_boundary',
                })
                await self.runtime.collect_actor_calls(None, 'actor:partial')
                summary = self.runtime.snapshot_backtest()
                case = summary['cases'][0]
                self.assertEqual((summary['status'], summary['unresolved_count']), ('unknown', 1))
                self.assertEqual((case['predicted_outcome'], case['predicted_risk']), ('settled', expected_risk))
                self.assertEqual(case['reason'], 'risk_assessment_incomplete')
                self.assertTrue(case['coverage']['partial'])
                self.assertEqual(case['coverage']['gaps'][0]['kind'], 'view_boundary')
                self.assertEqual(case['findings'], findings)
                artifact = self.runtime.root / (case['result_artifact_id'][7:] + '.json.zlib')
                raw = json.loads(zlib.decompress(artifact.read_bytes()))
                self.assertEqual(raw['risk']['status'], case['predicted_risk'])
                self.assertEqual(raw['risk']['coverage'], case['coverage'])
                recorded = [json.loads(line) for line in (self.runtime.root / 'calls.jsonl').read_text().splitlines()]
                recheck = [item for item in recorded if item.get('origin') == 'host_backtest'][-1]
                self.assertEqual(recheck['predicted_risk'], expected_risk)
                self.assertEqual(recheck['coverage'], case['coverage'])
                self.assertEqual(self.runtime.retained_fatal_risks, [])

    async def test_probe_death_with_unassessed_settled_outcome_is_not_a_safe_prediction_mismatch(self):
        coverage = {'checker_supplied': True, 'evaluated_ticks': 0, 'unassessed_ticks': 1,
                    'partial': True, 'errors': [], 'action_coverage': 'declared',
                    'gaps': [{'kind': 'contact_unmodeled'}], 'gaps_omitted': 0}
        for risk_fields in ({'risk': 'unassessed', 'coverage': coverage},
                            {'risk': {'status': 'unassessed', 'coverage': coverage}}):
            with self.subTest(risk=risk_fields['risk']):
                record = self.runtime.record_feedback(
                    {'status': 'evaluated', 'outcome': 'settled', **risk_fields,
                     'result_artifact_id': 'sha256:original'},
                    self.before, self.after, ACTION, 'GAME_OVER',
                )
                self.assertEqual(record['type'], 'death_not_assessed')
                self.assertEqual(record['coverage'], coverage)
                self.assertEqual(record['full_trace_ref'], 'sha256:original')
        case = self.runtime.snapshot_backtest()['cases'][0]
        self.assertEqual(case['predicted_risk'], 'unassessed')
        self.assertEqual(case['coverage'], coverage)

    async def test_partial_terminal_death_remains_unresolved_with_raw_death_prediction(self):
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        self.death_feedback()
        self.register(terminal=lambda state: 'dead' if state['tick'] else None,
                      risk_check=lambda before, after, action: {
                          'findings': [], 'coverage': 'unknown',
                          'reason': 'contact unknown', 'gap_kind': 'contact_unmodeled',
                      })
        await self.runtime.collect_actor_calls(None, 'actor:partial-dead')
        summary = self.runtime.snapshot_backtest()
        case = summary['cases'][0]
        self.assertEqual((summary['status'], summary['unresolved_count']), ('unknown', 1))
        self.assertEqual((case['predicted_outcome'], case['predicted_risk']), ('dead', 'predicted_death'))
        self.assertTrue(case['coverage']['partial'])

    async def test_death_witness_does_not_cross_run_when_same_root_is_recovered(self):
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        self.death_feedback()
        recovered = RolloutRuntime(self.owner, self.root)
        reference = {**self.before, 'run_id': 'another-run'}
        result = recovered.evaluate({'frame': [[[0]]]}, reference, ACTION)
        self.assertEqual(result['risk'], 'unassessed')

    async def test_death_and_plan_claim_remain_separate_after_death_prediction_is_corrected(self):
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        feedback = {'expected': {'frame_sha256': digest([[9]])},
                    'differences': [{'field': 'frame_sha256', 'expected': digest([[9]]), 'actual': digest([[1]])}]}
        result = self.runtime.record_feedback(
            {'status': 'evaluated', 'outcome': 'settled', 'risk': 'no_identified_fatal',
             'model_revision': self.runtime.revision(self.runtime.registration), 'frame_sha256': digest([[0]])},
            self.before, self.after, ACTION, 'GAME_OVER', step_feedback=feedback,
        )
        self.assertEqual(result['type'], 'model_mismatch')
        self.assertIn('related_plan_claim_case_id', result)
        self.register(terminal=lambda state: 'dead' if state['tick'] else None)
        await self.runtime.collect_actor_calls(None, 'actor:corrected')
        summary = self.runtime.snapshot_backtest()
        self.assertEqual((summary['case_count'], summary['unresolved_count']), (2, 1))
        self.assertEqual({case['status'] for case in summary['cases']}, {'matched', 'not_comparable'})

    async def test_cancelled_backtest_balances_control_and_bounded_summary_counts_all_cases(self):
        self.register()
        await self.runtime.collect_actor_calls(None, 'actor:first')
        events = []
        self.owner.control = SimpleNamespace(
            enter=lambda operation: events.append('enter') or True,
            leave=lambda operation: events.append('leave'),
        )
        for sequence in range(35):
            self.runtime.record_feedback(
                {'frame_sha256': digest([[0]])}, {**self.before, 'sequence': sequence},
                {**self.after, 'sequence': sequence + 1}, ACTION, 'GAME_OVER',
            )
        self.owner._closed = True
        await self.runtime.collect_actor_calls(None, 'actor:cancelled')
        summary = self.runtime.snapshot_backtest()
        self.assertEqual(events, [])
        self.assertEqual((summary['case_count'], summary['unresolved_count'], summary['omitted_cases']), (35, 35, 3))
        self.assertEqual(len(summary['cases']), 32)
        self.assertNotIn('p7-backtest-', self.calls)


if __name__ == '__main__':
    unittest.main()
