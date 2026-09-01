"""Provider-free truth table for the Prime Core smoke receipt."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from tools.prime_core_smoke import PrimeCoreSmokeResult, verify_prime_core_smoke_result
from tools.run_prime_core_smoke import _core_private_goal, _core_replay_contiguous


def _result(**changes: object) -> PrimeCoreSmokeResult:
    values: dict[str, object] = {
        "terminal": "completed",
        "terminal_count": 1,
        "root_model_selected": True,
        "generated_program_admitted": True,
        "application_succeeded": True,
        "oracle_passed": True,
        "child_target_count": 2,
        "children_started": 2,
        "children_completed": 2,
        "children_deleted": 2,
        "message_delivered": True,
        "message_causality_complete": True,
        "detached_while_active": True,
        "reattached": True,
        "replay_contiguous": True,
        "work_continued_after_attach": True,
        "recursion_policy_enforced": True,
        "control_event_sequence_contiguous": True,
        "observation_health": "healthy",
        "observation_gap_count": 0,
        "cleanup_complete": True,
        "privacy_checks_passed": True,
        "within_budget": True,
    }
    values.update(changes)
    return PrimeCoreSmokeResult(**values)


class PrimeCoreSmokeReceiptTests(unittest.TestCase):
    def test_persistent_core_goal_defers_to_the_direct_stage_instruction(self) -> None:
        goal = _core_private_goal()

        self.assertEqual(
            goal.resolve_text("native-rlm-goal", max_bytes=500),
            "Follow the direct verification instruction. Do not inspect, retry, or "
            "independently extend it. Complete only after a later direct instruction.",
        )
        self.assertIn("first = await rlm", goal.resolve_text("native-rlm-start-input", max_bytes=500))
        self.assertIn("Do not reply or complete until", goal.resolve_text("native-rlm-start-input", max_bytes=500))
        self.assertNotIn("agent_message.send", goal.resolve_text("native-rlm-start-input", max_bytes=500))
        self.assertIn("second = await rlm", goal.resolve_text("native-rlm-continue-input", max_bytes=1000))
        self.assertIn("ping-one", goal.resolve_text("native-rlm-continue-input", max_bytes=1000))
        self.assertNotIn("asterion_control.complete_goal", goal.resolve_text("native-rlm-continue-input", max_bytes=1000))

    def test_replay_requires_post_attach_work_and_healthy_gap_free_observation(self) -> None:
        evidence = SimpleNamespace(
            detach_attached=True,
            work_continued_after_attach=True,
            observation_health="healthy",
            observation_gap_count=0,
        )
        self.assertTrue(_core_replay_contiguous(evidence))
        for changes in (
            {"detach_attached": False},
            {"work_continued_after_attach": False},
            {"observation_health": "degraded"},
            {"observation_gap_count": 1},
        ):
            with self.subTest(changes=changes):
                candidate = SimpleNamespace(**vars(evidence) | changes)
                self.assertFalse(_core_replay_contiguous(candidate))

    def test_complete_closed_result_is_pass(self) -> None:
        receipt = verify_prime_core_smoke_result(_result())

        self.assertEqual(receipt["format"], "asterion.prime-core-smoke-receipt/v1")
        self.assertEqual(receipt["status"], "PASS")
        self.assertNotIn("prompt", receipt)
        self.assertNotIn("answer", receipt)

    def test_each_required_boolean_fails_closed(self) -> None:
        for name in (
            "root_model_selected",
            "generated_program_admitted",
            "application_succeeded",
            "oracle_passed",
            "message_delivered",
            "message_causality_complete",
            "detached_while_active",
            "reattached",
            "replay_contiguous",
            "work_continued_after_attach",
            "recursion_policy_enforced",
            "control_event_sequence_contiguous",
            "cleanup_complete",
            "privacy_checks_passed",
            "within_budget",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    verify_prime_core_smoke_result(_result(**{name: False}))["status"],
                    "External-limited",
                )

    def test_nonhealthy_observation_or_incomplete_children_fail_closed(self) -> None:
        for changes in (
            {"observation_health": "degraded"},
            {"observation_gap_count": 1},
            {"children_started": 1},
            {"children_completed": 1},
            {"children_deleted": 1},
            {"terminal_count": 2},
            {"terminal": "uncertain"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(
                    verify_prime_core_smoke_result(_result(**changes))["status"],
                    "External-limited",
                )
