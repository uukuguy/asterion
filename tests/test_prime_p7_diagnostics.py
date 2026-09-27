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
