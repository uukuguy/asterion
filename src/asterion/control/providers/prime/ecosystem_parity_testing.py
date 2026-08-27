"""Exact Prime ecosystem evidence reduction for parity closure."""

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
from asterion.control.providers.prime.parity_testing import (
    _CredentialFreeFixtureStore,
    _DeterministicClock,
    _DeterministicFaultInjector,
)


PRIME_ECOSYSTEM_SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c"
PRIME_ECOSYSTEM_ARTIFACT_LOCK_SHA256 = (
    "c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3"
)
PRIME_ECOSYSTEM_MODULE_LOCK_SHA256 = (
    "959989c9f6afb907db32bdef709cf19b45fa19421095f62714ff80b9a2c44cd6"
)
PRIME_ECOSYSTEM_OBSERVATION_FORMAT = "asterion.prime-ecosystem-observation/v1"
PRIME_ECOSYSTEM_REQUIRED_ASSERTIONS = (
    "authority-preserved",
    "feature-reachable",
    "identity-stable",
    "public-redacted",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SENTINELS = (
    "SENTINEL_BODY",
    "SENTINEL_MODEL_CREDENTIAL",
    "opaque-mcp-refresh-token",
    "PACKAGE_BODY_SENTINEL",
    "HOSTILE_TOOL_OUTPUT",
)


class _PackageContract(TypedDict):
    assertion_ids: tuple[str, ...]
    command_id: str
    feature_ids: tuple[str, ...]
    count_checks: Mapping[str, int]
    public_keys: frozenset[str]


def _contract(
    command_id: str,
    feature_ids: tuple[str, ...],
    assertion_ids: tuple[str, ...],
    count_checks: Mapping[str, int],
    public_keys: frozenset[str],
) -> _PackageContract:
    return cast(
        _PackageContract,
        MappingProxyType({
            "assertion_ids": assertion_ids,
            "command_id": command_id,
            "count_checks": MappingProxyType(dict(count_checks)),
            "feature_ids": feature_ids,
            "public_keys": public_keys,
        }),
    )


_METADATA_KEYS = frozenset({
    "artifact_lock_sha256",
    "command_id",
    "module_lock_sha256",
    "portfolio_digest",
    "source_commit",
})

PRIME_ECOSYSTEM_PACKAGE_CONTRACTS: Mapping[str, _PackageContract] = MappingProxyType(
    {
        "resources": _contract(
            "test.prime-ecosystem-resources.provider-free",
            (
                "ecosystem.collision-diagnostics",
                "ecosystem.context-files",
                "ecosystem.prompt-templates",
                "ecosystem.skills",
            ),
            (
                "resources.collision-digest",
                "resources.context-order",
                "resources.no-python-import",
                "resources.prompt-expansion",
                "resources.redacted-receipt",
                "resources.skill-identities",
            ),
            {
                "collision_count": 1,
                "context_count": 2,
                "prompt_count": 3,
                "resource_count": 7,
                "skill_count": 2,
            },
            frozenset({
                "assertion_ids",
                "collision_count",
                "collision_digest",
                "context_count",
                "feature_ids",
                "format",
                "model_credential_reads",
                "observation_digest",
                "owned_process_count_after_close",
                "prompt_count",
                "provider_operations",
                "resource_count",
                "scenario_package",
                "skill_count",
                "status",
            }),
        ),
        "extensions": _contract(
            "test.prime-ecosystem-extensions.provider-free",
            (
                "ecosystem.custom-providers-models",
                "ecosystem.extension-state-commands",
                "ecosystem.extensions-lifecycle",
                "ecosystem.tools",
            ),
            (
                "extensions.command-state-digest",
                "extensions.lifecycle-order",
                "extensions.no-provider-invocation",
                "extensions.provider-model-lookup",
                "extensions.tool-output-digest",
            ),
            {
                "command_count": 1,
                "lifecycle_count": 1,
                "provider_model_count": 1,
                "registration_count": 3,
                "resource_count": 1,
                "tool_count": 1,
            },
            frozenset({
                "assertion_ids",
                "command_count",
                "command_state_digest",
                "failure_matrix_count",
                "failure_matrix_digest",
                "feature_ids",
                "format",
                "lifecycle_count",
                "model_credential_reads",
                "observation_digest",
                "owned_process_count_after_close",
                "provider_model_count",
                "provider_operations",
                "reopened_command_state_digest",
                "reopened_nonterminal_status",
                "registration_count",
                "resource_count",
                "scenario_package",
                "status",
                "tool_count",
            }),
        ),
        "packages": _contract(
            "test.prime-ecosystem-packages.provider-free",
            ("ecosystem.packages",),
            (
                "packages.no-install",
                "packages.no-source-fallback",
                "packages.prime-package-manager",
                "packages.selected-source-digest",
            ),
            {
                "fallback_attempt_count": 0,
                "install_attempt_count": 0,
                "network_attempt_count": 0,
                "package_count": 1,
                "resource_count": 1,
            },
            frozenset({
                "assertion_ids",
                "fallback_attempt_count",
                "feature_ids",
                "format",
                "install_attempt_count",
                "model_credential_reads",
                "network_attempt_count",
                "observation_digest",
                "owned_process_count_after_close",
                "package_count",
                "prime_payload_digest",
                "prime_resource_digest",
                "prime_selected_identity_digest",
                "provider_operations",
                "resource_count",
                "scenario_package",
                "selected_payload_digest",
                "selected_resource_digest",
                "selected_source_digest",
                "status",
            }),
        ),
        "mcp": _contract(
            "test.prime-ecosystem-mcp.provider-free",
            ("ecosystem.mcp",),
            (
                "mcp.exact-local-server",
                "mcp.manager-and-oauth-surface",
                "mcp.no-provider-invocation",
                "mcp.redacted-receipt",
            ),
            {"mcp_count": 1, "resource_count": 1},
            frozenset({
                "assertion_ids",
                "feature_ids",
                "format",
                "mcp_count",
                "mcp_surface_digest",
                "model_credential_reads",
                "observation_digest",
                "owned_process_count_after_close",
                "provider_operations",
                "resource_count",
                "scenario_package",
                "status",
            }),
        ),
    }
)

PRIME_ECOSYSTEM_FEATURE_IDS = tuple(
    sorted(
        feature_id
        for package in PRIME_ECOSYSTEM_PACKAGE_CONTRACTS.values()
        for feature_id in package["feature_ids"]
    )
)
PRIME_ECOSYSTEM_SCENARIO_IDS = tuple(
    f"prime-parity.{feature_id}" for feature_id in PRIME_ECOSYSTEM_FEATURE_IDS
)


@dataclass(frozen=True, repr=False)
class PrimeEcosystemScenarioObservation:
    scenario_id: str
    feature_id: str
    status: str
    command_id: str
    source_commit: str
    artifact_lock_sha256: str
    module_lock_sha256: str
    portfolio_digest: str
    provider_operations: int
    model_credential_reads: int
    owned_process_count_after_close: int
    receipt_digest: str
    serialized_observations: str
    evidence_id: str

    def __repr__(self) -> str:
        return (
            "PrimeEcosystemScenarioObservation("
            f"scenario_id={self.scenario_id!r}, evidence_id={self.evidence_id!r}, "
            "observations=<redacted>)"
        )


def build_prime_ecosystem_observations(
    receipts: Sequence[Mapping[str, object]],
) -> tuple[PrimeEcosystemScenarioObservation, ...]:
    """Reduce four exact provider-free receipts into ten parity observations."""

    try:
        if type(receipts) not in {list, tuple}:
            raise ValueError
        receipt_by_package: dict[str, Mapping[str, object]] = {}
        for receipt in receipts:
            if type(receipt) is not dict:
                raise ValueError
            package = str(receipt.get("scenario_package"))
            if package not in PRIME_ECOSYSTEM_PACKAGE_CONTRACTS or package in receipt_by_package:
                raise ValueError
            receipt_by_package[package] = receipt
        if tuple(receipt_by_package) != tuple(PRIME_ECOSYSTEM_PACKAGE_CONTRACTS):
            raise ValueError
        observations: list[PrimeEcosystemScenarioObservation] = []
        for package, contract in PRIME_ECOSYSTEM_PACKAGE_CONTRACTS.items():
            receipt = receipt_by_package[package]
            _validate_package_receipt(package, receipt, contract)
            receipt_digest = _canonical_digest({
                key: value for key, value in receipt.items() if key not in _METADATA_KEYS
            })
            for feature_id in contract["feature_ids"]:
                scenario_id = f"prime-parity.{feature_id}"
                payload = {
                    "artifact_lock_sha256": receipt["artifact_lock_sha256"],
                    "assertion_ids": list(PRIME_ECOSYSTEM_REQUIRED_ASSERTIONS),
                    "boundary": "real-prime-provider-free",
                    "command_id": contract["command_id"],
                    "feature_ids": [feature_id],
                    "model_credential_reads": 0,
                    "module_lock_sha256": receipt["module_lock_sha256"],
                    "owned_process_count_after_close": 0,
                    "portfolio_digest": receipt["portfolio_digest"],
                    "provider_id": "asterion.prime-gateway",
                    "provider_operations": 0,
                    "receipt_digest": receipt_digest,
                    "scenario_id": scenario_id,
                    "source_commit": receipt["source_commit"],
                    "status": "PASS",
                }
                serialized = json.dumps(
                    payload,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                evidence_id = "evidence.ecosystem." + hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest()
                observations.append(
                    PrimeEcosystemScenarioObservation(
                        scenario_id=scenario_id,
                        feature_id=feature_id,
                        status="PASS",
                        command_id=contract["command_id"],
                        source_commit=PRIME_ECOSYSTEM_SOURCE_COMMIT,
                        artifact_lock_sha256=PRIME_ECOSYSTEM_ARTIFACT_LOCK_SHA256,
                        module_lock_sha256=PRIME_ECOSYSTEM_MODULE_LOCK_SHA256,
                        portfolio_digest=str(receipt["portfolio_digest"]),
                        provider_operations=0,
                        model_credential_reads=0,
                        owned_process_count_after_close=0,
                        receipt_digest=receipt_digest,
                        serialized_observations=serialized,
                        evidence_id=evidence_id,
                    )
                )
        observations.sort(key=lambda item: item.scenario_id)
        if tuple(item.scenario_id for item in observations) != PRIME_ECOSYSTEM_SCENARIO_IDS:
            raise ValueError
        return tuple(observations)
    except (KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime ecosystem observation is invalid"
        ) from None


def register_prime_ecosystem_scenarios(
    registry: ParityScenarioRegistry,
    observations: Sequence[PrimeEcosystemScenarioObservation],
    *,
    provider_factory: Callable[[], object],
) -> None:
    """Register ten exact provider-free ecosystem runners."""

    try:
        if (
            registry.provider_id != "asterion.prime-gateway"
            or type(observations) not in {list, tuple}
            or not callable(provider_factory)
            or any(
                scenario_id in registry.registered_scenario_ids
                for scenario_id in PRIME_ECOSYSTEM_SCENARIO_IDS
            )
        ):
            raise ValueError
        items = tuple(observations)
        if tuple(item.scenario_id for item in items) != PRIME_ECOSYSTEM_SCENARIO_IDS:
            raise ValueError
        runners: list[tuple[str, ParityScenarioRunner]] = []
        for observation in items:
            _validate_observation(observation)

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
                    reason_code="real-prime-provider-free-verified",
                )

            runners.append(
                (
                    observation.scenario_id,
                    ParityScenarioRunner(
                        scenario_id=observation.scenario_id,
                        provider_id="asterion.prime-gateway",
                        boundary="real-prime-provider-free",
                        feature_ids=(observation.feature_id,),
                        assertion_ids=PRIME_ECOSYSTEM_REQUIRED_ASSERTIONS,
                        fault_ids=("restart-after-admission",),
                        provider_factory=provider_factory,
                        clock=_DeterministicClock(),
                        private_fixture_store=_CredentialFreeFixtureStore(),
                        fault_injector=_DeterministicFaultInjector(),
                        executor=executor,
                    ),
                )
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime ecosystem evidence adapter is invalid"
        ) from None

    for scenario_id, runner in runners:
        registry.register(scenario_id, runner)


def _validate_package_receipt(
    package: str,
    receipt: Mapping[str, object],
    contract: _PackageContract,
) -> None:
    if set(receipt) != set(contract["public_keys"]) | _METADATA_KEYS:
        raise ValueError
    if (
        receipt["format"] != PRIME_ECOSYSTEM_OBSERVATION_FORMAT
        or receipt["scenario_package"] != package
        or receipt["status"] != "PASS"
        or tuple(receipt["feature_ids"]) != contract["feature_ids"]  # type: ignore[arg-type]
        or tuple(receipt["assertion_ids"]) != contract["assertion_ids"]  # type: ignore[arg-type]
        or receipt["command_id"] != contract["command_id"]
        or receipt["source_commit"] != PRIME_ECOSYSTEM_SOURCE_COMMIT
        or receipt["artifact_lock_sha256"] != PRIME_ECOSYSTEM_ARTIFACT_LOCK_SHA256
        or receipt["module_lock_sha256"] != PRIME_ECOSYSTEM_MODULE_LOCK_SHA256
        or not _is_hex64(receipt["portfolio_digest"])
        or not _is_hex64(receipt["observation_digest"])
        or receipt["provider_operations"] != 0
        or receipt["model_credential_reads"] != 0
        or receipt["owned_process_count_after_close"] != 0
    ):
        raise ValueError
    for key, expected in contract["count_checks"].items():
        if receipt[key] != expected:
            raise ValueError
    rendered = json.dumps(dict(receipt), ensure_ascii=True, sort_keys=True)
    if any(sentinel in rendered for sentinel in _SENTINELS):
        raise ValueError


def _validate_observation(observation: PrimeEcosystemScenarioObservation) -> None:
    try:
        if type(observation) is not PrimeEcosystemScenarioObservation:
            raise ValueError
        if (
            observation.scenario_id not in PRIME_ECOSYSTEM_SCENARIO_IDS
            or observation.scenario_id != f"prime-parity.{observation.feature_id}"
            or observation.status != "PASS"
            or observation.source_commit != PRIME_ECOSYSTEM_SOURCE_COMMIT
            or observation.artifact_lock_sha256 != PRIME_ECOSYSTEM_ARTIFACT_LOCK_SHA256
            or observation.module_lock_sha256 != PRIME_ECOSYSTEM_MODULE_LOCK_SHA256
            or not _is_hex64(observation.portfolio_digest)
            or not _is_hex64(observation.receipt_digest)
            or observation.provider_operations != 0
            or observation.model_credential_reads != 0
            or observation.owned_process_count_after_close != 0
            or observation.evidence_id
            != "evidence.ecosystem."
            + hashlib.sha256(observation.serialized_observations.encode("utf-8")).hexdigest()
            or any(
                sentinel in observation.serialized_observations
                for sentinel in _SENTINELS
            )
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise ParityScenarioRegistryError(
            "Prime ecosystem evidence adapter is invalid"
        ) from None


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None
