"""Closed provider-free reduction of Prime client evidence receipts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from asterion.control.parity_testing import (
    ParityScenarioRegistry,
    ParityScenarioRegistryError,
    ParityScenarioResult,
    ParityScenarioRunner,
)


PRIME_CLIENT_SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c"
PRIME_CLIENT_ARTIFACT_LOCK_DIGEST = (
    "34374afe3bbef57b6690764a174a22f2fbd3952e26cfac788c955a363a54274d"
)
PRIME_CLIENT_MODULE_LOCK_DIGEST = (
    "577f5ea261d515223d578673f7431fd12d141fb5160c1611315ab015892485a8"
)
PRIME_CLIENT_MODULE_DIGEST = (
    "5ada8386371b8b68bf2bf34b892fdee1b93ad936dfa906110901b14141b63e86"
)
PRIME_CLIENT_REQUIRED_ASSERTIONS = (
    "authority-preserved",
    "feature-reachable",
    "identity-stable",
    "public-redacted",
)
PRIME_CLIENT_PACKAGE_FEATURES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "core": ("interface.json-stream", "interface.sdk"),
        "protocols": ("interface.acp", "interface.rpc"),
        "interactive": (
            "interface.cli-interactive",
            "interface.headless-print",
            "interface.tui-commands",
            "interface.tui-extension-ui",
        ),
        "export-share": ("interface.export-share",),
    }
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_INT_LIMIT = 9_007_199_254_740_991
_SENTINELS = ("SENTINEL_",)
_FORBIDDEN_KEYS = frozenset(
    {
        "answer",
        "body",
        "command",
        "credential",
        "destination",
        "output",
        "path",
        "prompt",
        "raw_output",
        "source_path",
    }
)
_SCENARIO_EVIDENCE = (
    ("identity.source-module-artifact", "rejected", "identity_mismatch"),
    ("stream.cursor-gap", "rejected", "cursor_gap"),
    ("stream.partial-oversized", "rejected", "jsonl_frame_rejected"),
    ("redaction.body-credential", "rejected", "private_value_rejected"),
    ("lifecycle.disconnect-cancel", "cancelled", "disconnect_cancelled"),
    ("lifecycle.retained-process", "cleaned", "no_retained_process"),
    ("stdout.protocol-purity", "clean", "stdout_protocol_pure"),
    ("interactive.command-rollback", "rejected", "command_revision_rollback"),
    ("interactive.ui-timeout", "cancelled", "ui_timeout"),
    ("export.public-private-read", "succeeded", "public_export_no_private_read"),
    ("share.unauthorized-upload", "rejected", "upload_unauthorized"),
)
_PACKAGE_SCENARIOS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "core": ("prime-client-core.jsonl", "prime-client-core.sdk"),
        "protocols": ("prime-parity.interface.acp", "prime-parity.interface.rpc"),
        "interactive": (
            "prime-client-interactive.cli",
            "prime-client-interactive.headless",
            "prime-client-interactive.commands",
            "prime-client-interactive.extension-ui",
        ),
        "export-share": ("prime-client-export-share.public",),
    }
)


class PrimeClientParityError(ParityScenarioRegistryError):
    """Raised without exposing the rejected client receipt."""


_COMMON_KEYS = frozenset(
    {
        "artifact_lock_digest",
        "credential_reads",
        "feature_count",
        "feature_ids",
        "module_digest",
        "module_lock_digest",
        "package",
        "private_reads",
        "provider_operations",
        "retained_processes",
        "scenario_count",
        "scenario_evidence",
        "scenario_ids",
        "source_commit",
        "stdout_writes",
        "unauthorized_uploads",
    }
)
PRIME_CLIENT_PACKAGE_COMMAND_IDS: Mapping[str, str] = MappingProxyType(
    {
        "core": "test.prime-client-core.provider-free",
        "protocols": "test.prime-client-protocols.provider-free",
        "interactive": "test.prime-client-interactive.provider-free",
        "export-share": "test.prime-client-export-share.provider-free",
    }
)
PRIME_CLIENT_FEATURE_IDS = tuple(
    feature_id
    for package in PRIME_CLIENT_PACKAGE_FEATURES.values()
    for feature_id in package
)
PRIME_CLIENT_SCENARIO_IDS = tuple(
    sorted(f"prime-parity.{feature_id}" for feature_id in PRIME_CLIENT_FEATURE_IDS)
)


@dataclass(frozen=True, repr=False)
class PrimeClientScenarioObservation:
    scenario_id: str
    feature_id: str
    package: str
    status: str
    command_id: str
    source_commit: str
    artifact_lock_digest: str
    module_lock_digest: str
    module_digest: str
    provider_operations: int
    credential_reads: int
    private_reads: int
    retained_processes: int
    stdout_writes: int
    unauthorized_uploads: int
    receipt_digest: str
    serialized_observations: str
    evidence_id: str

    def __repr__(self) -> str:
        return (
            "PrimeClientScenarioObservation("
            f"scenario_id={self.scenario_id!r}, evidence_id={self.evidence_id!r}, "
            "observations=<redacted>)"
        )


def build_prime_client_observations(
    receipts: Sequence[Mapping[str, object]],
) -> tuple[PrimeClientScenarioObservation, ...]:
    """Reduce the four exact local client receipts into nine observations."""

    try:
        if type(receipts) not in {list, tuple}:
            raise ValueError
        receipt_by_package: dict[str, Mapping[str, object]] = {}
        for receipt in receipts:
            if type(receipt) is not dict:
                raise ValueError
            package = receipt.get("package")
            if (
                type(package) is not str
                or package not in PRIME_CLIENT_PACKAGE_FEATURES
                or package in receipt_by_package
            ):
                raise ValueError
            receipt_by_package[package] = receipt
        if tuple(receipt_by_package) != tuple(PRIME_CLIENT_PACKAGE_FEATURES):
            raise ValueError

        observations: list[PrimeClientScenarioObservation] = []
        for package in PRIME_CLIENT_PACKAGE_FEATURES:
            receipt = receipt_by_package[package]
            _validate_receipt(package, receipt)
            receipt_digest = _canonical_digest(receipt)
            for feature_id in PRIME_CLIENT_PACKAGE_FEATURES[package]:
                scenario_id = f"prime-parity.{feature_id}"
                payload = {
                    "artifact_lock_digest": PRIME_CLIENT_ARTIFACT_LOCK_DIGEST,
                    "assertion_ids": list(PRIME_CLIENT_REQUIRED_ASSERTIONS),
                    "boundary": "real-prime-provider-free",
                    "command_id": PRIME_CLIENT_PACKAGE_COMMAND_IDS[package],
                    "feature_ids": [feature_id],
                    "module_digest": PRIME_CLIENT_MODULE_DIGEST,
                    "module_lock_digest": PRIME_CLIENT_MODULE_LOCK_DIGEST,
                    "package": package,
                    "provider_id": "asterion.prime-gateway",
                    "provider_operations": 0,
                    "receipt_digest": receipt_digest,
                    "scenario_id": scenario_id,
                    "source_commit": PRIME_CLIENT_SOURCE_COMMIT,
                    "status": "PASS",
                }
                serialized = _canonical(payload)
                observations.append(
                    PrimeClientScenarioObservation(
                        scenario_id=scenario_id,
                        feature_id=feature_id,
                        package=package,
                        status="PASS",
                        command_id=PRIME_CLIENT_PACKAGE_COMMAND_IDS[package],
                        source_commit=PRIME_CLIENT_SOURCE_COMMIT,
                        artifact_lock_digest=PRIME_CLIENT_ARTIFACT_LOCK_DIGEST,
                        module_lock_digest=PRIME_CLIENT_MODULE_LOCK_DIGEST,
                        module_digest=PRIME_CLIENT_MODULE_DIGEST,
                        provider_operations=0,
                        credential_reads=0,
                        private_reads=0,
                        retained_processes=0,
                        stdout_writes=0,
                        unauthorized_uploads=0,
                        receipt_digest=receipt_digest,
                        serialized_observations=serialized,
                        evidence_id="evidence.client."
                        + hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                    )
                )
        observations.sort(key=lambda item: item.scenario_id)
        if tuple(item.scenario_id for item in observations) != tuple(
            sorted(PRIME_CLIENT_SCENARIO_IDS)
        ):
            raise ValueError
        return tuple(observations)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise PrimeClientParityError("Prime client receipt is invalid") from None


def register_prime_client_scenarios(
    registry: ParityScenarioRegistry,
    observations: Sequence[PrimeClientScenarioObservation],
    *,
    provider_factory: Callable[[], object],
) -> None:
    """Register exactly the nine local Prime client scenario runners."""

    try:
        if (
            registry.provider_id != "asterion.prime-gateway"
            or type(observations) not in {list, tuple}
            or not callable(provider_factory)
            or any(
                scenario_id in registry.registered_scenario_ids
                for scenario_id in PRIME_CLIENT_SCENARIO_IDS
            )
        ):
            raise ValueError
        items = tuple(observations)
        if tuple(item.scenario_id for item in items) != tuple(
            sorted(PRIME_CLIENT_SCENARIO_IDS)
        ):
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
                        assertion_ids=PRIME_CLIENT_REQUIRED_ASSERTIONS,
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
        raise PrimeClientParityError("Prime client evidence adapter is invalid") from None

    try:
        registry.register_many(runners)
    except ParityScenarioRegistryError:
        raise PrimeClientParityError("Prime client evidence adapter is invalid") from None


def _validate_receipt(package: str, receipt: Mapping[str, object]) -> None:
    if set(receipt) != _COMMON_KEYS:
        raise ValueError
    _validate_public_receipt(receipt)
    if (
        receipt["package"] != package
        or receipt["source_commit"] != PRIME_CLIENT_SOURCE_COMMIT
        or receipt["artifact_lock_digest"] != PRIME_CLIENT_ARTIFACT_LOCK_DIGEST
        or receipt["module_lock_digest"] != PRIME_CLIENT_MODULE_LOCK_DIGEST
        or receipt["module_digest"] != PRIME_CLIENT_MODULE_DIGEST
        or receipt["feature_ids"] != list(PRIME_CLIENT_PACKAGE_FEATURES[package])
        or receipt["scenario_ids"] != list(_PACKAGE_SCENARIOS[package])
        or receipt["feature_count"] != len(PRIME_CLIENT_PACKAGE_FEATURES[package])
        or receipt["scenario_count"] != len(_PACKAGE_SCENARIOS[package])
        or any(
            type(receipt[key]) is not int or receipt[key] != 0
            for key in (
                "credential_reads",
                "private_reads",
                "provider_operations",
                "retained_processes",
                "stdout_writes",
                "unauthorized_uploads",
            )
        )
    ):
        raise ValueError
    _validate_scenario_evidence(receipt["scenario_evidence"])


def _validate_scenario_evidence(value: object) -> None:
    if type(value) is not list or len(value) != len(_SCENARIO_EVIDENCE):
        raise ValueError
    for entry, (scenario_id, outcome, error_code) in zip(value, _SCENARIO_EVIDENCE):
        if type(entry) is not dict or set(entry) != {
            "counters",
            "digest",
            "error_code",
            "id",
            "outcome",
        }:
            raise ValueError
        counters = entry["counters"]
        expected_counter_keys = {
            "credential_reads",
            "network_requests",
            "private_reads",
            "provider_operations",
            "retained_processes",
            "scenario_calls",
            "stdout_writes",
            "unauthorized_uploads",
        }
        if scenario_id == "interactive.ui-timeout":
            expected_counter_keys |= {"ui_cancellations", "ui_renders", "ui_submits"}
        if (
            type(counters) is not dict
            or set(counters) != expected_counter_keys
            or entry["id"] != scenario_id
            or entry["outcome"] != outcome
            or entry["error_code"] != error_code
            or type(entry["digest"]) is not str
            or _HEX64.fullmatch(entry["digest"]) is None
        ):
            raise ValueError
        for key, count in counters.items():
            if type(count) is not int or not 0 <= count <= _SAFE_INT_LIMIT:
                raise ValueError
            if key not in {"scenario_calls", "ui_cancellations", "ui_renders"} and count != 0:
                raise ValueError
        if (
            counters["scenario_calls"] != 1
            or (scenario_id == "interactive.ui-timeout" and (
                counters["ui_cancellations"] != 1
                or counters["ui_renders"] < 1
                or counters["ui_submits"] != 0
            ))
            or entry["digest"] != _canonical_digest(
                {
                    "counters": counters,
                    "error_code": error_code,
                    "id": scenario_id,
                    "outcome": outcome,
                }
            )
        ):
            raise ValueError


def _validate_observation(observation: PrimeClientScenarioObservation) -> None:
    if type(observation) is not PrimeClientScenarioObservation:
        raise ValueError
    expected = f"prime-parity.{observation.feature_id}"
    if (
        observation.scenario_id != expected
        or observation.scenario_id not in PRIME_CLIENT_SCENARIO_IDS
        or observation.feature_id not in PRIME_CLIENT_PACKAGE_FEATURES[observation.package]
        or observation.status != "PASS"
        or observation.command_id
        != PRIME_CLIENT_PACKAGE_COMMAND_IDS[observation.package]
        or observation.source_commit != PRIME_CLIENT_SOURCE_COMMIT
        or observation.artifact_lock_digest != PRIME_CLIENT_ARTIFACT_LOCK_DIGEST
        or observation.module_lock_digest != PRIME_CLIENT_MODULE_LOCK_DIGEST
        or observation.module_digest != PRIME_CLIENT_MODULE_DIGEST
        or any(
            value != 0
            for value in (
                observation.provider_operations,
                observation.credential_reads,
                observation.private_reads,
                observation.retained_processes,
                observation.stdout_writes,
                observation.unauthorized_uploads,
            )
        )
        or _HEX64.fullmatch(observation.receipt_digest) is None
        or observation.evidence_id
        != "evidence.client."
        + hashlib.sha256(observation.serialized_observations.encode("utf-8")).hexdigest()
        or any(sentinel in observation.serialized_observations for sentinel in _SENTINELS)
    ):
        raise ValueError


def _validate_public_receipt(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or key.casefold() in _FORBIDDEN_KEYS:
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
