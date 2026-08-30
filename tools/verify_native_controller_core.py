"""Verify the provider-free Native controller core receipt."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from asterion.control.parity import ParityLedgerError, validate_parity_ledger
from tools.check_prime_parity import (
    PrimeParityCheckError,
    default_ledger_path,
    load_prime_parity_ledger,
)


COUNTER_FIELDS = (
    "provider_operations",
    "model_operations",
    "credential_reads",
    "network_operations",
    "application_operations",
    "upload_operations",
)
EXPECTED_CONFORMANCE_SCENARIOS = (
    "attach-replay",
    "budget-limited",
    "cancel",
    "checkpoint",
    "command-idempotency",
    "complete",
    "fault-recovery",
    "input-delivery",
    "pause-resume",
    "proposal-admission",
)
EXPECTED_DIFFERENTIAL_CASES = (
    "action-causality",
    "budget-monotonicity",
    "checkpoint-identity",
    "lifecycle-order",
    "replay-suffix",
)
EXPECTED_CRASH_POINTS = (
    "command-before-publish",
    "command-after-publish-before-ack",
    "turn-after-start",
    "turn-after-adapter-before-commit",
    "turn-after-commit-before-yield",
    "capsule-after-write-before-checkpoint",
    "checkpoint-after-commit-before-yield",
    "terminal-after-commit-before-host-receipt",
)
EXPECTED_NATIVE_CONTROLLER_CORE_REPORT = {
    "application_operations": 0,
    "claim": "native-controller-core",
    "common_scenarios": 10,
    "crash_points": 8,
    "credential_reads": 0,
    "differential_cases": 5,
    "model_operations": 0,
    "native_mandatory_missing": 61,
    "native_mandatory_total": 61,
    "network_operations": 0,
    "promoted_feature_ids": [],
    "provider_operations": 0,
    "status": "PASS",
    "upload_operations": 0,
}
_CONFORMANCE_KEYS = frozenset({"scenario_id", "status", *COUNTER_FIELDS})
_DIFFERENTIAL_KEYS = frozenset({"case_id", "status", *COUNTER_FIELDS})
_CRASH_KEYS = frozenset(
    {
        "crash_point",
        "status",
        "duplicate_commands",
        "duplicate_turns",
        "duplicate_actions",
        "sequence_gaps",
        "terminal_count",
        "owned_processes_after_close",
        *COUNTER_FIELDS,
    }
)
_CRASH_INVARIANT_FIELDS = (
    "duplicate_commands",
    "duplicate_turns",
    "duplicate_actions",
    "sequence_gaps",
    "owned_processes_after_close",
)


class NativeControllerCoreVerificationError(RuntimeError):
    """Raised with a fixed, redacted message for invalid core evidence."""


ObservationRunner = Callable[[], Mapping[str, Sequence[Mapping[str, object]]]]
LedgerLoader = Callable[[Path | None], Mapping[str, object]]


def build_native_controller_core_report(
    root: Path,
    *,
    ledger_loader: LedgerLoader | None = None,
    observation_runner: ObservationRunner | None = None,
) -> Mapping[str, object]:
    """Build the exact provider-free Native core verification report."""

    try:
        ledger = (ledger_loader or load_prime_parity_ledger)(default_ledger_path())
        mandatory_total, missing_total, promoted = _native_mandatory_state(ledger)
        observations = (
            observation_runner() if observation_runner is not None else _run_observations()
        )
        counts = _validate_observations(observations)
        report = {
            "application_operations": counts["application_operations"],
            "claim": "native-controller-core",
            "common_scenarios": len(EXPECTED_CONFORMANCE_SCENARIOS),
            "crash_points": len(EXPECTED_CRASH_POINTS),
            "credential_reads": counts["credential_reads"],
            "differential_cases": len(EXPECTED_DIFFERENTIAL_CASES),
            "model_operations": counts["model_operations"],
            "native_mandatory_missing": missing_total,
            "native_mandatory_total": mandatory_total,
            "network_operations": counts["network_operations"],
            "promoted_feature_ids": promoted,
            "provider_operations": counts["provider_operations"],
            "status": "PASS",
            "upload_operations": counts["upload_operations"],
        }
        _assert_exact_report(report)
        _assert_report_is_redacted(report, root)
        return report
    except NativeControllerCoreVerificationError:
        raise
    except Exception as error:
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        ) from error


def render_native_controller_core_report(report: Mapping[str, object]) -> str:
    _assert_exact_report(report)
    return json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"


def _native_mandatory_state(
    ledger: Mapping[str, object],
) -> tuple[int, int, list[str]]:
    try:
        snapshot = validate_parity_ledger(ledger)
    except (ParityLedgerError, TypeError, ValueError):
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        ) from None

    features = _mapping_sequence(snapshot.get("features"))
    mandatory_total = 0
    missing_total = 0
    promoted: list[str] = []
    for feature in features:
        if feature.get("disposition") != "mandatory":
            continue
        mandatory_total += 1
        feature_id = _exact_str(feature.get("feature_id"))
        results = tuple(
            result
            for result in _mapping_sequence(feature.get("provider_results"))
            if result.get("provider_id") == "asterion.native"
        )
        if len(results) != 1:
            raise NativeControllerCoreVerificationError(
                "Native controller core verification failed"
            )
        status = _exact_str(results[0].get("status"))
        if status == "missing":
            missing_total += 1
        else:
            promoted.append(feature_id)

    promoted.sort()
    if (
        mandatory_total != EXPECTED_NATIVE_CONTROLLER_CORE_REPORT["native_mandatory_total"]
        or missing_total
        != EXPECTED_NATIVE_CONTROLLER_CORE_REPORT["native_mandatory_missing"]
        or promoted
    ):
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )
    return mandatory_total, missing_total, promoted


def _run_observations() -> Mapping[str, Sequence[Mapping[str, object]]]:
    return {
        "conformance": _call_observation_helper(
            "tests.test_native_control_conformance",
            "run_native_conformance_observations",
        ),
        "differential": _call_observation_helper(
            "tests.test_native_prime_differential",
            "run_native_prime_differential_observations",
        ),
        "crash": _call_observation_helper(
            "tests.test_native_control_process_recovery",
            "run_native_crash_observations",
        ),
    }


def _call_observation_helper(
    module_name: str,
    function_name: str,
) -> tuple[Mapping[str, object], ...]:
    module = importlib.import_module(module_name)
    function = getattr(module, function_name)
    result = function()
    if inspect.isawaitable(result):
        result = asyncio.run(_await_any(cast(Awaitable[object], result)))
    return _observation_sequence(result)


async def _await_any(value: Awaitable[object]) -> object:
    return await value


def _validate_observations(
    observations: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, int]:
    if frozenset(observations) != frozenset(
        {"conformance", "differential", "crash"}
    ):
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )

    counts = {field: 0 for field in COUNTER_FIELDS}
    _validate_identity_group(
        observations["conformance"],
        identity_key="scenario_id",
        expected=EXPECTED_CONFORMANCE_SCENARIOS,
        allowed_keys=_CONFORMANCE_KEYS,
        counts=counts,
    )
    _validate_identity_group(
        observations["differential"],
        identity_key="case_id",
        expected=EXPECTED_DIFFERENTIAL_CASES,
        allowed_keys=_DIFFERENTIAL_KEYS,
        counts=counts,
    )
    _validate_identity_group(
        observations["crash"],
        identity_key="crash_point",
        expected=EXPECTED_CRASH_POINTS,
        allowed_keys=_CRASH_KEYS,
        counts=counts,
        require_crash_invariants=True,
    )
    return counts


def _validate_identity_group(
    rows: Sequence[Mapping[str, object]],
    *,
    identity_key: str,
    expected: tuple[str, ...],
    allowed_keys: frozenset[str],
    counts: dict[str, int],
    require_crash_invariants: bool = False,
) -> None:
    observations = _observation_sequence(rows)
    identities: list[str] = []
    for row in observations:
        if frozenset(row) != allowed_keys:
            raise NativeControllerCoreVerificationError(
                "Native controller core verification failed"
            )
        identity = row.get(identity_key)
        if type(identity) is not str:
            raise NativeControllerCoreVerificationError(
                "Native controller core verification failed"
            )
        identities.append(identity)
        if type(row.get("status")) is not str or row.get("status") != "PASS":
            raise NativeControllerCoreVerificationError(
                "Native controller core verification failed"
            )
        for field in COUNTER_FIELDS:
            count = _exact_int(row.get(field))
            if count != 0:
                raise NativeControllerCoreVerificationError(
                    "Native controller core verification failed"
                )
            counts[field] += count
        if require_crash_invariants:
            for field in _CRASH_INVARIANT_FIELDS:
                if _exact_int(row.get(field)) != 0:
                    raise NativeControllerCoreVerificationError(
                        "Native controller core verification failed"
                    )
            if _exact_int(row.get("terminal_count")) != 1:
                raise NativeControllerCoreVerificationError(
                    "Native controller core verification failed"
                )
    if tuple(identities) != expected:
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )


def _assert_exact_report(report: Mapping[str, object]) -> None:
    if dict(report) != EXPECTED_NATIVE_CONTROLLER_CORE_REPORT:
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )


def _assert_report_is_redacted(report: Mapping[str, object], root: Path) -> None:
    rendered = json.dumps(report, sort_keys=True, separators=(",", ":"))
    if str(root) in rendered or "SENTINEL_SECRET" in rendered:
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )
    items = tuple(value)
    if any(not isinstance(item, Mapping) for item in items):
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )
    return cast(tuple[Mapping[str, object], ...], items)


def _observation_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    return _mapping_sequence(value)


def _exact_str(value: object) -> str:
    if type(value) is not str:
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )
    return value


def _exact_int(value: object) -> int:
    if type(value) is not int:
        raise NativeControllerCoreVerificationError(
            "Native controller core verification failed"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)
    try:
        report = build_native_controller_core_report(
            Path(__file__).resolve().parents[1]
        )
        print(render_native_controller_core_report(report), end="")
        return 0
    except (NativeControllerCoreVerificationError, PrimeParityCheckError):
        print(
            json.dumps(
                {
                    "claim": "native-controller-core",
                    "provider_operations": 0,
                    "reason_codes": ["verification-invalid"],
                    "status": "ERROR",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
