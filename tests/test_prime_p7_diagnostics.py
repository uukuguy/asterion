from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.diagnostics import (
    analyze_model_rounds,
    analyze_trace,
    analyze_trace_snapshot,
    combine_model_round_action_evidence,
)


def noop_then_life_loss_trace():
    directory = tempfile.TemporaryDirectory()
    recorder = PrimeTraceRecorder(Path(directory.name))
    identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
    for sequence in range(3):
        recorder.append(
            "arc.action",
            identities,
            {
                "action": "ACTION1",
                "before_sha256": "state-0",
                "after_sha256": "state-0",
                "information_gain": 0.0,
            },
        )
    recorder.append(
        "arc.action",
        identities,
        {
            "action": "ACTION2",
            "before_sha256": "state-0",
            "after_sha256": "state-1",
            "resource_reset": True,
            "information_gain": 1.0,
        },
    )
    recorder.append("hypothesis.contradicted", identities, {"hypothesis": "private"})
    recorder.seal()
    entries = recorder.entries
    directory.cleanup()
    return entries


class TestPrimeP7Diagnostics(unittest.TestCase):
    def test_model_round_diagnostic_is_bounded_and_guides_followup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
            recorder.append(
                "prime.model.round",
                identities,
                {
                    "round_index": 0,
                    "prompt_bytes": 120,
                    "prompt_sha256": "sha256:" + "a" * 64,
                    "output_bytes": 80,
                    "output_sha256": "sha256:" + "b" * 64,
                    "prompt_signals": ["tool-guidance", "mechanics-prior"],
                    "output_signals": ["plan", "observation"],
                },
            )
            recorder.append(
                "prime.model.round",
                identities,
                {
                    "round_index": 1,
                    "prompt_bytes": 120,
                    "prompt_sha256": "sha256:" + "c" * 64,
                    "output_bytes": 80,
                    "output_sha256": "sha256:" + "d" * 64,
                    "prompt_signals": ["tool-guidance"],
                    "output_signals": ["plan", "action"],
                },
            )
            recorder.seal()
            report = analyze_model_rounds(recorder.entries)
            self.assertEqual(report["round_count"], 2)
            self.assertEqual(report["read_only_rounds"], 1)
            self.assertEqual(report["planned_action_rounds"], 1)
            self.assertEqual(report["recommendation"], "reinforce-hypothesis-to-action-link")
            self.assertNotIn("sentinel", repr(report))

    def test_model_round_snapshot_is_available_before_trace_seal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
            recorder.append(
                "prime.model.round",
                identities,
                {
                    "round_index": 0,
                    "prompt_bytes": 1,
                    "prompt_sha256": "sha256:" + "a" * 64,
                    "output_bytes": 1,
                    "output_sha256": "sha256:" + "b" * 64,
                    "prompt_signals": [],
                    "output_signals": [],
                },
            )
            from asterion.applications.prime.p7.diagnostics import analyze_model_round_snapshot
            report = analyze_model_round_snapshot(recorder.snapshot())
            self.assertEqual(report["round_count"], 1)
            self.assertEqual(report["recommendation"], "require-action-after-planning")
            action_report = analyze_trace_snapshot(recorder.snapshot())
            self.assertEqual(action_report.actions_since_progress, 0)

    def test_repeated_noop_and_resource_reset_are_labeled(self) -> None:
        report = analyze_trace(noop_then_life_loss_trace())

        self.assertGreaterEqual(report.repeated_action_streak, 3)
        self.assertEqual(report.no_op_streak, 3)
        self.assertEqual(report.deaths, 1)
        self.assertEqual(report.contradicted_hypotheses, 1)
        self.assertEqual(report.experiment_information_gain, (0.0, 0.0, 0.0, 1.0))

    def test_analysis_is_deterministic_and_does_not_expose_private_payload(self) -> None:
        entries = noop_then_life_loss_trace()
        self.assertEqual(analyze_trace(entries), analyze_trace(entries))
        self.assertNotIn("private", repr(analyze_trace(entries)))

    def test_model_rounds_force_replan_when_actions_repeat_without_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recorder = PrimeTraceRecorder(Path(directory))
            identities = {"model_id": "deepseek-r1", "reasoning_id": "sol"}
            recorder.append(
                "prime.model.round",
                identities,
                {
                    "round_index": 0,
                    "prompt_bytes": 1,
                    "prompt_sha256": "sha256:" + "a" * 64,
                    "output_bytes": 1,
                    "output_sha256": "sha256:" + "b" * 64,
                    "prompt_signals": ["application-state"],
                    "output_signals": ["plan", "action"],
                },
            )
            for _ in range(20):
                recorder.append(
                    "arc.action",
                    identities,
                    {
                        "action": "ACTION4",
                        "before_sha256": "state-0",
                        "after_sha256": "state-1",
                        "levels_completed": 2,
                    },
                )
            recorder.seal()
            report = combine_model_round_action_evidence(
                analyze_model_rounds(recorder.entries),
                analyze_trace(recorder.entries),
            )
            self.assertEqual(report["repeated_action_streak"], 20)
            self.assertEqual(report["actions_since_progress"], 20)
            self.assertEqual(report["recommendation"], "force-replan-after-no-progress")


class TestSafeFailureLimitProjection(unittest.TestCase):
    def test_limit_projection_is_closed_and_validated(self):
        from dataclasses import asdict, replace
        import json
        from asterion.applications.prime.p7.operator import _safe_failure_diagnostic
        from asterion.services.diagnostics import FailureDiagnostic, LimitDiagnostic
        limit = LimitDiagnostic('witness-frame-limit', 'admission', 'rejected',
                                8193, 8192, 'bytes', 'exact', 'application')
        record = FailureDiagnostic('a' * 32, 'prime.compaction', 'ResourceLimitExceeded',
            'b' * 64, 'c' * 64, limit.limit_code, limit_diagnostic=limit)
        self.assertEqual(_safe_failure_diagnostic(record)['limit_diagnostic'], asdict(limit))
        unsafe = replace(record, limit_diagnostic={'prompt': 'PRIVATE-PROMPT',
            'error': 'PRIVATE-CREDENTIAL', 'path': '/PRIVATE-PATH'})
        self.assertNotIn('limit_diagnostic', _safe_failure_diagnostic(unsafe))
        self.assertNotIn('PRIVATE', json.dumps(_safe_failure_diagnostic(unsafe)))

    def test_final_stdout_ignores_arbitrary_exception_alarm_attributes(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from asterion.applications.prime.p7 import operator
        error = RuntimeError('PRIVATE-ERROR')
        error.resource_alarms = [{'prompt': 'PRIVATE-PROMPT', 'path': '/PRIVATE/PATH'}]
        output = io.StringIO()
        with (patch.object(operator, '_preflight', return_value=SimpleNamespace(game=operator.DEFAULT_GAME)),
              patch.object(operator.live, 'safe_run_id', return_value='p7-test'),
              patch.object(operator, '_run_live_with_process_signals', side_effect=error),
              redirect_stdout(output), redirect_stderr(io.StringIO())):
            self.assertEqual(operator.main([]), 1)
        public = json.loads(output.getvalue())
        self.assertEqual(public['resource_alarms'], [])
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_public_receipt_validates_alarm_shape_and_configuration(self):
        from dataclasses import replace
        from asterion.applications.prime.resource_alarms import resource_alarm
        from asterion.applications.prime.p7 import operator
        from asterion.services.diagnostics import FailureDiagnostic, LimitDiagnostic
        record = FailureDiagnostic('a' * 32, 'prime.compaction', 'ValueError', 'b' * 64,
            None, 'witness-frame-limit', limit_diagnostic=LimitDiagnostic('witness-frame-limit',
                'admission', 'rejected', 2, 1, 'bytes', 'exact', 'application'))
        alarm = resource_alarm(record)
        for bad in ({**alarm, 'prompt': 'PRIVATE-PROMPT'},
                    {**alarm, 'configuration': 'PRIVATE-CONFIG'},
                    {**alarm, 'observed': 'PRIVATE-OBSERVED'},
                    {**alarm, 'diagnostic_id': 'PRIVATE-ID'},
                    {**alarm, 'outcome': 'PRIVATE-OUTCOME'}):
            with self.subTest(fields=set(bad)):
                public = operator._public_receipt('unsuccessful', 'p7-test', resource_alarms=[bad, alarm])
                self.assertEqual(public['resource_alarms'], [alarm])
        self.assertEqual(operator._public_receipt('unsuccessful', 'p7-test', resource_alarms=[alarm])['resource_alarms'], [alarm])
        self.assertIsNone(resource_alarm(replace(record, limit_diagnostic=None)))

    def test_final_stdout_keeps_owned_alarm_for_success_and_attempt_failure(self):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        import json
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from asterion.applications.prime.p7 import operator
        from asterion.applications.prime.resource_alarms import resource_alarm
        from asterion.services.diagnostics import FailureDiagnostic, LimitDiagnostic
        record = FailureDiagnostic('a' * 32, 'prime.compaction', 'ValueError', 'b' * 64,
            None, 'witness-frame-limit', limit_diagnostic=LimitDiagnostic('witness-frame-limit',
                'admission', 'rejected', 2, 1, 'bytes', 'exact', 'application'))
        alarm = resource_alarm(record)
        owned = operator.P7LiveAttemptFailure(primitive_actions=1, levels_completed=0,
            target_level=1, terminal_reason='game-over', replay_verified=False,
            sealed_trace=False, cleanup_complete=True, resource_alarms=(alarm,))
        execution = operator.live.P7LiveExecution(run_id='p7-test', completed_level_count=1,
            primitive_action_count=1, replay_verified=True, sealed_trace=True, cleanup_complete=True,
            trace_root=Path('/PRIVATE/PATH'), receipt={'receipt_sha256': '0' * 64,
                'resource_alarms': [alarm, {**alarm, 'prompt': 'PRIVATE-PROMPT'}]},
            comparison_report=None, game=operator.DEFAULT_GAME, broker_replay_sha256='1' * 64,
            terminal_reason='game-won')
        for outcome in (owned, execution):
            with self.subTest(outcome=type(outcome).__name__):
                output = io.StringIO()
                with (patch.object(operator, '_preflight', return_value=SimpleNamespace(game=operator.DEFAULT_GAME, environment={})),
                      patch.object(operator.live, 'safe_run_id', return_value='p7-test'),
                      patch.object(operator, '_run_live_with_process_signals',
                          **({'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome})),
                      redirect_stdout(output), redirect_stderr(io.StringIO())):
                    self.assertEqual(operator.main([]), 0)
                self.assertEqual(json.loads(output.getvalue())['resource_alarms'], [alarm])
                self.assertNotIn('PRIVATE', output.getvalue())
