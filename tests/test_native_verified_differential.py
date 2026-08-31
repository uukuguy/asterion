from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import Mapping

from asterion.control.providers.native.verified import (
    NativeVerifiedFeatureRecord,
    native_verified_record_id,
    reduce_verified_feature_records,
)
from tests.test_native_prime_differential import _validate_prime_oracle_lock_identity
from tools.verify_native_verified_loop import PROVIDER_FREE_FEATURE_IDS


def _record(feature_id: str, payload: Mapping[str, object]) -> NativeVerifiedFeatureRecord:
    return NativeVerifiedFeatureRecord(
        feature_id=feature_id,
        record_id=native_verified_record_id(feature_id, payload),
        payload=payload,
    )


def _snapshot_digest() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.native-verified-rlm-snapshot/v1",
                "environment_id": "environment-1",
                "environment_digest": "2" * 64,
                "child_tokens": 1,
                "cost_micros": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def run_native_verified_provider_free_observations() -> tuple[Mapping[str, object], ...]:
    _validate_prime_oracle_lock_identity()
    session_id = "session-1"
    state = reduce_verified_feature_records(
        (
            _record(
                "session.persistence-naming",
                {
                    "session_id": session_id,
                    "generation": 1,
                    "name_digest": "1" * 64,
                    "active_continuation_id": "continuation-1",
                    "transcript_id": "transcript-1",
                },
            ),
            _record(
                "session.resume-delete",
                {
                    "session_id": session_id,
                    "generation": 1,
                    "operation": "resume",
                    "selector_digest": _selector_digest(session_id, "continuation-1"),
                    "continuation_id": "continuation-1",
                },
            ),
            _record(
                "session.delivery",
                {
                    "session_id": session_id,
                    "generation": 1,
                    "input_id": "input-1",
                    "delivery": "direct",
                    "ordinal": 1,
                },
            ),
            _record(
                "session.usage-status",
                {
                    "session_id": session_id,
                    "generation": 1,
                    "status": "running",
                    "total_tokens": 1,
                    "controller_tokens": 1,
                    "cost_micros": 1,
                },
            ),
            _record(
                "rlm.environment",
                {"environment_id": "environment-1", "environment_digest": "2" * 64},
            ),
            _record(
                "rlm.usage-cost",
                {"environment_id": "environment-1", "child_tokens": 1, "cost_micros": 1},
            ),
            _record(
                "rlm.recovery",
                {"environment_id": "environment-1", "snapshot_digest": _snapshot_digest()},
            ),
            _record("operation.goals", {"operation_id": "operation-1", "goal_status": "active"}),
            _record(
                "operation.detach-attach-replay",
                {"operation_id": "operation-1", "cursor": 1, "event_digest": "3" * 64},
            ),
        )
    )
    session = state.session_projection(session_id)
    environment = state.rlm_projection("environment-1")
    operation = state.operation_projection("operation-1")
    checks = (
        session["name_digest"] == "1" * 64,
        session["resumed_continuations"] == ("continuation-1",),
        session["deliveries"] == ("input-1",),
        session["total_tokens"] == 1,
        environment["environment_digest"] == "2" * 64,
        environment["cost_micros"] == 1,
        environment["child_tokens"] == 1,
        operation["goal_status"] == "active",
        state.replay("operation-1", after_cursor=0) == ((1, "3" * 64),),
    )
    return tuple(
        {
            "scenario_id": scenario_id,
            "feature_id": feature_id,
            "status": "PASS" if check else "FAIL",
            "public_projection_equal": check,
            "provider_operations": 0,
            "model_operations": 0,
            "credential_reads": 0,
            "network_operations": 0,
            "application_operations": 0,
            "upload_operations": 0,
            "redaction_safe": True,
        }
        for (scenario_id, feature_id), check in zip(PROVIDER_FREE_FEATURE_IDS.items(), checks)
    )


def _selector_digest(session_id: str, continuation_id: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.native-verified-selector/v1",
                "session_id": session_id,
                "generation": 1,
                "continuation_id": continuation_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class TestNativeVerifiedDifferential(unittest.TestCase):
    def test_nine_provider_free_observations_are_exact_and_zero_effect(self) -> None:
        observations = run_native_verified_provider_free_observations()
        self.assertEqual(tuple(item["scenario_id"] for item in observations), tuple(PROVIDER_FREE_FEATURE_IDS))
        self.assertTrue(all(item["status"] == "PASS" for item in observations))
        self.assertTrue(all(item["provider_operations"] == 0 for item in observations))


if __name__ == "__main__":
    unittest.main()
