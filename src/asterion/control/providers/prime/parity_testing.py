"""Exact adapters from Prime Phase 1 evidence to full parity scenarios."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
    ParityScenarioResult,
    ParityScenarioRunner,
)


PHASE1_PRIME_SCENARIO_IDS = (
    "prime-loop-application",
    "prime-loop-child",
    "prime-loop-detach-attach",
    "prime-loop-checkpoint",
    "prime-loop-gateway-crash",
    "prime-loop-supervisor-crash",
    "prime-loop-worker-crash",
    "prime-loop-cancel",
    "prime-loop-budget",
    "prime-loop-redaction",
)
PROVEN_PHASE1_PARITY_SCENARIO_IDS = (
    "prime-parity.operation.detach-attach-replay",
    "prime-parity.operation.goals",
)
_PHASE1_SENTINELS = (
    "SENTINEL_PROMPT",
    "SENTINEL_TOKEN",
    "SENTINEL_PATH",
    "SENTINEL_OUTPUT",
)
_PHASE1_PARITY_ADAPTERS = {
    "prime-parity.operation.detach-attach-replay": {
        "source_scenario_id": "prime-loop-detach-attach",
        "feature_ids": ("operation.detach-attach-replay",),
        "required_events": (
            "session.created",
            "session.recovery-required",
            "session.running",
        ),
    },
    "prime-parity.operation.goals": {
        "source_scenario_id": "prime-loop-application",
        "feature_ids": ("operation.goals",),
        "required_events": (
            "goal.updated",
            "session.completed",
        ),
    },
}


@dataclass(frozen=True)
class _DeterministicClock:
    deterministic: bool = True

    def now_ms(self) -> int:
        return 1_786_291_200_000


@dataclass(frozen=True)
class _CredentialFreeFixtureStore:
    model_credential_reads: int = 0


@dataclass(frozen=True)
class _DeterministicFaultInjector:
    deterministic: bool = True

    def inject(self, fault_id: str) -> None:
        del fault_id


def register_proven_phase1_prime_subset(
    registry: ParityScenarioRegistry,
    results: Sequence[object],
    *,
    provider_factory: Callable[[], object],
) -> None:
    """Adapt only full-feature coverage from the closed Phase 1 scenario set."""

    try:
        if (
            registry.provider_id != "asterion.prime-gateway"
            or type(results) not in {list, tuple}
            or not callable(provider_factory)
            or any(
                scenario_id in registry.registered_scenario_ids
                for scenario_id in PROVEN_PHASE1_PARITY_SCENARIO_IDS
            )
        ):
            raise ParityScenarioRegistryError(
                "Phase 1 parity evidence adapter is invalid"
            )
        result_by_id: dict[str, object] = {}
        for result in results:
            scenario_id = getattr(result, "scenario_id")
            if not isinstance(scenario_id, str) or scenario_id in result_by_id:
                raise ParityScenarioRegistryError(
                    "Phase 1 parity evidence adapter is invalid"
                )
            result_by_id[scenario_id] = result
        if tuple(result_by_id) != PHASE1_PRIME_SCENARIO_IDS:
            raise ParityScenarioRegistryError(
                "Phase 1 parity evidence adapter is invalid"
            )
        for result in result_by_id.values():
            serialized = getattr(result, "serialized_observations")
            expected_evidence_id = "evidence.phase1." + hashlib.sha256(
                serialized.encode("utf-8")
            ).hexdigest()
            if (
                getattr(result, "status") != "PASS"
                or getattr(result, "provider_operations") != 0
                or tuple(getattr(result, "pathlight_gaps"))
                or getattr(result, "evidence_id") != expected_evidence_id
                or any(
                    sentinel in serialized
                    for sentinel in _PHASE1_SENTINELS
                )
            ):
                raise ParityScenarioRegistryError(
                    "Phase 1 parity evidence adapter is invalid"
                )

        runners: list[tuple[str, ParityScenarioRunner]] = []
        for parity_scenario_id in PROVEN_PHASE1_PARITY_SCENARIO_IDS:
            adapter = _PHASE1_PARITY_ADAPTERS[parity_scenario_id]
            source_id = str(adapter["source_scenario_id"])
            source = result_by_id[source_id]
            required_events = tuple(adapter["required_events"])
            observed_events = tuple(getattr(source, "pathlight_control_events"))
            if (
                getattr(source, "outcome") != "proven-effect-succeeded"
                or any(event not in observed_events for event in required_events)
            ):
                raise ParityScenarioRegistryError(
                    "Phase 1 parity evidence adapter is invalid"
                )
            evidence_id = str(getattr(source, "evidence_id"))

            async def executor(
                factory,
                clock,
                private_fixture_store,
                fault_injector,
                *,
                scenario_id: str = parity_scenario_id,
                adapted_evidence_id: str = evidence_id,
            ) -> ParityScenarioResult:
                del factory, clock, private_fixture_store, fault_injector
                return ParityScenarioResult(
                    scenario_id=scenario_id,
                    provider_id="asterion.prime-gateway",
                    status="pass",
                    evidence_id=adapted_evidence_id,
                    reason_code="phase1-exact-coverage",
                )

            runners.append(
                (
                    parity_scenario_id,
                    ParityScenarioRunner(
                        scenario_id=parity_scenario_id,
                        provider_id="asterion.prime-gateway",
                        boundary="real-prime-provider-free",
                        feature_ids=tuple(adapter["feature_ids"]),
                        provider_factory=provider_factory,
                        clock=_DeterministicClock(),
                        private_fixture_store=_CredentialFreeFixtureStore(),
                        fault_injector=_DeterministicFaultInjector(),
                        executor=executor,
                    ),
                )
            )
    except ParityScenarioRegistryError:
        raise
    except Exception:
        raise ParityScenarioRegistryError(
            "Phase 1 parity evidence adapter is invalid"
        ) from None

    for scenario_id, runner in runners:
        registry.register(scenario_id, runner)
