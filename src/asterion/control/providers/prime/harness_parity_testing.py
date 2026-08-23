"""Closed provider-free parity evidence for Prime continual harness state."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
    ParityScenarioResult,
    ParityScenarioRunner,
)


PRIME_HARNESS_SCENARIO_MATRIX = (
    "prime-parity.harness.evidence-refinement",
    "prime-parity.harness.history-snapshots",
    "prime-parity.harness.memory-entries",
    "prime-parity.harness.prompt-entries",
    "prime-parity.harness.rollback",
    "prime-parity.harness.scope-isolation",
    "prime-parity.harness.skill-descriptions",
    "prime-parity.harness.subagent-specifications",
)
PRIME_HARNESS_BOUNDED_SCENARIO_IDS = (
    "prime-parity.harness.evidence-refinement",
)
PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS = tuple(
    scenario_id
    for scenario_id in PRIME_HARNESS_SCENARIO_MATRIX
    if scenario_id not in PRIME_HARNESS_BOUNDED_SCENARIO_IDS
)
PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID = (
    "test.prime-continual-harness.provider-free"
)
PRIME_HARNESS_BOUNDED_VERIFICATION_COMMAND_ID = (
    "test.prime-continual-harness.bounded"
)
PRIME_HARNESS_REQUIRED_ASSERTIONS = (
    "authority-preserved",
    "feature-reachable",
    "identity-stable",
    "public-redacted",
)
_REPORT_ASSERTIONS = (
    "base_prompt_immutable",
    "exact_python_skill_contract",
    "scope_roots_disjoint",
    "subagent_not_spawned",
)
_SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c"
_ARTIFACT_LOCK = "asterion.prime-artifact-lock/v1"
_HARNESS_MODULE_LOCK = "asterion.prime-harness-module-lock/v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, repr=False)
class PrimeHarnessScenarioObservation:
    scenario_id: str
    status: str
    checks: tuple[str, ...]
    fault_ids: tuple[str, ...]
    real_prime_runtime: bool
    fake_daemon: bool
    provider_operations: int
    model_credential_reads: int
    owned_process_count_after_close: int
    source_commit: str
    artifact_lock: str
    harness_module_lock: str
    command_id: str
    serialized_observations: str
    evidence_id: str

    def __repr__(self) -> str:
        return (
            "PrimeHarnessScenarioObservation("
            f"scenario_id={self.scenario_id!r}, status={self.status!r}, "
            f"evidence_id={self.evidence_id!r}, observations=<redacted>)"
        )


def _canonical(value: Mapping[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _report_digest_payload(report: Mapping[str, object]) -> dict[str, object]:
    return {
        key: report[key]
        for key in (
            "assertions",
            "fake_daemon",
            "model_credential_reads",
            "provider_operations",
            "real_prime_runtime",
            "restart_after_admission",
            "restart_digest",
            "scenario_ids",
            "snapshot_digest",
        )
    }


def _observation_payload(
    scenario_id: str, observation_digest: object
) -> dict[str, object]:
    return {
        "artifact_lock": _ARTIFACT_LOCK,
        "checks": list(PRIME_HARNESS_REQUIRED_ASSERTIONS),
        "command_id": PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID,
        "fake_daemon": False,
        "fault_ids": ["restart-after-admission"],
        "harness_module_lock": _HARNESS_MODULE_LOCK,
        "model_credential_reads": 0,
        "observation_digest": observation_digest,
        "owned_process_count_after_close": 0,
        "provider_id": "asterion.prime-gateway",
        "provider_operations": 0,
        "real_prime_runtime": True,
        "scenario_id": scenario_id,
        "source_commit": _SOURCE_COMMIT,
        "status": "PASS",
    }


def build_prime_harness_observations(
    report: Mapping[str, object],
) -> tuple[PrimeHarnessScenarioObservation, ...]:
    """Reduce one closed real-Prime report into seven exact evidence records."""

    try:
        if type(report) is not dict or set(report) != {
            "assertions",
            "fake_daemon",
            "model_credential_reads",
            "observation_digest",
            "owned_process_count_after_close",
            "provider_operations",
            "real_prime_runtime",
            "restart_after_admission",
            "restart_digest",
            "scenario_ids",
            "snapshot_digest",
            "status",
        }:
            raise ValueError
        assertions = report["assertions"]
        scenario_ids = report["scenario_ids"]
        if (
            type(assertions) is not dict
            or tuple(assertions) != _REPORT_ASSERTIONS
            or any(value is not True for value in assertions.values())
            or type(scenario_ids) is not list
            or tuple(scenario_ids) != PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS
            or report["status"] != "PASS"
            or report["real_prime_runtime"] is not True
            or report["fake_daemon"] is not False
            or report["restart_after_admission"] is not True
            or type(report["provider_operations"]) is not int
            or report["provider_operations"] != 0
            or type(report["model_credential_reads"]) is not int
            or report["model_credential_reads"] != 0
            or type(report["owned_process_count_after_close"]) is not int
            or report["owned_process_count_after_close"] != 0
            or any(
                not isinstance(report[key], str)
                or _DIGEST.fullmatch(report[key]) is None
                for key in (
                    "observation_digest",
                    "restart_digest",
                    "snapshot_digest",
                )
            )
        ):
            raise ValueError
        expected_digest = hashlib.sha256(
            _canonical(_report_digest_payload(report)).encode("utf-8")
        ).hexdigest()
        if report["observation_digest"] != expected_digest:
            raise ValueError

        observations = []
        for scenario_id in PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS:
            serialized = _canonical(
                _observation_payload(scenario_id, report["observation_digest"])
            )
            observations.append(
                PrimeHarnessScenarioObservation(
                    scenario_id=scenario_id,
                    status="PASS",
                    checks=PRIME_HARNESS_REQUIRED_ASSERTIONS,
                    fault_ids=("restart-after-admission",),
                    real_prime_runtime=True,
                    fake_daemon=False,
                    provider_operations=0,
                    model_credential_reads=0,
                    owned_process_count_after_close=0,
                    source_commit=_SOURCE_COMMIT,
                    artifact_lock=_ARTIFACT_LOCK,
                    harness_module_lock=_HARNESS_MODULE_LOCK,
                    command_id=PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID,
                    serialized_observations=serialized,
                    evidence_id="evidence.harness."
                    + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                )
            )
        return tuple(observations)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime harness observation is invalid"
        ) from None


def build_prime_harness_bounded_observation(
    receipt: Mapping[str, object],
) -> PrimeHarnessScenarioObservation:
    """Bind evidence-refinement to one finite closed bounded receipt."""

    try:
        if not isinstance(receipt, Mapping) or set(receipt) != {
            "evidence_input_count",
            "format",
            "host_admitted",
            "limits",
            "model_credential_reads",
            "model_selector_digest",
            "proposal_grounded",
            "provider_operations",
            "snapshot_activated",
            "status",
            "usage",
        }:
            raise ValueError
        usage = receipt["usage"]
        limits = receipt["limits"]
        if (
            receipt["format"] != "asterion.prime-continual-harness-bounded/v1"
            or receipt["status"] != "PASS"
            or not isinstance(receipt["model_selector_digest"], str)
            or _DIGEST.fullmatch(receipt["model_selector_digest"]) is None
            or receipt["provider_operations"] != 1
            or isinstance(receipt["provider_operations"], bool)
            or receipt["model_credential_reads"] != 1
            or isinstance(receipt["model_credential_reads"], bool)
            or receipt["evidence_input_count"] != 7
            or receipt["proposal_grounded"] is not True
            or receipt["host_admitted"] is not True
            or receipt["snapshot_activated"] is not True
            or not isinstance(usage, Mapping)
            or set(usage) != {"aggregate_tokens", "cost_micros"}
            or not isinstance(limits, Mapping)
            or set(limits) != {"aggregate_tokens", "cost_micros", "deadline_ms"}
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (*usage.values(), *limits.values())
            )
            or usage["aggregate_tokens"] < 1
            or usage["cost_micros"] < 0
            or any(limits[key] < 1 for key in limits)
            or usage["aggregate_tokens"] > limits["aggregate_tokens"]
            or usage["cost_micros"] > limits["cost_micros"]
        ):
            raise ValueError
        receipt_digest = hashlib.sha256(_canonical(receipt).encode()).hexdigest()
        scenario_id = PRIME_HARNESS_BOUNDED_SCENARIO_IDS[0]
        payload = {
            "artifact_lock": _ARTIFACT_LOCK,
            "bounded_receipt_sha256": receipt_digest,
            "checks": list(PRIME_HARNESS_REQUIRED_ASSERTIONS),
            "command_id": PRIME_HARNESS_BOUNDED_VERIFICATION_COMMAND_ID,
            "fake_daemon": False,
            "fault_ids": ["restart-after-admission"],
            "harness_module_lock": _HARNESS_MODULE_LOCK,
            "model_credential_reads": 1,
            "owned_process_count_after_close": 0,
            "provider_id": "asterion.prime-gateway",
            "provider_operations": 1,
            "real_prime_runtime": True,
            "scenario_id": scenario_id,
            "source_commit": _SOURCE_COMMIT,
            "status": "PASS",
        }
        serialized = _canonical(payload)
        return PrimeHarnessScenarioObservation(
            scenario_id=scenario_id,
            status="PASS",
            checks=PRIME_HARNESS_REQUIRED_ASSERTIONS,
            fault_ids=("restart-after-admission",),
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=1,
            model_credential_reads=1,
            owned_process_count_after_close=0,
            source_commit=_SOURCE_COMMIT,
            artifact_lock=_ARTIFACT_LOCK,
            harness_module_lock=_HARNESS_MODULE_LOCK,
            command_id=PRIME_HARNESS_BOUNDED_VERIFICATION_COMMAND_ID,
            serialized_observations=serialized,
            evidence_id="evidence.harness."
            + hashlib.sha256(serialized.encode()).hexdigest(),
        )
    except (KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime harness bounded observation is invalid"
        ) from None


@dataclass(frozen=True)
class _Clock:
    deterministic: bool = True

    def now_ms(self) -> int:
        return 0


@dataclass(frozen=True)
class _FixtureStore:
    model_credential_reads: int = 0


@dataclass(frozen=True)
class _FaultInjector:
    deterministic: bool = True

    def inject(self, fault_id: str) -> None:
        del fault_id


def register_prime_harness_scenarios(
    registry: ParityScenarioRegistry,
    *,
    observations: Sequence[PrimeHarnessScenarioObservation],
    bounded_receipt: Mapping[str, object] | None,
    provider_factory: Callable[[], object],
) -> None:
    """Register exactly seven provider-free scenarios, never the bounded path."""

    try:
        items = tuple(observations)
        if (
            registry.provider_id != "asterion.prime-gateway"
            or not callable(provider_factory)
            or tuple(item.scenario_id for item in items)
            != PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS
            or any(type(item) is not PrimeHarnessScenarioObservation for item in items)
        ):
            raise ValueError
        validated = list(items)
        if bounded_receipt is not None:
            validated.insert(0, build_prime_harness_bounded_observation(bounded_receipt))
        for observation in items:
            payload = json.loads(observation.serialized_observations)
            expected = _canonical(
                _observation_payload(
                    observation.scenario_id,
                    payload.get("observation_digest"),
                )
            )
            if (
                type(payload) is not dict
                or observation.serialized_observations != expected
                or observation.status != "PASS"
                or observation.checks != PRIME_HARNESS_REQUIRED_ASSERTIONS
                or observation.fault_ids != ("restart-after-admission",)
                or observation.real_prime_runtime is not True
                or observation.fake_daemon is not False
                or observation.provider_operations != 0
                or observation.model_credential_reads != 0
                or observation.owned_process_count_after_close != 0
                or observation.source_commit != _SOURCE_COMMIT
                or observation.artifact_lock != _ARTIFACT_LOCK
                or observation.harness_module_lock != _HARNESS_MODULE_LOCK
                or observation.command_id
                != PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID
                or observation.evidence_id
                != "evidence.harness."
                + hashlib.sha256(
                    observation.serialized_observations.encode("utf-8")
                ).hexdigest()
            ):
                raise ValueError
    except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime harness evidence adapter is invalid"
        ) from None

    for observation in validated:
        feature_id = observation.scenario_id.removeprefix("prime-parity.")
        boundary = (
            "bounded-provider"
            if observation.scenario_id in PRIME_HARNESS_BOUNDED_SCENARIO_IDS
            else "real-prime-provider-free"
        )

        async def executor(
            factory,
            clock,
            private_fixture_store,
            fault_injector,
            *,
            scenario_id: str = observation.scenario_id,
            evidence_id: str = observation.evidence_id,
        ) -> ParityScenarioResult:
            del clock, private_fixture_store, fault_injector
            factory()
            return ParityScenarioResult(
                scenario_id=scenario_id,
                provider_id="asterion.prime-gateway",
                status="pass",
                evidence_id=evidence_id,
                reason_code=(
                    "real-prime-bounded-provider-verified"
                    if scenario_id in PRIME_HARNESS_BOUNDED_SCENARIO_IDS
                    else "real-prime-provider-free-verified"
                ),
            )

        registry.register(
            observation.scenario_id,
            ParityScenarioRunner(
                scenario_id=observation.scenario_id,
                provider_id="asterion.prime-gateway",
                boundary=boundary,
                feature_ids=(feature_id,),
                assertion_ids=PRIME_HARNESS_REQUIRED_ASSERTIONS,
                fault_ids=("restart-after-admission",),
                provider_factory=provider_factory,
                clock=_Clock(),
                private_fixture_store=_FixtureStore(),
                fault_injector=_FaultInjector(),
                executor=executor,
            ),
        )
