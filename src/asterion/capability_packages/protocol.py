"""Portable capability-package descriptor values and validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from types import MappingProxyType
from typing import TypeVar

from asterion.capabilities.catalog import CapabilityRef


CAPABILITY_PACKAGE_PROTOCOL_VERSION = "asterion.capability-package/v1"
BENCHMARK_SUITE_PROTOCOL_VERSION = "asterion.benchmark-suite/v1"
CAPABILITY_SOURCE_PROTOCOL_VERSION = "asterion.capability-source/v1"
CAPABILITY_LOCK_PROTOCOL_VERSION = "asterion.capability-lock/v1"
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
SEMANTIC_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_FIELDS = {
    "protocol",
    "package_id",
    "version",
    "capabilities",
    "benchmark_suites",
    "resources",
}
BENCHMARK_SUITE_REQUIRED_FIELDS = {
    "protocol",
    "suite_id",
    "version",
    "owner_package",
    "tasks",
    "artifact_media_types",
    "default_case_limit",
    "default_concurrency",
}
BENCHMARK_TASK_REQUIRED_FIELDS = {
    "task_id",
    "capability",
    "binding_id",
    "metric_contract_id",
    "result_contract_id",
    "note",
}
CAPABILITY_SOURCE_REQUIRED_FIELDS = {
    "protocol",
    "source_id",
    "kind",
    "package",
    "payload_sha256",
    "locator",
    "provider_factory",
}
CAPABILITY_LOCK_REQUIRED_FIELDS = {"protocol", "entries"}
CAPABILITY_LOCK_ENTRY_REQUIRED_FIELDS = {
    "package",
    "payload_sha256",
    "source_id",
}
SOURCE_KINDS = frozenset(
    {
        "archive",
        "builtin",
        "local-directory",
        "python-distribution",
        "registry",
    }
)


class CapabilityPackageProtocolError(ValueError):
    """Raised when a descriptor violates asterion.capability-package/v1."""


class BenchmarkSuiteProtocolError(ValueError):
    """Raised when a suite violates asterion.benchmark-suite/v1."""


class CapabilitySourceProtocolError(ValueError):
    """Raised when an operator source or lock document is invalid."""


@dataclass(frozen=True, order=True, slots=True)
class CapabilityPackageRef:
    """Exact identity of one portable capability package."""

    package_id: str
    version: str

    @property
    def selector(self) -> str:
        return f"{self.package_id}@{self.version}"


@dataclass(frozen=True, order=True, slots=True)
class BenchmarkSuiteRef:
    """Exact identity of one package-owned benchmark suite."""

    suite_id: str
    version: str

    @property
    def selector(self) -> str:
        return f"{self.suite_id}@{self.version}"


@dataclass(frozen=True, order=True, slots=True)
class ResourceIdentity:
    """Content identity of one public package resource."""

    resource_id: str
    media_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CapabilityPackageManifest:
    """Immutable validated snapshot of one portable package descriptor."""

    package_ref: CapabilityPackageRef
    capabilities: tuple[CapabilityRef, ...]
    benchmark_suites: tuple[BenchmarkSuiteRef, ...]
    resources: tuple[ResourceIdentity, ...]


@dataclass(frozen=True, order=True, slots=True)
class BenchmarkTaskManifest:
    """One authority-free task declaration in a portable benchmark suite."""

    task_id: str
    capability: CapabilityRef
    binding_id: str
    metric_contract_id: str
    result_contract_id: str
    note: str


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteManifest:
    """Immutable validated snapshot of one portable benchmark suite."""

    suite_ref: BenchmarkSuiteRef
    owner_package: CapabilityPackageRef
    tasks: tuple[BenchmarkTaskManifest, ...]
    artifact_media_types: tuple[str, ...]
    default_case_limit: int
    default_concurrency: int


@dataclass(frozen=True, slots=True)
class CapabilitySourceDeclaration:
    """One operator-owned package source with an explicitly safe projection."""

    source_id: str
    kind: str
    package_ref: CapabilityPackageRef
    payload_sha256: str | None
    locator: Mapping[str, str] = dataclass_field(repr=False)
    provider_factory: Mapping[str, str] = dataclass_field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "locator",
            _private_string_mapping(self.locator),
        )
        object.__setattr__(
            self,
            "provider_factory",
            _private_string_mapping(self.provider_factory),
        )

    @property
    def public_projection(self) -> Mapping[str, object]:
        package = MappingProxyType(
            {
                "package_id": self.package_ref.package_id,
                "version": self.package_ref.version,
            }
        )
        return MappingProxyType(
            {
                "source_id": self.source_id,
                "kind": self.kind,
                "package": package,
                "payload_sha256": self.payload_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilitySourceLockEntry:
    """One exact operator selection of source and payload identity."""

    package_ref: CapabilityPackageRef
    payload_sha256: str
    source_id: str


@dataclass(frozen=True, slots=True)
class CapabilitySourceLock:
    """Immutable validated source selections in canonical order."""

    entries: tuple[CapabilitySourceLockEntry, ...]


_CanonicalValue = TypeVar(
    "_CanonicalValue",
    CapabilityRef,
    BenchmarkSuiteRef,
    ResourceIdentity,
)


def validate_capability_package_manifest(
    value: object,
) -> CapabilityPackageManifest:
    """Validate and snapshot one closed portable package descriptor."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CapabilityPackageProtocolError(
            "capability package manifest must be an object"
        )
    if value.keys() != REQUIRED_FIELDS:
        raise CapabilityPackageProtocolError(
            "capability package manifest fields are not recognized"
        )
    if value["protocol"] != CAPABILITY_PACKAGE_PROTOCOL_VERSION:
        raise CapabilityPackageProtocolError(
            "capability package protocol is invalid"
        )

    package_ref = CapabilityPackageRef(
        _identifier(value["package_id"], "package_id"),
        _version(value["version"], "package version"),
    )
    capabilities = _capability_refs(value["capabilities"])
    benchmark_suites = _benchmark_suite_refs(value["benchmark_suites"])
    resources = _resource_identities(value["resources"])
    return CapabilityPackageManifest(
        package_ref=package_ref,
        capabilities=capabilities,
        benchmark_suites=benchmark_suites,
        resources=resources,
    )


def validate_benchmark_suite_manifest(
    value: object,
) -> BenchmarkSuiteManifest:
    """Validate and snapshot one closed authority-free benchmark suite."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise BenchmarkSuiteProtocolError(
            "benchmark suite manifest must be an object"
        )
    if value.keys() != BENCHMARK_SUITE_REQUIRED_FIELDS:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite manifest fields are not recognized"
        )
    if value["protocol"] != BENCHMARK_SUITE_PROTOCOL_VERSION:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite protocol is invalid"
        )

    suite_ref = BenchmarkSuiteRef(
        _suite_identifier(value["suite_id"], "suite_id"),
        _suite_version(value["version"], "suite version"),
    )
    owner_package = _suite_package_ref(value["owner_package"])
    tasks = _benchmark_tasks(value["tasks"])
    artifact_media_types = _suite_media_types(
        value["artifact_media_types"]
    )
    default_case_limit = _bounded_positive_integer(
        value["default_case_limit"],
        "default_case_limit",
        1_000_000,
    )
    default_concurrency = _bounded_positive_integer(
        value["default_concurrency"],
        "default_concurrency",
        1_024,
    )
    return BenchmarkSuiteManifest(
        suite_ref=suite_ref,
        owner_package=owner_package,
        tasks=tasks,
        artifact_media_types=artifact_media_types,
        default_case_limit=default_case_limit,
        default_concurrency=default_concurrency,
    )


def validate_capability_source_declaration(
    value: object,
) -> CapabilitySourceDeclaration:
    """Validate and snapshot one operator-owned source declaration."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CapabilitySourceProtocolError(
            "capability source declaration must be an object"
        )
    if value.keys() != CAPABILITY_SOURCE_REQUIRED_FIELDS:
        raise CapabilitySourceProtocolError(
            "capability source declaration fields are not recognized"
        )
    if value["protocol"] != CAPABILITY_SOURCE_PROTOCOL_VERSION:
        raise CapabilitySourceProtocolError(
            "capability source protocol is invalid"
        )

    source_id = _source_identifier(value["source_id"], "source_id")
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in SOURCE_KINDS:
        raise CapabilitySourceProtocolError(
            "capability source kind is invalid"
        )
    package_ref = _source_package_ref(value["package"])
    payload_sha256 = value["payload_sha256"]
    if payload_sha256 is not None and (
        not isinstance(payload_sha256, str)
        or SHA256.fullmatch(payload_sha256) is None
    ):
        raise CapabilitySourceProtocolError(
            "capability source payload_sha256 is invalid"
        )
    locator = _private_string_mapping(value["locator"])
    provider_factory = _private_string_mapping(value["provider_factory"])
    return CapabilitySourceDeclaration(
        source_id=source_id,
        kind=kind,
        package_ref=package_ref,
        payload_sha256=payload_sha256,
        locator=locator,
        provider_factory=provider_factory,
    )


def validate_capability_source_lock(
    value: object,
) -> CapabilitySourceLock:
    """Validate and snapshot one canonical operator-owned source lock."""

    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise CapabilitySourceProtocolError(
            "capability source lock must be an object"
        )
    if value.keys() != CAPABILITY_LOCK_REQUIRED_FIELDS:
        raise CapabilitySourceProtocolError(
            "capability source lock fields are not recognized"
        )
    if value["protocol"] != CAPABILITY_LOCK_PROTOCOL_VERSION:
        raise CapabilitySourceProtocolError(
            "capability source lock protocol is invalid"
        )
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CapabilitySourceProtocolError(
            "capability source lock entries must be a non-empty array"
        )
    entries: list[CapabilitySourceLockEntry] = []
    for item in raw_entries:
        if (
            not isinstance(item, Mapping)
            or item.keys() != CAPABILITY_LOCK_ENTRY_REQUIRED_FIELDS
        ):
            raise CapabilitySourceProtocolError(
                "capability source lock entry is invalid"
            )
        payload_sha256 = item["payload_sha256"]
        if (
            not isinstance(payload_sha256, str)
            or SHA256.fullmatch(payload_sha256) is None
        ):
            raise CapabilitySourceProtocolError(
                "capability source lock payload_sha256 is invalid"
            )
        entries.append(
            CapabilitySourceLockEntry(
                package_ref=_source_package_ref(item["package"]),
                payload_sha256=payload_sha256,
                source_id=_source_identifier(
                    item["source_id"],
                    "lock source_id",
                ),
            )
        )
    snapshot = tuple(entries)
    keys = tuple(
        (
            entry.package_ref.package_id,
            entry.package_ref.version,
            entry.payload_sha256,
            entry.source_id,
        )
        for entry in snapshot
    )
    if keys != tuple(sorted(set(keys))):
        raise CapabilitySourceProtocolError(
            "capability source lock entries must be sorted and unique"
        )
    return CapabilitySourceLock(entries=snapshot)


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(
            f"capability package {label} is invalid"
        )
    return value


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(
            f"capability package {label} is invalid"
        )
    return value


def _capability_refs(value: object) -> tuple[CapabilityRef, ...]:
    if not isinstance(value, list) or not value:
        raise CapabilityPackageProtocolError(
            "capability package capabilities must be a non-empty array"
        )
    refs: list[CapabilityRef] = []
    for item in value:
        if not isinstance(item, Mapping) or item.keys() != {
            "capability_id",
            "version",
        }:
            raise CapabilityPackageProtocolError(
                "capability package capability ref is invalid"
            )
        refs.append(
            CapabilityRef(
                _identifier(item["capability_id"], "capability ref"),
                _version(item["version"], "capability ref version"),
            )
        )
    return _canonical_tuple(
        refs,
        "capability package capability refs must be sorted and unique",
    )


def _benchmark_suite_refs(value: object) -> tuple[BenchmarkSuiteRef, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError(
            "capability package benchmark_suites must be an array"
        )
    refs: list[BenchmarkSuiteRef] = []
    for item in value:
        if not isinstance(item, Mapping) or item.keys() != {
            "suite_id",
            "version",
        }:
            raise CapabilityPackageProtocolError(
                "capability package benchmark suite ref is invalid"
            )
        refs.append(
            BenchmarkSuiteRef(
                _identifier(item["suite_id"], "benchmark suite ref"),
                _version(item["version"], "benchmark suite ref version"),
            )
        )
    return _canonical_tuple(
        refs,
        "capability package benchmark suite refs must be sorted and unique",
    )


def _resource_identities(value: object) -> tuple[ResourceIdentity, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError(
            "capability package resources must be an array"
        )
    resources: list[ResourceIdentity] = []
    for item in value:
        if not isinstance(item, Mapping) or item.keys() != {
            "resource_id",
            "media_type",
            "sha256",
        }:
            raise CapabilityPackageProtocolError(
                "capability package resource identity is invalid"
            )
        media_type = item["media_type"]
        digest = item["sha256"]
        if not isinstance(media_type, str) or MEDIA_TYPE.fullmatch(media_type) is None:
            raise CapabilityPackageProtocolError(
                "capability package resource media_type is invalid"
            )
        if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
            raise CapabilityPackageProtocolError(
                "capability package resource sha256 is invalid"
            )
        resources.append(
            ResourceIdentity(
                resource_id=_identifier(item["resource_id"], "resource_id"),
                media_type=media_type,
                sha256=digest,
            )
        )
    return _canonical_tuple(
        resources,
        "capability package resources must be sorted and unique",
    )


def _suite_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise BenchmarkSuiteProtocolError(
            f"benchmark suite {label} is invalid"
        )
    return value


def _suite_version(value: object, label: str) -> str:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise BenchmarkSuiteProtocolError(
            f"benchmark suite {label} is invalid"
        )
    return value


def _suite_package_ref(value: object) -> CapabilityPackageRef:
    if not isinstance(value, Mapping) or value.keys() != {
        "package_id",
        "version",
    }:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite owner package ref is invalid"
        )
    return CapabilityPackageRef(
        _suite_identifier(value["package_id"], "owner package ref"),
        _suite_version(value["version"], "owner package ref version"),
    )


def _benchmark_tasks(
    value: object,
) -> tuple[BenchmarkTaskManifest, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite tasks must be a non-empty array"
        )
    tasks: list[BenchmarkTaskManifest] = []
    for item in value:
        if (
            not isinstance(item, Mapping)
            or item.keys() != BENCHMARK_TASK_REQUIRED_FIELDS
        ):
            raise BenchmarkSuiteProtocolError(
                "benchmark suite task is invalid"
            )
        capability = item["capability"]
        if not isinstance(capability, Mapping) or capability.keys() != {
            "capability_id",
            "version",
        }:
            raise BenchmarkSuiteProtocolError(
                "benchmark suite task capability ref is invalid"
            )
        note = item["note"]
        if (
            not isinstance(note, str)
            or len(note) > 1_024
            or _contains_surrogate(note)
        ):
            raise BenchmarkSuiteProtocolError(
                "benchmark suite task note is invalid"
            )
        tasks.append(
            BenchmarkTaskManifest(
                task_id=_suite_identifier(item["task_id"], "task_id"),
                capability=CapabilityRef(
                    _suite_identifier(
                        capability["capability_id"],
                        "task capability ref",
                    ),
                    _suite_version(
                        capability["version"],
                        "task capability ref version",
                    ),
                ),
                binding_id=_suite_identifier(
                    item["binding_id"],
                    "binding_id",
                ),
                metric_contract_id=_suite_scalar_text(
                    item["metric_contract_id"],
                    "metric_contract_id",
                ),
                result_contract_id=_suite_scalar_text(
                    item["result_contract_id"],
                    "result_contract_id",
                ),
                note=note,
            )
        )
    snapshot = tuple(tasks)
    task_ids = tuple(task.task_id for task in snapshot)
    if task_ids != tuple(sorted(set(task_ids))):
        raise BenchmarkSuiteProtocolError(
            "benchmark suite tasks must be sorted and unique"
        )
    return snapshot


def _suite_scalar_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or _contains_surrogate(value)
    ):
        raise BenchmarkSuiteProtocolError(
            f"benchmark suite {label} is invalid"
        )
    return value


def _suite_media_types(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite artifact_media_types must be a non-empty array"
        )
    media_types: list[str] = []
    for item in value:
        if not isinstance(item, str) or MEDIA_TYPE.fullmatch(item) is None:
            raise BenchmarkSuiteProtocolError(
                "benchmark suite artifact media type is invalid"
            )
        media_types.append(item)
    snapshot = tuple(media_types)
    if snapshot != tuple(sorted(set(snapshot))):
        raise BenchmarkSuiteProtocolError(
            "benchmark suite artifact_media_types must be sorted and unique"
        )
    return snapshot


def _bounded_positive_integer(
    value: object,
    label: str,
    maximum: int,
) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise BenchmarkSuiteProtocolError(
            f"benchmark suite {label} is invalid"
        )
    return value


def _source_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise CapabilitySourceProtocolError(
            f"capability source {label} is invalid"
        )
    return value


def _source_version(value: object, label: str) -> str:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise CapabilitySourceProtocolError(
            f"capability source {label} is invalid"
        )
    return value


def _source_package_ref(value: object) -> CapabilityPackageRef:
    if not isinstance(value, Mapping) or value.keys() != {
        "package_id",
        "version",
    }:
        raise CapabilitySourceProtocolError(
            "capability source package ref is invalid"
        )
    return CapabilityPackageRef(
        _source_identifier(value["package_id"], "package ref"),
        _source_version(value["version"], "package ref version"),
    )


def _private_string_mapping(value: object) -> Mapping[str, str]:
    if (
        not isinstance(value, Mapping)
        or not value
        or not all(
            isinstance(key, str)
            and key
            and isinstance(item, str)
            and item
            for key, item in value.items()
        )
    ):
        raise CapabilitySourceProtocolError(
            "capability source private configuration is invalid"
        )
    return MappingProxyType(
        dict(sorted((str(key), str(item)) for key, item in value.items()))
    )


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _canonical_tuple(
    values: list[_CanonicalValue],
    message: str,
) -> tuple[_CanonicalValue, ...]:
    snapshot = tuple(values)
    if snapshot != tuple(sorted(set(snapshot))):
        raise CapabilityPackageProtocolError(message)
    return snapshot
