"""Reduce Native Verified-loop evidence without granting execution authority."""

from __future__ import annotations

import asyncio
import argparse
import importlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from asterion.control.authority import RemainingBudget
from asterion.control.providers.native.bounded import (
    BoundedNativeTurnAdapter,
    NativeBoundedTurnError,
    NativeSmallVerificationPresetResolver,
)
from asterion.control.providers.native.model import NativeTurnRequest


PROVIDER_FREE_FEATURE_IDS = {
    "prime-parity.session.persistence-naming": "session.persistence-naming",
    "prime-parity.session.resume-delete": "session.resume-delete",
    "prime-parity.session.delivery": "session.delivery",
    "prime-parity.session.usage-status": "session.usage-status",
    "prime-parity.rlm.environment": "rlm.environment",
    "prime-parity.rlm.usage-cost": "rlm.usage-cost",
    "prime-parity.rlm.recovery": "rlm.recovery",
    "prime-parity.operation.goals": "operation.goals",
    "prime-parity.operation.detach-attach-replay": "operation.detach-attach-replay",
}
BOUNDED_FEATURE_IDS = ("rlm.generated-program", "operation.autonomous-quality")
_EXTERNAL_COUNTER_FIELDS = (
    "provider_operations",
    "model_operations",
    "credential_reads",
    "network_operations",
    "application_operations",
    "upload_operations",
)


class NativeVerifiedLoopError(ValueError):
    """Raised when a Native Verified-loop receipt is ambiguous or unsafe."""


def build_native_verified_loop_report(
    root: Path,
    *,
    observation_runner: Callable[[], Sequence[Mapping[str, object]]],
    bounded_receipt_loader: Callable[[], Mapping[str, object] | None],
) -> Mapping[str, object]:
    if not isinstance(root, Path) or not root.is_dir():
        raise NativeVerifiedLoopError("native verified-loop evidence is invalid")
    observations = tuple(observation_runner())
    expected_items = tuple(PROVIDER_FREE_FEATURE_IDS.items())
    if len(observations) != len(expected_items):
        raise NativeVerifiedLoopError("native verified-loop evidence is invalid")

    passed: list[str] = []
    for observation, (scenario_id, feature_id) in zip(observations, expected_items):
        if not _valid_observation(observation, scenario_id, feature_id):
            raise NativeVerifiedLoopError("native verified-loop evidence is invalid")
        passed.append(feature_id)

    bounded = bounded_receipt_loader()
    if bounded is not None:
        raise NativeVerifiedLoopError("native verified-loop evidence is invalid")
    return {
        "status": "INCOMPLETE",
        "level": "provider-free",
        "provider_free_passed_feature_ids": passed,
        "bounded_required_feature_ids": list(BOUNDED_FEATURE_IDS),
        "bounded_passed_feature_ids": [],
        "promoted_feature_ids": [],
        "external_counters": {field: 0 for field in _EXTERNAL_COUNTER_FIELDS},
    }


def _valid_observation(
    value: Mapping[str, object], scenario_id: str, feature_id: str
) -> bool:
    required = {
        "scenario_id",
        "feature_id",
        "status",
        "public_projection_equal",
        "redaction_safe",
        *_EXTERNAL_COUNTER_FIELDS,
    }
    return (
        isinstance(value, Mapping)
        and set(value) == required
        and value["scenario_id"] == scenario_id
        and value["feature_id"] == feature_id
        and value["status"] == "PASS"
        and value["public_projection_equal"] is True
        and value["redaction_safe"] is True
        and all(value[field] == 0 for field in _EXTERNAL_COUNTER_FIELDS)
    )


async def run_small_verification(
    resolver: NativeSmallVerificationPresetResolver,
) -> Mapping[str, object]:
    """Run one injected small preset without accepting user configuration."""

    try:
        adapter = BoundedNativeTurnAdapter.from_small_verification_preset(resolver)
        result = await adapter.execute(
            NativeTurnRequest(
                turn_id="native-small-verification-turn",
                session_id="native-small-verification-session",
                generation=1,
                authority_revision=1,
                causal_command_ids=(),
                inputs=(),
                action_results=(),
                budget=RemainingBudget(1, 0, 0, 1, 1, 1),
            )
        )
        if result.usage.aggregate_tokens < 1:
            raise NativeBoundedTurnError
        return {
            "status": "PASS",
            "level": "small-verification",
            "bounded_passed_feature_ids": list(BOUNDED_FEATURE_IDS),
            "promoted_feature_ids": [],
        }
    except (NativeBoundedTurnError, ValueError):
        return {
            "status": "External-limited",
            "level": "small-verification",
            "bounded_passed_feature_ids": [],
            "promoted_feature_ids": [],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--level",
        choices=("provider-free", "bounded", "small-verification"),
        required=True,
    )
    arguments = parser.parse_args()
    if arguments.level == "bounded":
        print(
            json.dumps(
                {
                    "status": "External-limited",
                    "level": arguments.level,
                    "promoted_feature_ids": [],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    if arguments.level == "small-verification":
        try:
            from asterion.applications.dci_agent_lite.native_small_verification import (
                NativeSmallVerificationOperatorResolver,
                PrimeNativeSmallVerificationHost,
            )

            root = Path(__file__).resolve().parents[1]
            resolver = NativeSmallVerificationOperatorResolver.from_repository(
                root, PrimeNativeSmallVerificationHost()
            )
            report = asyncio.run(run_small_verification(resolver))
        except (ImportError, OSError, ValueError):
            report = {
                "status": "External-limited",
                "level": "small-verification",
                "bounded_passed_feature_ids": [],
                "promoted_feature_ids": [],
            }
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0 if report["status"] == "PASS" else 1
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    try:
        runner = importlib.import_module(
            "tests.test_native_verified_differential"
        ).run_native_verified_provider_free_observations
        report = build_native_verified_loop_report(
            root,
            observation_runner=runner,
            bounded_receipt_loader=lambda: None,
        )
    except (AttributeError, NativeVerifiedLoopError):
        report = {
            "status": "INVALID",
            "level": "provider-free",
            "promoted_feature_ids": [],
        }
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 1
    finally:
        sys.path.pop(0)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
