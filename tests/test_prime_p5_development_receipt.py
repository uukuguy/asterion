from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest


def _digest(char: str) -> str:
    return "sha256:" + char * 64


class TestP5DevelopmentReceipt(unittest.TestCase):
    def _receipt(self, **changes: object) -> object:
        from asterion.applications.prime_agent.operator.p5_development_receipt import (
            P5DevelopmentReceipt,
        )
        from asterion.applications.prime_agent.operator.p5_development_workload import (
            P5_DEVELOPMENT_MODEL_DIGEST,
            P5_DEVELOPMENT_ORACLE_DIGEST,
            P5_DEVELOPMENT_SCHEMA_DIGEST,
            P5_DEVELOPMENT_WORKLOAD_DIGEST,
        )

        values: dict[str, object] = {
            "workload_sha256": P5_DEVELOPMENT_WORKLOAD_DIGEST,
            "schema_sha256": P5_DEVELOPMENT_SCHEMA_DIGEST,
            "model_sha256": P5_DEVELOPMENT_MODEL_DIGEST,
            "oracle_sha256": P5_DEVELOPMENT_ORACLE_DIGEST,
            "goal_sha256": _digest("1"),
            "session_sha256": _digest("2"),
            "container_sha256": _digest("3"),
            "image_sha256": _digest("d"),
            "initial_snapshot_sha256": _digest("4"),
            "repaired_snapshot_sha256": _digest("5"),
            "first_result_sha256": _digest("6"),
            "second_result_sha256": _digest("7"),
            "first_quality_sha256": _digest("8"),
            "second_quality_sha256": _digest("9"),
            "feedback_sha256": _digest("a"),
            "artifact_sha256": _digest("b"),
            "usage_sha256": _digest("c"),
            "prompt_count": 2,
            "provider_callback_count": 4,
            "ipython_call_count": 2,
            "result_gate_count": 2,
            "quality_gate_count": 2,
            "feedback_count": 1,
            "repair_count": 1,
            "retry_count": 0,
            "child_count": 0,
            "compact_count": 0,
            "same_goal": True,
            "same_session": True,
            "same_container": True,
            "first_result_passed": True,
            "second_result_passed": True,
            "first_quality_failed": True,
            "second_quality_passed": True,
            "workspace_changed": True,
            "full_cleanup": True,
        }
        values.update(changes)
        return P5DevelopmentReceipt(**values)

    def test_accepts_only_the_fixed_two_gate_receipt(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_receipt import (
            validate_p5_development_receipt,
        )

        validate_p5_development_receipt(self._receipt())

    def test_rejects_bool_count_and_private_field(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_receipt import (
            P5DevelopmentReceiptError,
            validate_p5_development_receipt,
        )

        for field, value in (
            ("provider_callback_count", True),
            ("first_quality_failed", False),
            ("retry_count", 1),
        ):
            with self.subTest(field=field):
                with self.assertRaises(P5DevelopmentReceiptError):
                    validate_p5_development_receipt(self._receipt(**{field: value}))
        receipt = self._receipt()
        object.__setattr__(receipt, "private", "P5-PRIVATE-SENTINEL")
        with self.assertRaises(P5DevelopmentReceiptError):
            validate_p5_development_receipt(receipt)
        self.assertNotIn("P5-PRIVATE-SENTINEL", repr(receipt))
        with self.assertRaises(FrozenInstanceError):
            receipt.full_cleanup = False
