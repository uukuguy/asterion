from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from asterion.control.authority import BudgetUsage
from tools.prime_native_rlm_experiment import (
    PrimeRlmExperimentError,
    prepare_native_rlm_experiment,
    write_native_rlm_experiment_receipt,
)


def _authority(**changes: object) -> dict[str, object]:
    authority: dict[str, object] = {
        "authority_id": "authority-1",
        "revision": 1,
        "allowed_portfolio": [
            {
                "provider_id": "example.provider",
                "application_id": "alpha",
                "version": "1.0.0",
                "runtime_id": "fake.runtime",
            }
        ],
        "allowed_operations": [
            "application.invoke",
            "checkpoint.create",
            "child.cancel",
            "child.message",
            "child.spawn",
            "goal.complete",
            "goal.fail",
            "rlm.child.delete",
            "rlm.child.message",
            "rlm.child.spawn",
        ],
        "budget_limit": {
            "controller_tokens": 100,
            "application_tokens": 100,
            "child_tokens": 100,
            "aggregate_tokens": 300,
            "cost_micros": 500_000,
        },
        "expires_at_ms": 100_000,
        "max_action_deadline_ms": 600_000,
        "max_recursion_depth": 1,
        "max_concurrent_children": 1,
        "execution_domain": "trusted-local",
        "host_service_grants": ["artifact.write"],
        "cancelled": False,
    }
    authority.update(changes)
    return {"format": "asterion.prime-bounded-authorization/v1", "authority": authority}


class TestNativeRlmExperiment(unittest.TestCase):
    def test_preparation_binds_private_model_as_a_digest_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")

            reservation = prepare_native_rlm_experiment(
                authority,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"},
                now_ms=1_000,
            )

            self.assertEqual(reservation.limits.cost_micros, 500_000)
            self.assertEqual(reservation.limits.deadline_ms, 600_000)
            self.assertEqual(len(reservation.configuration_digest), 64)
            self.assertFalse(reservation.consumed)
            self.assertTrue(reservation.consume().consumed)

    def test_preparation_rejects_invalid_limits_model_and_reuse_without_leaking(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")
            invalid = (
                ({}, 500_000, 600_000),
                ({"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"}, 500_001, 600_000),
                ({"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"}, 500_000, 600_001),
            )
            for environ, cost, deadline in invalid:
                with self.subTest(environ=environ, cost=cost, deadline=deadline), self.assertRaises(
                    PrimeRlmExperimentError
                ) as raised:
                    prepare_native_rlm_experiment(
                        authority,
                        max_cost_micros=cost,
                        deadline_ms=deadline,
                        environ=environ,
                        now_ms=1_000,
                    )
                self.assertNotIn("private-model", str(raised.exception))
            reservation = prepare_native_rlm_experiment(
                authority,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"},
                now_ms=1_000,
            ).consume()
            with self.assertRaises(PrimeRlmExperimentError):
                reservation.consume()

    def test_receipt_requires_complete_bounded_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")
            reservation = prepare_native_rlm_experiment(
                authority,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"},
                now_ms=1_000,
            ).consume()

            report = write_native_rlm_experiment_receipt(
                root,
                reservation,
                terminal="completed",
                child_started=True,
                message_delivered=True,
                child_deleted=True,
                usage=BudgetUsage(1, 1, 1, 3, 3),
            )

            self.assertEqual(report["status"], "PASS")
            self.assertNotIn("private-model", repr(report))
            receipt = root / "native-rlm-experiment-receipt.json"
            self.assertEqual(os.stat(receipt).st_mode & 0o777, 0o600)
            self.assertNotIn("private-model", receipt.read_text(encoding="utf-8"))
            for changes in (
                {"child_deleted": False},
                {"terminal": "uncertain"},
                {"usage": BudgetUsage(1, 1, 1, 3, 500_001)},
            ):
                with self.subTest(changes=changes):
                    arguments = {
                        "child_started": True,
                        "message_delivered": True,
                        "child_deleted": True,
                        "terminal": "completed",
                        "usage": BudgetUsage(1, 1, 1, 3, 3),
                    }
                    arguments.update(changes)
                    self.assertNotEqual(
                        write_native_rlm_experiment_receipt(
                            root, reservation, **arguments,
                        )["status"],
                        "PASS",
                    )
