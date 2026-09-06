from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest


class TestP6DevelopmentReceipt(unittest.TestCase):
    def _receipt(self, *, outcome: str = "preserved", **changes: object) -> object:
        from asterion.applications.prime_agent.operator import (
            p6_development_workload as workload,
        )
        from asterion.applications.prime_agent.operator.p6_development_receipt import (
            P6DevelopmentReceipt,
        )

        branch = workload.p6_development_branch_facts(outcome)
        values: dict[str, object] = {
            "workload_sha256": workload.P6_DEVELOPMENT_WORKLOAD_DIGEST,
            "schema_sha256": workload.P6_DEVELOPMENT_SCHEMA_DIGEST,
            "model_sha256": workload.P6_DEVELOPMENT_MODEL_DIGEST,
            "oracle_sha256": workload.P6_DEVELOPMENT_ORACLE_DIGEST,
            "baseline_source_sha256": workload.P6_DEVELOPMENT_BASELINE_SNAPSHOT_SHA256,
            "candidate_source_sha256": workload.P6_DEVELOPMENT_CANDIDATE_SNAPSHOT_SHA256,
            "task_a_result_sha256": workload.P6_DEVELOPMENT_TASK_A_RESULT_SHA256,
            "holdout_result_sha256": branch["holdout_result_sha256"],
            "final_source_sha256": branch["final_source_sha256"],
            "outcome_sha256": branch["outcome_sha256"],
            "run_sha256": "sha256:" + "1" * 64,
            "session_sha256": "sha256:" + "2" * 64,
            "container_sha256": "sha256:" + "3" * 64,
            "image_sha256": "sha256:" + "4" * 64,
            "usage_sha256": "sha256:" + "5" * 64,
            "project_scope_sha256": "sha256:" + "6" * 64,
            "baseline_harness_snapshot_sha256": "sha256:" + "7" * 64,
            "candidate_harness_snapshot_sha256": "sha256:" + "8" * 64,
            "final_harness_snapshot_sha256": (
                "sha256:" + ("7" if outcome == "rolled-back" else "8") * 64
            ),
            "proposal_sha256": "sha256:" + "9" * 64,
            "candidate_revision_sha256": "sha256:" + "a" * 64,
            "rollback_revision_sha256": (
                "sha256:" + "b" * 64 if outcome == "rolled-back" else None
            ),
            "scope_kind": "project",
            "tool_names": ("ipython",),
            "prompt_count": 3,
            "provider_callback_count": 6,
            "ipython_call_count": 3,
            "candidate_count": 1,
            "holdout_count": 1,
            "rollback_count": branch["rollback_count"],
            "outcome": outcome,
            "terminal": True,
            "full_cleanup": True,
        }
        values.update(changes)
        return P6DevelopmentReceipt(**values)

    def test_accepts_exact_preserve_and_rollback_branches(self) -> None:
        from asterion.applications.prime_agent.operator.p6_development_receipt import (
            validate_p6_development_receipt,
        )

        preserved = self._receipt()
        rolled_back = self._receipt(outcome="rolled-back")
        validate_p6_development_receipt(preserved)
        validate_p6_development_receipt(rolled_back)
        self.assertNotEqual(preserved.trace_sha256, rolled_back.trace_sha256)
        self.assertRegex(preserved.trace_sha256, r"\Asha256:[0-9a-f]{64}\Z")

    def test_rejects_branch_mismatch_bool_counts_and_private_fields(self) -> None:
        from asterion.applications.prime_agent.operator.p6_development_receipt import (
            P6DevelopmentReceiptError,
            validate_p6_development_receipt,
        )

        for receipt in (
            self._receipt(rollback_count=1),
            self._receipt(outcome="rolled-back", rollback_count=0),
            self._receipt(final_harness_snapshot_sha256="sha256:" + "0" * 64),
            self._receipt(provider_callback_count=True),
        ):
            with self.subTest(receipt=receipt), self.assertRaises(P6DevelopmentReceiptError):
                validate_p6_development_receipt(receipt)
        receipt = self._receipt()
        object.__setattr__(receipt, "private", "P6-PRIVATE-SENTINEL")
        with self.assertRaises(P6DevelopmentReceiptError):
            validate_p6_development_receipt(receipt)
        self.assertNotIn("P6-PRIVATE-SENTINEL", repr(receipt))
        with self.assertRaises(FrozenInstanceError):
            receipt.outcome = "rolled-back"  # type: ignore[misc]
