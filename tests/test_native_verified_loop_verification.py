from __future__ import annotations

import asyncio
import unittest
import json
import subprocess
from pathlib import Path

from asterion.control.authority import BudgetUsage
from asterion.control.providers.native.bounded import NativeBoundedReservation
from asterion.control.providers.native.model import NativeTurnResult
from tools.verify_native_verified_loop import (
    BOUNDED_FEATURE_IDS,
    PROVIDER_FREE_FEATURE_IDS,
    build_native_verified_loop_report,
    run_small_verification,
)


ROOT = Path(__file__).resolve().parents[1]


def _nine_passes() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "scenario_id": scenario_id,
            "feature_id": feature_id,
            "status": "PASS",
            "public_projection_equal": True,
            "provider_operations": 0,
            "model_operations": 0,
            "credential_reads": 0,
            "network_operations": 0,
            "application_operations": 0,
            "upload_operations": 0,
            "redaction_safe": True,
        }
        for scenario_id, feature_id in PROVIDER_FREE_FEATURE_IDS.items()
    )


class TestNativeVerifiedLoopVerification(unittest.TestCase):
    def test_small_verification_has_no_user_provider_or_budget_inputs(self) -> None:
        class Host:
            async def execute(self, reservation: object, request: object) -> object:
                return NativeTurnResult(
                    request.turn_id, (), BudgetUsage(1, 0, 0, 1, 0)
                )

        class Resolver:
            def resolve(self) -> tuple[object, object]:
                return (
                    NativeBoundedReservation(
                        reservation_id="small-verification",
                        provider_digest="1" * 64,
                        model_digest="2" * 64,
                        max_turns=1,
                        max_cost_micros=1,
                        deadline_ms=1,
                    ),
                    Host(),
                )

        report = asyncio.run(run_small_verification(Resolver()))

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["level"], "small-verification")
        self.assertEqual(report["bounded_passed_feature_ids"], list(BOUNDED_FEATURE_IDS))
        self.assertEqual(report["promoted_feature_ids"], [])
        self.assertNotIn("reservation", json.dumps(report))

    def test_provider_free_receipt_cannot_promote_bounded_rows(self) -> None:
        report = build_native_verified_loop_report(
            ROOT,
            observation_runner=_nine_passes,
            bounded_receipt_loader=lambda: None,
        )

        self.assertEqual(
            report["provider_free_passed_feature_ids"],
            list(PROVIDER_FREE_FEATURE_IDS.values()),
        )
        self.assertEqual(report["bounded_required_feature_ids"], list(BOUNDED_FEATURE_IDS))
        self.assertEqual(report["promoted_feature_ids"], [])
        self.assertEqual(report["status"], "INCOMPLETE")

    def test_bounded_cli_without_reservation_is_external_limited_and_safe(self) -> None:
        completed = subprocess.run(
            ["uv", "run", "python", "tools/verify_native_verified_loop.py", "--level", "bounded"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(json.loads(completed.stdout)["status"], "External-limited")


if __name__ == "__main__":
    unittest.main()
