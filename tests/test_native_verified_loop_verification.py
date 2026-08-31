from __future__ import annotations

import unittest
from pathlib import Path

from tools.verify_native_verified_loop import (
    BOUNDED_FEATURE_IDS,
    PROVIDER_FREE_FEATURE_IDS,
    build_native_verified_loop_report,
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


if __name__ == "__main__":
    unittest.main()
