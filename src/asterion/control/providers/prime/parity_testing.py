"""Exact adapters from Prime Phase 1 evidence to full parity scenarios."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypedDict, cast

from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
    ParityScenarioResult,
    ParityScenarioRunner,
)
from asterion.control.providers.prime.harness_parity_testing import (
    PRIME_HARNESS_BOUNDED_SCENARIO_IDS,
    PRIME_HARNESS_BOUNDED_VERIFICATION_COMMAND_ID,
    PRIME_HARNESS_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_HARNESS_PROVIDER_FREE_VERIFICATION_COMMAND_ID,
    PRIME_HARNESS_REQUIRED_ASSERTIONS,
    PRIME_HARNESS_SCENARIO_MATRIX,
    PrimeHarnessScenarioObservation,
    build_prime_harness_bounded_observation,
    build_prime_harness_observations,
    register_prime_harness_scenarios,
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

PRIME_SESSION_CONTEXT_SOURCE_COMMIT = (
    "a18809e00ea30638584d87b3afea7285a9d7296c"
)
PRIME_SESSION_CONTEXT_ARTIFACT_LOCK = "asterion.prime-artifact-lock/v1"
PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID = (
    "test.prime-session-context-parity.provider-free"
)
_SAFE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_SESSION_CONTEXT_SENTINELS = (
    "SENTINEL_PROMPT",
    "SENTINEL_SECRET",
    "SENTINEL_TOKEN",
    "SENTINEL_PATH",
    "SENTINEL_OUTPUT",
)


class _SessionContextScenarioContract(TypedDict):
    boundary: str
    feature_ids: tuple[str, ...]
    assertion_ids: tuple[str, ...]
    fault_ids: tuple[str, ...]


def _contract(
    boundary: str,
    feature_id: str,
    assertion_ids: tuple[str, ...],
    fault_ids: tuple[str, ...],
) -> _SessionContextScenarioContract:
    return cast(
        _SessionContextScenarioContract,
        MappingProxyType({
            "boundary": boundary,
            "feature_ids": (feature_id,),
            "assertion_ids": assertion_ids,
            "fault_ids": fault_ids,
        }),
    )


PRIME_SESSION_CONTEXT_SCENARIO_MATRIX: Mapping[
    str, _SessionContextScenarioContract
] = MappingProxyType(
    {
        "prime-parity.session.branch-summaries-labels": _contract(
            "bounded-provider",
            "session.branch-summaries-labels",
            (
                "branch-identity-retained",
                "label-set-clear-exact-entry",
                "summary-admitted-budgeted",
                "summary-label-text-private",
            ),
            (
                "cancel-during-summary",
                "label-replay-conflict",
                "restart-after-summary-result",
                "restart-before-summary-result",
                "stale-entry",
            ),
        ),
        "prime-parity.session.compaction": _contract(
            "bounded-provider",
            "session.compaction",
            (
                "auto-compaction-disabled",
                "budget-admitted-before-model-call",
                "context-usage-monotonic",
                "private-summary",
                "resumable-compacted-context",
            ),
            (
                "bounded-provider-failure",
                "cancel-during-compaction",
                "restart-after-compaction-result",
                "restart-before-compaction-result",
            ),
        ),
        "prime-parity.session.delivery": _contract(
            "real-prime-provider-free",
            "session.delivery",
            (
                "cancel-before-ownership",
                "direct-idle-ownership",
                "follow-up-next-turn",
                "input-id-exactly-once",
                "steer-current-turn",
            ),
            (
                "cancel-before-ownership",
                "replay-direct",
                "replay-follow-up",
                "replay-steer",
                "restart-after-admission",
            ),
        ),
        "prime-parity.session.fork-clone": _contract(
            "real-prime-provider-free",
            "session.fork-clone",
            (
                "clone-equals-leaf-fork-at",
                "fork-requested-entry",
                "new-binding-atomically-committed",
                "source-remains-resumable",
            ),
            (
                "missing-leaf",
                "response-binding-conflict",
                "restart-after-clone-binding",
                "restart-after-clone-result",
                "restart-after-fork-binding",
                "restart-after-fork-result",
            ),
        ),
        "prime-parity.session.persistence-naming": _contract(
            "real-prime-provider-free",
            "session.persistence-naming",
            (
                "active-transcript-continuation-identities-separated",
                "duplicate-rename-idempotent",
                "name-persists-detach-restart",
                "public-name-digest-only",
            ),
            (
                "conflicting-rename-replay",
                "restart-after-daemon-result-before-commit",
            ),
        ),
        "prime-parity.session.resume-delete": _contract(
            "real-prime-provider-free",
            "session.resume-delete",
            (
                "active-continuation-delete-rejected",
                "exact-continuation-resumed",
                "inactive-exact-artifact-deleted",
                "public-paths-absent",
            ),
            (
                "delete-after-side-effect-before-commit",
                "restart-after-switch",
                "selector-swap",
                "symlink-replacement",
            ),
        ),
        "prime-parity.session.rich-attachments": _contract(
            "real-prime-provider-free",
            "session.rich-attachments",
            (
                "attachment-causal-to-exact-input",
                "body-private",
                "prime-receives-verified-bytes-once",
                "typed-digest-size-projection",
            ),
            (
                "body-swap",
                "digest-mismatch",
                "media-mismatch",
                "restart-after-attachment-bind",
                "restart-after-prompt-admission",
                "size-mismatch",
            ),
        ),
        "prime-parity.session.tree-navigation": _contract(
            "real-prime-provider-free",
            "session.tree-navigation",
            (
                "canonical-topology-projected",
                "deterministic-active-leaf",
                "exact-entry-scope",
                "raw-message-label-absent",
            ),
            (
                "foreign-entry-id",
                "restart-after-navigation",
                "stale-continuation",
            ),
        ),
        "prime-parity.session.usage-status": _contract(
            "real-prime-provider-free",
            "session.usage-status",
            (
                "current-identity",
                "nonnegative-monotonic-counts",
                "private-provider-fields-absent",
                "safe-status-vocabulary",
            ),
            (
                "malformed-stats",
                "overflow-stats",
                "restart-during-read",
                "stale-generation",
            ),
        ),
    }
)
PRIME_SESSION_CONTEXT_SCENARIO_IDS = tuple(
    PRIME_SESSION_CONTEXT_SCENARIO_MATRIX
)
PRIME_SESSION_CONTEXT_PROVIDER_FREE_SCENARIO_IDS = tuple(
    scenario_id
    for scenario_id, contract in PRIME_SESSION_CONTEXT_SCENARIO_MATRIX.items()
    if contract["boundary"] == "real-prime-provider-free"
)
PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS = tuple(
    scenario_id
    for scenario_id, contract in PRIME_SESSION_CONTEXT_SCENARIO_MATRIX.items()
    if contract["boundary"] == "bounded-provider"
)

_RLM_PRIMARY_ASSERTIONS = (
    "authority-preserved",
    "feature-reachable",
    "identity-stable",
    "public-redacted",
)
_RLM_PRIMARY_FAULTS = ("restart-after-admission",)

PRIME_RLM_SCENARIO_MATRIX: Mapping[str, _SessionContextScenarioContract] = (
    MappingProxyType(
        {
            "prime-parity.rlm.cancellation-teardown": _contract(
                "real-prime-provider-free",
                "rlm.cancellation-teardown",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.child-model": _contract(
                "bounded-provider",
                "rlm.child-model",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.environment": _contract(
                "real-prime-provider-free",
                "rlm.environment",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.generated-program": _contract(
                "bounded-provider",
                "rlm.generated-program",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.messaging": _contract(
                "real-prime-provider-free",
                "rlm.messaging",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.recovery": _contract(
                "real-prime-provider-free",
                "rlm.recovery",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.recursion-depth": _contract(
                "bounded-provider",
                "rlm.recursion-depth",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.registry-lifecycle": _contract(
                "real-prime-provider-free",
                "rlm.registry-lifecycle",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
            "prime-parity.rlm.usage-cost": _contract(
                "real-prime-provider-free",
                "rlm.usage-cost",
                _RLM_PRIMARY_ASSERTIONS,
                _RLM_PRIMARY_FAULTS,
            ),
        }
    )
)
PRIME_RLM_SCENARIO_IDS = tuple(PRIME_RLM_SCENARIO_MATRIX)
PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS = tuple(
    scenario_id
    for scenario_id, contract in PRIME_RLM_SCENARIO_MATRIX.items()
    if contract["boundary"] == "real-prime-provider-free"
)
PRIME_RLM_BOUNDED_SCENARIO_IDS = tuple(
    scenario_id
    for scenario_id, contract in PRIME_RLM_SCENARIO_MATRIX.items()
    if contract["boundary"] == "bounded-provider"
)
PRIME_RLM_VERIFICATION_COMMAND_ID = (
    "test.prime-rlm-spawn-admission.provider-free"
)
PRIME_RLM_REQUIRED_CHECK_IDS = MappingProxyType(
    {
        "prime-parity.rlm.cancellation-teardown": (
            "native-child-teardown-passed",
            "pinned-prime-rlm-daemon-passed",
        ),
        "prime-parity.rlm.environment": (
            "closed-home-no-credentials-passed",
            "pinned-prime-rlm-daemon-passed",
        ),
        "prime-parity.rlm.messaging": (
            "native-family-message-admitted-passed",
            "native-message-delivery-recorded-passed",
        ),
        "prime-parity.rlm.recovery": (
            "native-message-recovery-fenced-passed",
            "pinned-prime-rlm-daemon-passed",
        ),
        "prime-parity.rlm.registry-lifecycle": (
            "native-child-registry-delete-passed",
            "pinned-prime-rlm-daemon-passed",
        ),
        "prime-parity.rlm.usage-cost": (
            "zero-provider-usage-monotonic-passed",
            "pinned-prime-rlm-daemon-passed",
        ),
    }
)
PRIME_SESSION_CONTEXT_REQUIRED_CHECK_IDS = MappingProxyType(
    {
        "prime-parity.session.branch-summaries-labels": (
            "bounded-authority-absent",
            "gateway-branch-summary-faults-passed",
            "pinned-prime-preflight-passed",
        ),
        "prime-parity.session.compaction": (
            "bounded-authority-absent",
            "gateway-compaction-faults-passed",
            "pinned-prime-preflight-passed",
        ),
        "prime-parity.session.delivery": (
            "daemon-input-admission-capability-passed",
            "gateway-delivery-faults-passed",
            "prime-queue-code-path-passed",
        ),
        "prime-parity.session.fork-clone": (
            "gateway-fork-clone-faults-passed",
            "prime-fork-clone-roundtrip-passed",
            "source-resume-roundtrip-passed",
        ),
        "prime-parity.session.persistence-naming": (
            "gateway-naming-faults-passed",
            "prime-detach-attach-passed",
            "prime-name-roundtrip-passed",
        ),
        "prime-parity.session.resume-delete": (
            "gateway-resume-delete-faults-passed",
            "prime-exact-delete-passed",
            "prime-resume-roundtrip-passed",
        ),
        "prime-parity.session.rich-attachments": (
            "gateway-attachment-faults-passed",
            "prime-image-code-path-passed",
            "private-body-redaction-passed",
        ),
        "prime-parity.session.tree-navigation": (
            "gateway-navigation-faults-passed",
            "prime-tree-navigation-roundtrip-passed",
            "tree-private-content-redaction-passed",
        ),
        "prime-parity.session.usage-status": (
            "gateway-status-faults-passed",
            "prime-status-roundtrip-passed",
            "status-private-fields-redacted",
        ),
    }
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
        "assertion_ids": (
            "authority-preserved",
            "feature-reachable",
            "identity-stable",
            "public-redacted",
        ),
        "fault_ids": ("restart-after-admission",),
        "required_events": (
            "session.created",
            "session.recovery-required",
            "session.running",
        ),
    },
    "prime-parity.operation.goals": {
        "source_scenario_id": "prime-loop-application",
        "feature_ids": ("operation.goals",),
        "assertion_ids": (
            "authority-preserved",
            "feature-reachable",
            "identity-stable",
            "public-redacted",
        ),
        "fault_ids": ("restart-after-admission",),
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


@dataclass(frozen=True, repr=False)
class PrimeSessionContextScenarioObservation:
    """Public-safe result of one exact Prime session/context verification."""

    scenario_id: str
    status: str
    checks: tuple[str, ...]
    real_prime_runtime: bool
    fake_daemon: bool
    provider_operations: int
    model_credential_reads: int
    source_commit: str
    artifact_lock: str
    command_id: str
    serialized_observations: str
    evidence_id: str | None

    def __repr__(self) -> str:
        return (
            "PrimeSessionContextScenarioObservation("
            f"scenario_id={self.scenario_id!r}, status={self.status!r}, "
            f"evidence_id={self.evidence_id!r}, observations=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class PrimeRlmScenarioObservation:
    """Public-safe result of one exact native Prime RLM verification."""

    scenario_id: str
    status: str
    checks: tuple[str, ...]
    real_prime_runtime: bool
    fake_daemon: bool
    provider_operations: int
    model_credential_reads: int
    source_commit: str
    artifact_lock: str
    command_id: str
    serialized_observations: str
    evidence_id: str | None

    def __repr__(self) -> str:
        return (
            "PrimeRlmScenarioObservation("
            f"scenario_id={self.scenario_id!r}, status={self.status!r}, "
            f"evidence_id={self.evidence_id!r}, observations=<redacted>)"
        )


def build_prime_rlm_observation(
    *,
    scenario_id: str,
    status: str,
    checks: Sequence[str],
    real_prime_runtime: bool,
    fake_daemon: bool,
    provider_operations: int,
    model_credential_reads: int,
) -> PrimeRlmScenarioObservation:
    """Build a canonical RLM observation without inventing model evidence."""

    try:
        contract = PRIME_RLM_SCENARIO_MATRIX[scenario_id]
        check_ids = tuple(checks)
        expected_checks = PRIME_RLM_REQUIRED_CHECK_IDS.get(scenario_id, ())
        expected_status = (
            "EXTERNAL-LIMITED"
            if scenario_id in PRIME_RLM_BOUNDED_SCENARIO_IDS
            else "PASS"
        )
        if (
            status != expected_status
            or check_ids != expected_checks
            or any(_SAFE_ID.fullmatch(item) is None for item in check_ids)
            or type(real_prime_runtime) is not bool
            or type(fake_daemon) is not bool
            or type(provider_operations) is not int
            or provider_operations < 0
            or type(model_credential_reads) is not int
            or model_credential_reads < 0
        ):
            raise ValueError
        payload = {
            "artifact_lock": PRIME_SESSION_CONTEXT_ARTIFACT_LOCK,
            "assertion_ids": list(contract["assertion_ids"]),
            "boundary": contract["boundary"],
            "checks": list(check_ids),
            "command_id": PRIME_RLM_VERIFICATION_COMMAND_ID,
            "fake_daemon": fake_daemon,
            "fault_ids": list(contract["fault_ids"]),
            "feature_ids": list(contract["feature_ids"]),
            "model_credential_reads": model_credential_reads,
            "provider_id": "asterion.prime-gateway",
            "provider_operations": provider_operations,
            "real_prime_runtime": real_prime_runtime,
            "scenario_id": scenario_id,
            "source_commit": PRIME_SESSION_CONTEXT_SOURCE_COMMIT,
            "status": status,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        evidence_id = None
        if (
            status == "PASS"
            and real_prime_runtime
            and not fake_daemon
        ):
            evidence_id = "evidence.rlm." + hashlib.sha256(
                serialized.encode("utf-8")
            ).hexdigest()
        return PrimeRlmScenarioObservation(
            scenario_id=scenario_id,
            status=status,
            checks=check_ids,
            real_prime_runtime=real_prime_runtime,
            fake_daemon=fake_daemon,
            provider_operations=provider_operations,
            model_credential_reads=model_credential_reads,
            source_commit=PRIME_SESSION_CONTEXT_SOURCE_COMMIT,
            artifact_lock=PRIME_SESSION_CONTEXT_ARTIFACT_LOCK,
            command_id=PRIME_RLM_VERIFICATION_COMMAND_ID,
            serialized_observations=serialized,
            evidence_id=evidence_id,
        )
    except (KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError("Prime RLM observation is invalid") from None


def register_prime_rlm_scenarios(
    registry: ParityScenarioRegistry,
    observations: Sequence[PrimeRlmScenarioObservation],
    *,
    provider_factory: Callable[[], object],
) -> None:
    """Register exact RLM scenarios without promoting model-only paths."""

    try:
        if (
            registry.provider_id != "asterion.prime-gateway"
            or type(observations) not in {list, tuple}
            or not callable(provider_factory)
            or any(
                scenario_id in registry.registered_scenario_ids
                for scenario_id in PRIME_RLM_SCENARIO_IDS
            )
        ):
            raise ValueError
        items = tuple(observations)
        if tuple(item.scenario_id for item in items) != PRIME_RLM_SCENARIO_IDS:
            raise ValueError
        runners: list[tuple[str, ParityScenarioRunner]] = []
        for observation in items:
            _validate_prime_rlm_observation(observation)
            contract = PRIME_RLM_SCENARIO_MATRIX[observation.scenario_id]
            result_status = (
                "pass" if observation.status == "PASS" else "external-limited"
            )
            reason_code = (
                "real-prime-provider-free-verified"
                if result_status == "pass"
                else "bounded-provider-authorization-required"
            )

            async def executor(
                factory,
                clock,
                private_fixture_store,
                fault_injector,
                *,
                scenario_id: str = observation.scenario_id,
                status: str = result_status,
                evidence_id: str | None = observation.evidence_id,
                reason: str = reason_code,
            ) -> ParityScenarioResult:
                del clock, private_fixture_store, fault_injector
                factory()
                return ParityScenarioResult(
                    scenario_id=scenario_id,
                    provider_id="asterion.prime-gateway",
                    status=status,
                    evidence_id=evidence_id,
                    reason_code=reason,
                )

            runners.append(
                (
                    observation.scenario_id,
                    ParityScenarioRunner(
                        scenario_id=observation.scenario_id,
                        provider_id="asterion.prime-gateway",
                        boundary=str(contract["boundary"]),
                        feature_ids=tuple(contract["feature_ids"]),
                        assertion_ids=tuple(contract["assertion_ids"]),
                        fault_ids=tuple(contract["fault_ids"]),
                        provider_factory=provider_factory,
                        clock=_DeterministicClock(),
                        private_fixture_store=_CredentialFreeFixtureStore(),
                        fault_injector=_DeterministicFaultInjector(),
                        executor=executor,
                    ),
                )
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError("Prime RLM evidence adapter is invalid") from None

    for scenario_id, runner in runners:
        registry.register(scenario_id, runner)


def _validate_prime_rlm_observation(observation: PrimeRlmScenarioObservation) -> None:
    try:
        if type(observation) is not PrimeRlmScenarioObservation:
            raise ValueError
        rebuilt = build_prime_rlm_observation(
            scenario_id=observation.scenario_id,
            status=observation.status,
            checks=observation.checks,
            real_prime_runtime=observation.real_prime_runtime,
            fake_daemon=observation.fake_daemon,
            provider_operations=observation.provider_operations,
            model_credential_reads=observation.model_credential_reads,
        )
        if (
            observation.real_prime_runtime is not True
            or observation.fake_daemon is not False
            or observation.provider_operations != 0
            or observation.model_credential_reads != 0
            or observation.source_commit != PRIME_SESSION_CONTEXT_SOURCE_COMMIT
            or observation.artifact_lock != PRIME_SESSION_CONTEXT_ARTIFACT_LOCK
            or observation.command_id != PRIME_RLM_VERIFICATION_COMMAND_ID
            or observation.serialized_observations
            != rebuilt.serialized_observations
            or observation.evidence_id != rebuilt.evidence_id
            or (
                observation.scenario_id in PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS
                and observation.evidence_id is None
            )
            or (
                observation.scenario_id in PRIME_RLM_BOUNDED_SCENARIO_IDS
                and observation.evidence_id is not None
            )
            or any(
                sentinel in observation.serialized_observations
                for sentinel in _SESSION_CONTEXT_SENTINELS
            )
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError("Prime RLM evidence adapter is invalid") from None


def build_prime_session_context_observation(
    *,
    scenario_id: str,
    status: str,
    checks: Sequence[str],
    real_prime_runtime: bool,
    fake_daemon: bool,
    provider_operations: int,
    model_credential_reads: int,
) -> PrimeSessionContextScenarioObservation:
    """Build one canonical observation without granting provider authority."""

    try:
        contract = PRIME_SESSION_CONTEXT_SCENARIO_MATRIX[scenario_id]
        check_ids = tuple(checks)
        if (
            status not in {"PASS", "EXTERNAL-LIMITED"}
            or check_ids != PRIME_SESSION_CONTEXT_REQUIRED_CHECK_IDS[scenario_id]
            or any(_SAFE_ID.fullmatch(item) is None for item in check_ids)
            or type(real_prime_runtime) is not bool
            or type(fake_daemon) is not bool
            or type(provider_operations) is not int
            or provider_operations < 0
            or type(model_credential_reads) is not int
            or model_credential_reads < 0
        ):
            raise ValueError
        payload = {
            "artifact_lock": PRIME_SESSION_CONTEXT_ARTIFACT_LOCK,
            "assertion_ids": list(contract["assertion_ids"]),
            "boundary": contract["boundary"],
            "checks": list(check_ids),
            "command_id": PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID,
            "fake_daemon": fake_daemon,
            "fault_ids": list(contract["fault_ids"]),
            "feature_ids": list(contract["feature_ids"]),
            "model_credential_reads": model_credential_reads,
            "provider_id": "asterion.prime-gateway",
            "provider_operations": provider_operations,
            "real_prime_runtime": real_prime_runtime,
            "scenario_id": scenario_id,
            "source_commit": PRIME_SESSION_CONTEXT_SOURCE_COMMIT,
            "status": status,
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        evidence_id = None
        if real_prime_runtime and not fake_daemon:
            evidence_id = "evidence.session-context." + hashlib.sha256(
                serialized.encode("utf-8")
            ).hexdigest()
        return PrimeSessionContextScenarioObservation(
            scenario_id=scenario_id,
            status=status,
            checks=check_ids,
            real_prime_runtime=real_prime_runtime,
            fake_daemon=fake_daemon,
            provider_operations=provider_operations,
            model_credential_reads=model_credential_reads,
            source_commit=PRIME_SESSION_CONTEXT_SOURCE_COMMIT,
            artifact_lock=PRIME_SESSION_CONTEXT_ARTIFACT_LOCK,
            command_id=PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID,
            serialized_observations=serialized,
            evidence_id=evidence_id,
        )
    except (KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime session context observation is invalid"
        ) from None


def register_prime_session_context_scenarios(
    registry: ParityScenarioRegistry,
    observations: Sequence[PrimeSessionContextScenarioObservation],
    *,
    provider_factory: Callable[[], object],
) -> None:
    """Register nine exact runners without promoting fake or bounded evidence."""

    try:
        if (
            registry.provider_id != "asterion.prime-gateway"
            or type(observations) not in {list, tuple}
            or not callable(provider_factory)
            or any(
                scenario_id in registry.registered_scenario_ids
                for scenario_id in PRIME_SESSION_CONTEXT_SCENARIO_IDS
            )
        ):
            raise ParityScenarioRegistryError(
                "Prime session context evidence adapter is invalid"
            )
        items = tuple(observations)
        if (
            tuple(item.scenario_id for item in items)
            != PRIME_SESSION_CONTEXT_SCENARIO_IDS
        ):
            raise ParityScenarioRegistryError(
                "Prime session context evidence adapter is invalid"
            )
        runners: list[tuple[str, ParityScenarioRunner]] = []
        for observation in items:
            _validate_session_context_observation(observation)
            contract = PRIME_SESSION_CONTEXT_SCENARIO_MATRIX[
                observation.scenario_id
            ]
            result_status = (
                "pass" if observation.status == "PASS" else "external-limited"
            )
            reason_code = (
                "real-prime-provider-free-verified"
                if result_status == "pass"
                else "bounded-provider-authorization-required"
            )

            async def executor(
                factory,
                clock,
                private_fixture_store,
                fault_injector,
                *,
                scenario_id: str = observation.scenario_id,
                status: str = result_status,
                evidence_id: str | None = observation.evidence_id,
                reason: str = reason_code,
            ) -> ParityScenarioResult:
                del clock, private_fixture_store, fault_injector
                factory()
                return ParityScenarioResult(
                    scenario_id=scenario_id,
                    provider_id="asterion.prime-gateway",
                    status=status,
                    evidence_id=evidence_id,
                    reason_code=reason,
                )

            runners.append(
                (
                    observation.scenario_id,
                    ParityScenarioRunner(
                        scenario_id=observation.scenario_id,
                        provider_id="asterion.prime-gateway",
                        boundary=str(contract["boundary"]),
                        feature_ids=tuple(contract["feature_ids"]),
                        assertion_ids=tuple(contract["assertion_ids"]),
                        fault_ids=tuple(contract["fault_ids"]),
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
            "Prime session context evidence adapter is invalid"
        ) from None

    for scenario_id, runner in runners:
        registry.register(scenario_id, runner)


def _validate_session_context_observation(
    observation: PrimeSessionContextScenarioObservation,
) -> None:
    try:
        if type(observation) is not PrimeSessionContextScenarioObservation:
            raise ValueError
        expected_status = (
            "EXTERNAL-LIMITED"
            if observation.scenario_id
            in PRIME_SESSION_CONTEXT_BOUNDED_SCENARIO_IDS
            else "PASS"
        )
        rebuilt = build_prime_session_context_observation(
            scenario_id=observation.scenario_id,
            status=observation.status,
            checks=observation.checks,
            real_prime_runtime=observation.real_prime_runtime,
            fake_daemon=observation.fake_daemon,
            provider_operations=observation.provider_operations,
            model_credential_reads=observation.model_credential_reads,
        )
        if (
            observation.status != expected_status
            or observation.real_prime_runtime is not True
            or observation.fake_daemon is not False
            or observation.provider_operations != 0
            or observation.model_credential_reads != 0
            or observation.source_commit != PRIME_SESSION_CONTEXT_SOURCE_COMMIT
            or observation.artifact_lock != PRIME_SESSION_CONTEXT_ARTIFACT_LOCK
            or observation.command_id
            != PRIME_SESSION_CONTEXT_VERIFICATION_COMMAND_ID
            or observation.serialized_observations
            != rebuilt.serialized_observations
            or observation.evidence_id != rebuilt.evidence_id
            or observation.evidence_id is None
            or any(
                sentinel in observation.serialized_observations
                for sentinel in _SESSION_CONTEXT_SENTINELS
            )
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime session context evidence adapter is invalid"
        ) from None


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
                        assertion_ids=tuple(adapter["assertion_ids"]),
                        fault_ids=tuple(adapter["fault_ids"]),
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
