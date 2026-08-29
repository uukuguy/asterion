"""Atomic reduction of six Prime operational receipts into parity rows."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
    ParityScenarioResult,
    ParityScenarioRunner,
)


PRIME_OPERATION_FEATURES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "auth": ("operation.auth",),
        "model-selection": ("operation.model-selection",),
        "settings-keybindings": ("operation.settings-keybindings",),
        "telemetry-usage": ("operation.telemetry-usage",),
        "doctor": ("operation.doctor",),
        "controlled-update-restart": (
            "operation.controlled-update-restart",
        ),
    }
)
PRIME_OPERATION_SCENARIO_IDS = tuple(
    sorted(
        f"prime-parity.{feature_ids[0]}"
        for feature_ids in PRIME_OPERATION_FEATURES.values()
    )
)
PRIME_OPERATION_REQUIRED_ASSERTIONS = (
    "authority-preserved",
    "feature-reachable",
    "identity-stable",
    "public-redacted",
)
PRIME_OPERATION_COMMAND_ID = "test.prime-operational-parity.provider-free"
PRIME_OPERATION_RECEIPT_FORMAT = "asterion.prime-operational-receipt/v1"
PRIME_OPERATION_LOCK_FORMAT = "asterion.prime-operational-module-lock/v1"
PRIME_OPERATION_SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c"
PRIME_OPERATION_DEPENDENCY_LOCK_SHA256 = (
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8"
)
PRIME_OPERATION_DEPENDENCY_TREE_DIGEST = (
    "874f48a650a1ea7d12e4b9ecfc4ce750515c1ea0642e297f43cb2c8ea9dd4a76"
)
PRIME_OPERATION_MODULE_DIGEST = (
    "6326ee8a6433f52c78210297c6bf499ab561d171ce1caaf51a107216392be041"
)
PRIME_OPERATION_RUNTIME_DIGEST = (
    "ea7cd4333f84cb10727d2feeba58ddfd177c9ae35601f505e346e085280a00b6"
)
PRIME_OPERATION_WORKSPACE_DIGEST = (
    "4e49f896d35be953c7939c2daaf5fcf884092f3b10370778e1643a54185c4033"
)
PRIME_OPERATION_NODE_RUNTIME = "v22.23.2"
PRIME_OPERATION_EFFECT_COUNTS = MappingProxyType(
    {
        "credential_reads": 0,
        "network_requests": 0,
        "provider_operations": 0,
        "retained_processes": 0,
        "stdout_writes": 0,
        "unauthorized_uploads": 0,
    }
)
_SCENARIO_COUNTERS = (
    "fake_coordinator_calls",
    "host_service_calls",
    "injected_sink_calls",
    "mock_refresh_calls",
    "reconcile_calls",
    "scenario_calls",
)
_SAFE_INT_LIMIT = 9_007_199_254_740_991
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_NODE_RUNTIME = re.compile(r"^v([0-9]+)\.([0-9]+)\.([0-9]+)$")
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_SENTINELS = (
    "SENTINEL_",
    "SENTINEL_BODY",
    "SENTINEL_SECRET",
    "SENTINEL_TOKEN",
)
_FORBIDDEN_KEYS = frozenset(
    {
        "authorization",
        "body",
        "credential",
        "destination",
        "path",
        "prompt",
        "refresh_token",
        "secret",
        "text",
        "token",
    }
)
_COMMON_KEYS = frozenset(
    {
        "assertion_ids",
        "built_anchor_digests",
        "dependency_lock_sha256",
        "dependency_tree_digest",
        "effect_counts",
        "failure_matrix",
        "fault_ids",
        "feature_ids",
        "format",
        "module_digest",
        "node_runtime",
        "package",
        "redaction_status",
        "runtime_digest",
        "scenario_counts",
        "scenario_id",
        "source_anchor_digests",
        "source_commit",
        "status",
        "workspace_digest",
    }
)
_PACKAGE_EXTRA_KEYS = MappingProxyType(
    {
        "auth": frozenset({"refresh_outcomes"}),
        "model-selection": frozenset({"model_transition"}),
        "settings-keybindings": frozenset({"key_chords", "settings"}),
        "telemetry-usage": frozenset({"usage_observation"}),
        "doctor": frozenset({"diagnostic"}),
        "controlled-update-restart": frozenset({"restart"}),
    }
)
_PACKAGE_FAILURES = MappingProxyType(
    {
        "auth": (
            "mock-refresh-failure",
            "restart-after-admission",
        ),
        "model-selection": (
            "fixture-catalog-mismatch",
            "restart-after-admission",
        ),
        "settings-keybindings": (
            "legacy-alias",
            "restart-after-admission",
        ),
        "telemetry-usage": (
            "injected-sink-failure",
            "restart-after-admission",
        ),
        "doctor": (
            "diagnostic-inspection-failure",
            "restart-after-admission",
        ),
        "controlled-update-restart": (
            "reconcile-identity-mismatch",
            "restart-after-admission",
        ),
    }
)
_EXPECTED_SOURCE_ANCHOR_DIGESTS = MappingProxyType(
    {
        "packages/coding-agent/src/core/agent-session.ts": (
            "44d66f879ac71e4fe1e520b19f7d1073e5311f62373ef62dd5dbee97f4f0b5e0"
        ),
        "packages/coding-agent/src/core/auth-storage.ts": (
            "8cb1c7dcaab1c017136f5a1626faed45d7ea9b61e845d88519a18b4787c9717b"
        ),
        "packages/coding-agent/src/core/diagnostics.ts": (
            "1914431098db1b4638e4fb3582ac22e8125356c4ab024671494f565c6d5ffb39"
        ),
        "packages/coding-agent/src/core/keybindings.ts": (
            "ee493ac30dc1a3ca20415f6b0e8125cb9c1b252d1eed4fde876af715018f704a"
        ),
        "packages/coding-agent/src/core/resource-loader.ts": (
            "b4ac632adeb2960cddcc3ff6c6f7a87d133feacb14e8a6e8ab802e5720d8c852"
        ),
        "packages/coding-agent/src/core/settings-manager.ts": (
            "9fa62f6e72527e8aefe4278954e51464e73b7b8a22fbe25740d742a3ddd0b8c9"
        ),
        "packages/coding-agent/src/core/telemetry.ts": (
            "c42df2bd87ad5ccfb4c8282de8abdddd5f04ab1ca13b7e77606bccf9e0b45d2b"
        ),
        "packages/coding-agent/src/core/usage.ts": (
            "7a43a041f30f8233648e6d57f047cc6534b7fa0cf7b447e42c6815dab5807a0e"
        ),
        "packages/coding-agent/src/package-manager-cli.ts": (
            "349b464c03982ebaa0aca02d7bff01b9d72a5e4c86c3f0b60c802e78637a3027"
        ),
    }
)
_EXPECTED_BUILT_ANCHOR_DIGESTS = MappingProxyType(
    {
        "packages/coding-agent/dist/core/agent-session.js": (
            "0fe28b4cd8bc093ddee791e86f8d594878f5119e5b9105c32d1dc6cd7d4d8321"
        ),
        "packages/coding-agent/dist/core/auth-storage.js": (
            "fa45c9ed883363475bbca80839ec42d518597c3671d2cda9d320f083f1393c76"
        ),
        "packages/coding-agent/dist/core/diagnostics.js": (
            "b84fc4bac1fa2a4554cbc33b8b20f56908a2de8c302e63178c2981bfd185dc08"
        ),
        "packages/coding-agent/dist/core/keybindings.js": (
            "e147e1bef2aeb10d4a034e48ea63f7a3cea85fd07e2947e4ac9499c0a2dc4b2f"
        ),
        "packages/coding-agent/dist/core/resource-loader.js": (
            "48517fd47b99a1554b53f1c7ed3a38502304d0e82c29ce39b3c3eb3e9ab64f48"
        ),
        "packages/coding-agent/dist/core/settings-manager.js": (
            "867be3ac28592431d772f9ffdbd3d5a2e24dc2f9932c2de1baa41a4d2d8cfe64"
        ),
        "packages/coding-agent/dist/core/telemetry.js": (
            "fb2a879d5beb9db95de88e4735eb86a359f6a12e8aea29e3bd7ee822c482850a"
        ),
        "packages/coding-agent/dist/core/usage.js": (
            "de168e741a4aaa2fc58ba5a14c0b5f87055d5ee9665c5eacf8ae0994079f48ae"
        ),
        "packages/coding-agent/dist/package-manager-cli.js": (
            "2f8472b8d9de974123de3584630b92285b9ebf980d1614891980049c9752ca3c"
        ),
    }
)


class PrimeOperationalParityError(ParityScenarioRegistryError):
    """Raised with a fixed message when operational evidence fails closed."""


@dataclass(frozen=True, repr=False)
class PrimeOperationalScenarioObservation:
    scenario_id: str
    feature_id: str
    package: str
    status: str
    command_id: str
    source_commit: str
    dependency_lock_sha256: str
    dependency_tree_digest: str
    module_digest: str
    runtime_digest: str
    workspace_digest: str
    node_runtime: str
    source_anchor_digests: Mapping[str, str]
    built_anchor_digests: Mapping[str, str]
    effect_counts: Mapping[str, int]
    scenario_counts: Mapping[str, int]
    provider_operations: int
    receipt_digest: str
    serialized_observations: str
    evidence_id: str

    def __repr__(self) -> str:
        return (
            "PrimeOperationalScenarioObservation("
            f"scenario_id={self.scenario_id!r}, evidence_id={self.evidence_id!r}, "
            "observations=<redacted>)"
        )


def build_prime_operational_observations(
    receipts: Mapping[str, Mapping[str, object]],
) -> tuple[PrimeOperationalScenarioObservation, ...]:
    """Reduce exactly six immutable package receipts into six parity observations."""

    try:
        _require_exact_six_receipts(receipts)
        validated = tuple(
            _validate_operational_receipt(package, receipts[package])
            for package in sorted(receipts)
        )
        observations = tuple(_observation(item) for item in validated)
        if tuple(item.scenario_id for item in observations) != PRIME_OPERATION_SCENARIO_IDS:
            raise ValueError
        return observations
    except (AttributeError, KeyError, TypeError, ValueError):
        raise PrimeOperationalParityError(
            "Prime operational receipt closure is invalid"
        ) from None


def register_prime_operational_scenarios(
    registry: ParityScenarioRegistry,
    observations: Sequence[PrimeOperationalScenarioObservation],
    *,
    provider_factory: Callable[[], object],
) -> None:
    """Register all six Prime operation scenarios atomically."""

    try:
        if (
            registry.provider_id != "asterion.prime-gateway"
            or type(observations) not in {list, tuple}
            or not callable(provider_factory)
            or any(
                scenario_id in registry.registered_scenario_ids
                for scenario_id in PRIME_OPERATION_SCENARIO_IDS
            )
        ):
            raise ValueError
        items = tuple(observations)
        if tuple(item.scenario_id for item in items) != PRIME_OPERATION_SCENARIO_IDS:
            raise ValueError
        runners: list[tuple[str, ParityScenarioRunner]] = []
        for observation in items:
            _validate_observation(observation)

            async def executor(
                factory: Callable[[], object],
                clock: object,
                private_fixture_store: object,
                fault_injector: object,
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
                        assertion_ids=PRIME_OPERATION_REQUIRED_ASSERTIONS,
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
        raise PrimeOperationalParityError(
            "Prime operational evidence adapter is invalid"
        ) from None

    try:
        registry.register_many(runners)
    except ParityScenarioRegistryError:
        raise PrimeOperationalParityError(
            "Prime operational evidence adapter is invalid"
        ) from None


def _require_exact_six_receipts(
    receipts: Mapping[str, Mapping[str, object]],
) -> None:
    if type(receipts) is not _MAPPING_PROXY_TYPE:
        raise ValueError
    if set(receipts) != set(PRIME_OPERATION_FEATURES):
        raise ValueError
    for receipt in receipts.values():
        if type(receipt) is not dict:
            raise ValueError


def _validate_operational_receipt(
    package: str, receipt: Mapping[str, object]
) -> Mapping[str, object]:
    if set(receipt) != _COMMON_KEYS | _PACKAGE_EXTRA_KEYS[package]:
        raise ValueError
    _validate_public_receipt(receipt)
    feature_id = PRIME_OPERATION_FEATURES[package][0]
    if (
        receipt["format"] != PRIME_OPERATION_RECEIPT_FORMAT
        or receipt["package"] != package
        or receipt["status"] != "pass"
        or receipt["redaction_status"] != "pass"
        or receipt["feature_ids"] != [feature_id]
        or receipt["scenario_id"] != f"prime-parity.{feature_id}"
        or receipt["assertion_ids"] != list(PRIME_OPERATION_REQUIRED_ASSERTIONS)
        or receipt["fault_ids"] != ["restart-after-admission"]
        or receipt["source_commit"] != PRIME_OPERATION_SOURCE_COMMIT
        or receipt["dependency_lock_sha256"]
        != PRIME_OPERATION_DEPENDENCY_LOCK_SHA256
        or receipt["dependency_tree_digest"]
        != PRIME_OPERATION_DEPENDENCY_TREE_DIGEST
        or receipt["module_digest"] != PRIME_OPERATION_MODULE_DIGEST
        or receipt["runtime_digest"] != PRIME_OPERATION_RUNTIME_DIGEST
        or receipt["workspace_digest"] != PRIME_OPERATION_WORKSPACE_DIGEST
        or receipt["node_runtime"] != PRIME_OPERATION_NODE_RUNTIME
        or not _supported_node_runtime(str(receipt["node_runtime"]))
        or receipt["source_anchor_digests"] != dict(_EXPECTED_SOURCE_ANCHOR_DIGESTS)
        or receipt["built_anchor_digests"] != dict(_EXPECTED_BUILT_ANCHOR_DIGESTS)
        or receipt["effect_counts"] != dict(PRIME_OPERATION_EFFECT_COUNTS)
    ):
        raise ValueError
    _validate_scenario_counts(package, receipt["scenario_counts"])
    _validate_failure_matrix(package, receipt["failure_matrix"])
    _validate_package_payload(package, receipt)
    return receipt


def _validate_scenario_counts(package: str, value: object) -> None:
    if type(value) is not dict or tuple(value) != _SCENARIO_COUNTERS:
        raise ValueError
    expected = {
        "fake_coordinator_calls": (
            1 if package == "controlled-update-restart" else 0
        ),
        "host_service_calls": 1,
        "injected_sink_calls": 1 if package == "telemetry-usage" else 0,
        "mock_refresh_calls": 1 if package == "auth" else 0,
        "reconcile_calls": 1 if package == "controlled-update-restart" else 0,
        "scenario_calls": 1,
    }
    if value != expected:
        raise ValueError


def _validate_failure_matrix(package: str, value: object) -> None:
    expected = [
        {"case_id": case_id, "status": "rejected"}
        for case_id in _PACKAGE_FAILURES[package]
    ]
    if value != expected:
        raise ValueError


def _validate_package_payload(package: str, receipt: Mapping[str, object]) -> None:
    if package == "auth":
        if receipt["refresh_outcomes"] != [
            "failure-rejected",
            "success-redacted",
        ]:
            raise ValueError
    elif package == "model-selection":
        if receipt["model_transition"] != [
            "fixture-catalog-1",
            "1",
            "fixture.model.small",
            "low",
            "standard",
            "fixture.transport-1",
        ]:
            raise ValueError
    elif package == "settings-keybindings":
        if receipt["settings"] != [
            ["global", "theme", "enum"],
            ["global", "telemetry.enabled", "boolean"],
            ["global", "app.session.new", "key-chord"],
            ["global", "app.input.clear", "key-chord"],
            ["global", "app.interrupt", "key-chord"],
        ]:
            raise ValueError
        if receipt["key_chords"] != {
            "app.input.clear": "Ctrl+L",
            "app.interrupt": "Ctrl+C",
            "app.session.new": "Ctrl+N",
        }:
            raise ValueError
    elif package == "telemetry-usage":
        if receipt["usage_observation"] != [
            "fixture.source",
            "agent run completed",
            0,
            0,
            "sink-failure-observed",
        ]:
            raise ValueError
    elif package == "doctor":
        diagnostic = receipt["diagnostic"]
        if (
            type(diagnostic) is not list
            or len(diagnostic) != 4
            or diagnostic[:3]
            != ["resource-loader.theme", "warning", "theme-path-missing"]
            or type(diagnostic[3]) is not str
            or _HEX64.fullmatch(diagnostic[3]) is None
        ):
            raise ValueError
    elif package == "controlled-update-restart":
        restart = receipt["restart"]
        if (
            type(restart) is not list
            or len(restart) != 6
            or restart[:4]
            != [
                "artifact-prime-1",
                "prime-daemon-1",
                "asterion.agent-runtime/v1",
                "checkpoint-prime-1",
            ]
            or type(restart[4]) is not str
            or _HEX64.fullmatch(restart[4]) is None
            or restart[5] != "uncertain-reconciled"
        ):
            raise ValueError


def _observation(
    receipt: Mapping[str, object],
) -> PrimeOperationalScenarioObservation:
    package = str(receipt["package"])
    feature_id = PRIME_OPERATION_FEATURES[package][0]
    scenario_id = f"prime-parity.{feature_id}"
    receipt_digest = _canonical_digest(receipt)
    payload = {
        "assertion_ids": list(PRIME_OPERATION_REQUIRED_ASSERTIONS),
        "boundary": "real-prime-provider-free",
        "built_anchor_digests": receipt["built_anchor_digests"],
        "command_id": PRIME_OPERATION_COMMAND_ID,
        "dependency_lock_sha256": PRIME_OPERATION_DEPENDENCY_LOCK_SHA256,
        "dependency_tree_digest": PRIME_OPERATION_DEPENDENCY_TREE_DIGEST,
        "effect_counts": receipt["effect_counts"],
        "feature_ids": [feature_id],
        "fault_ids": ["restart-after-admission"],
        "module_digest": PRIME_OPERATION_MODULE_DIGEST,
        "node_runtime": PRIME_OPERATION_NODE_RUNTIME,
        "package": package,
        "provider_id": "asterion.prime-gateway",
        "provider_operations": 0,
        "receipt_digest": receipt_digest,
        "runtime_digest": PRIME_OPERATION_RUNTIME_DIGEST,
        "scenario_counts": receipt["scenario_counts"],
        "scenario_id": scenario_id,
        "source_anchor_digests": receipt["source_anchor_digests"],
        "source_commit": PRIME_OPERATION_SOURCE_COMMIT,
        "status": "PASS",
        "workspace_digest": PRIME_OPERATION_WORKSPACE_DIGEST,
    }
    serialized = _canonical(payload)
    return PrimeOperationalScenarioObservation(
        scenario_id=scenario_id,
        feature_id=feature_id,
        package=package,
        status="PASS",
        command_id=PRIME_OPERATION_COMMAND_ID,
        source_commit=PRIME_OPERATION_SOURCE_COMMIT,
        dependency_lock_sha256=PRIME_OPERATION_DEPENDENCY_LOCK_SHA256,
        dependency_tree_digest=PRIME_OPERATION_DEPENDENCY_TREE_DIGEST,
        module_digest=PRIME_OPERATION_MODULE_DIGEST,
        runtime_digest=PRIME_OPERATION_RUNTIME_DIGEST,
        workspace_digest=PRIME_OPERATION_WORKSPACE_DIGEST,
        node_runtime=PRIME_OPERATION_NODE_RUNTIME,
        source_anchor_digests=MappingProxyType(
            dict(_EXPECTED_SOURCE_ANCHOR_DIGESTS)
        ),
        built_anchor_digests=MappingProxyType(
            dict(_EXPECTED_BUILT_ANCHOR_DIGESTS)
        ),
        effect_counts=MappingProxyType(dict(PRIME_OPERATION_EFFECT_COUNTS)),
        scenario_counts=MappingProxyType(
            dict(cast(Mapping[str, int], receipt["scenario_counts"]))
        ),
        provider_operations=0,
        receipt_digest=receipt_digest,
        serialized_observations=serialized,
        evidence_id="evidence.operation."
        + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )


def _validate_observation(observation: PrimeOperationalScenarioObservation) -> None:
    if type(observation) is not PrimeOperationalScenarioObservation:
        raise ValueError
    package = observation.package
    expected_scenario = f"prime-parity.{PRIME_OPERATION_FEATURES[package][0]}"
    if (
        observation.scenario_id != expected_scenario
        or observation.feature_id != PRIME_OPERATION_FEATURES[package][0]
        or observation.status != "PASS"
        or observation.command_id != PRIME_OPERATION_COMMAND_ID
        or observation.source_commit != PRIME_OPERATION_SOURCE_COMMIT
        or observation.dependency_lock_sha256
        != PRIME_OPERATION_DEPENDENCY_LOCK_SHA256
        or observation.dependency_tree_digest
        != PRIME_OPERATION_DEPENDENCY_TREE_DIGEST
        or observation.module_digest != PRIME_OPERATION_MODULE_DIGEST
        or observation.runtime_digest != PRIME_OPERATION_RUNTIME_DIGEST
        or observation.workspace_digest != PRIME_OPERATION_WORKSPACE_DIGEST
        or observation.node_runtime != PRIME_OPERATION_NODE_RUNTIME
        or observation.source_anchor_digests != _EXPECTED_SOURCE_ANCHOR_DIGESTS
        or observation.built_anchor_digests != _EXPECTED_BUILT_ANCHOR_DIGESTS
        or observation.provider_operations != 0
        or observation.effect_counts != PRIME_OPERATION_EFFECT_COUNTS
        or _HEX64.fullmatch(observation.receipt_digest) is None
        or observation.evidence_id
        != "evidence.operation."
        + hashlib.sha256(
            observation.serialized_observations.encode("utf-8")
        ).hexdigest()
        or any(
            sentinel in observation.serialized_observations
            for sentinel in _SENTINELS
        )
    ):
        raise ValueError


def _validate_public_receipt(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if (
                type(key) is not str
                or key.casefold() in _FORBIDDEN_KEYS
                or any(sentinel in key.upper() for sentinel in _SENTINELS)
            ):
                raise ValueError
            _validate_public_receipt(item)
        return
    if type(value) is list:
        for item in value:
            _validate_public_receipt(item)
        return
    if type(value) is str:
        if (
            value.startswith(("/", "~"))
            or "\\" in value
            or any(sentinel in value.upper() for sentinel in _SENTINELS)
        ):
            raise ValueError
        return
    if value is None or type(value) is bool:
        return
    if type(value) is int and -_SAFE_INT_LIMIT <= value <= _SAFE_INT_LIMIT:
        return
    raise ValueError


def _supported_node_runtime(value: str) -> bool:
    match = _NODE_RUNTIME.fullmatch(value)
    if match is None:
        return False
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch) >= (22, 8, 0) and major < 23


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _DeterministicClock:
    deterministic: bool = True

    def now_ms(self) -> int:
        return 0


@dataclass(frozen=True)
class _CredentialFreeFixtureStore:
    model_credential_reads: int = 0


@dataclass(frozen=True)
class _DeterministicFaultInjector:
    deterministic: bool = True

    def inject(self, fault_id: str) -> None:
        del fault_id
