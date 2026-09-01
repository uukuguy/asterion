"""Provider-free truth table for the Prime Core smoke receipt."""

from __future__ import annotations

import unittest

from tools.prime_core_smoke import PrimeCoreSmokeResult, verify_prime_core_smoke_result


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
