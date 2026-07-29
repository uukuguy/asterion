"""Reference validation for portable capability-package manifests."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.protocol import CAPABILITY_ID, SEMANTIC_VERSION
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


CAPABILITY_PACKAGE_PROTOCOL_VERSION = "asterion.capability-package/v1"
BENCHMARK_SUITE_PROTOCOL_VERSION = "asterion.benchmark-suite/v1"
CAPABILITY_SOURCE_PROTOCOL_VERSION = "asterion.capability-source/v1"
CAPABILITY_LOCK_PROTOCOL_VERSION = "asterion.capability-lock/v1"
SOURCE_KINDS = frozenset(
    {"archive", "builtin", "local-directory", "python-distribution"}
)
REQUIRED_FIELDS = {
    "protocol",
    "package_id",
    "version",
    "capabilities",
    "benchmark_suites",
    "resources",
    "conformance",
}
MEDIA_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CONTRACT_ID = re.compile(
    r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*/v(?:0|[1-9][0-9]*)$"
)
BENCHMARK_SUITE_FIELDS = {
    "protocol",
    "suite_id",
    "version",
    "owner_package",
    "tasks",
    "artifact_media_types",
    "default_case_limit",
    "default_concurrency",
}
BENCHMARK_TASK_FIELDS = {
    "task_id",
    "capability",
    "binding_id",
    "metric_contract_id",
    "result_contract_id",
    "note",
}
SOURCE_FIELDS = {
    "protocol",
    "source_id",
    "kind",
    "package_ref",
    "payload_sha256",
}
LOCK_FIELDS = {"protocol", "entries"}
LOCK_ENTRY_FIELDS = {"package_ref", "payload_sha256", "source_id"}


class CapabilityPackageProtocolError(ValueError):
    """Raised when a capability package violates its portable protocol."""


class BenchmarkSuiteProtocolError(ValueError):
    """Raised when a benchmark suite violates its portable protocol."""


class CapabilitySourceProtocolError(ValueError):
    """Raised when a capability source or lock violates its operator protocol."""


@dataclass(frozen=True, order=True, slots=True)
class CapabilityPackageRef:
    package_id: str
    version: str


@dataclass(frozen=True, order=True, slots=True)
class BenchmarkSuiteRef:
    suite_id: str
    version: str


@dataclass(frozen=True, order=True, slots=True)
class ResourceIdentity:
    resource_id: str
    media_type: str
    sha256: str


@dataclass(frozen=True, slots=True)
class CapabilityPackageManifest:
    package_ref: CapabilityPackageRef
    capabilities: tuple[CapabilityRef, ...]
    benchmark_suites: tuple[BenchmarkSuiteRef, ...]
    resources: tuple[ResourceIdentity, ...]
    conformance: tuple[ResourceIdentity, ...]


@dataclass(frozen=True, slots=True)
class BenchmarkTaskManifest:
    task_id: str
    capability: CapabilityRef
    binding_id: str
    metric_contract_id: str
    result_contract_id: str
    note: str


@dataclass(frozen=True, slots=True)
class BenchmarkSuiteManifest:
    suite_ref: BenchmarkSuiteRef
    owner_package: CapabilityPackageRef
    tasks: tuple[BenchmarkTaskManifest, ...]
    artifact_media_types: tuple[str, ...]
    default_case_limit: int
    default_concurrency: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(
            self,
            "artifact_media_types",
            tuple(self.artifact_media_types),
        )


@dataclass(frozen=True, slots=True)
class CapabilitySourceDeclaration:
    source_id: str
    kind: str
    package_ref: CapabilityPackageRef
    payload_sha256: str | None
    private_locator: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_source_value(self)
        object.__setattr__(self, "private_locator", _freeze(self.private_locator))

    @property
    def public_projection(self) -> Mapping[str, object]:
        """Return the complete body-free public identity of this source."""

        return MappingProxyType(
            {
                "source_id": self.source_id,
                "kind": self.kind,
                "package_ref": MappingProxyType(
                    {
                        "package_id": self.package_ref.package_id,
                        "version": self.package_ref.version,
                    }
                ),
                "payload_sha256": self.payload_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class CapabilitySourceLockEntry:
    package_ref: CapabilityPackageRef
    payload_sha256: str
    source_id: str


@dataclass(frozen=True, slots=True)
class CapabilitySourceLock:
    entries: tuple[CapabilitySourceLockEntry, ...]

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if (
            not all(isinstance(entry, CapabilitySourceLockEntry) for entry in entries)
            or entries != tuple(sorted(entries, key=_lock_entry_key))
            or len({entry.package_ref for entry in entries}) != len(entries)
        ):
            raise CapabilitySourceProtocolError(
                "capability source lock entries are not sorted and unique"
            )
        object.__setattr__(self, "entries", entries)


def validate_capability_package_manifest(value: object) -> CapabilityPackageManifest:
    """Validate one closed, portable capability-package manifest."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CapabilityPackageProtocolError("capability package must be an object")
    if value.keys() != REQUIRED_FIELDS:
        raise CapabilityPackageProtocolError("capability package fields are not recognized")
    if value["protocol"] != CAPABILITY_PACKAGE_PROTOCOL_VERSION:
        raise CapabilityPackageProtocolError("capability package protocol is invalid")
    package_ref = CapabilityPackageRef(
        _identity(value["package_id"], "package identifier"),
        _version(value["version"], "package version"),
    )
    capabilities = _capability_refs(value["capabilities"])
    benchmark_suites = _benchmark_suite_refs(value["benchmark_suites"])
    resources = _resource_identities(value["resources"])
    conformance = _resource_identities(value["conformance"])
    return CapabilityPackageManifest(
        package_ref=package_ref,
        capabilities=capabilities,
        benchmark_suites=benchmark_suites,
        resources=resources,
        conformance=conformance,
    )


def validate_benchmark_suite_manifest(value: object) -> BenchmarkSuiteManifest:
    """Validate one closed, declarative benchmark-suite manifest."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise BenchmarkSuiteProtocolError("benchmark suite must be an object")
    if value.keys() != BENCHMARK_SUITE_FIELDS:
        raise BenchmarkSuiteProtocolError("benchmark suite fields are not recognized")
    if value["protocol"] != BENCHMARK_SUITE_PROTOCOL_VERSION:
        raise BenchmarkSuiteProtocolError("benchmark suite protocol is invalid")
    suite_ref = BenchmarkSuiteRef(
        _benchmark_identity(value["suite_id"], "suite identifier"),
        _benchmark_version(value["version"], "suite version"),
    )
    owner_package = _benchmark_package_ref(value["owner_package"])
    tasks = _benchmark_tasks(value["tasks"])
    artifact_media_types = _benchmark_media_types(value["artifact_media_types"])
    case_limit = _bounded_integer(
        value["default_case_limit"],
        "benchmark suite default case limit",
        maximum=1_000_000,
    )
    concurrency = _bounded_integer(
        value["default_concurrency"],
        "benchmark suite default concurrency",
        maximum=256,
    )
    return BenchmarkSuiteManifest(
        suite_ref=suite_ref,
        owner_package=owner_package,
        tasks=tasks,
        artifact_media_types=artifact_media_types,
        default_case_limit=case_limit,
        default_concurrency=concurrency,
    )


def validate_capability_source_declaration(
    value: object,
    *,
    private_locator: object = None,
) -> CapabilitySourceDeclaration:
    """Validate one closed source declaration and attach private operator state."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CapabilitySourceProtocolError("capability source must be an object")
    if value.keys() != SOURCE_FIELDS:
        raise CapabilitySourceProtocolError("capability source fields are not recognized")
    if value["protocol"] != CAPABILITY_SOURCE_PROTOCOL_VERSION:
        raise CapabilitySourceProtocolError("capability source protocol is invalid")
    package_ref = _source_package_ref(value["package_ref"])
    payload_sha256 = value["payload_sha256"]
    if payload_sha256 is not None:
        payload_sha256 = _source_sha256(payload_sha256)
    return CapabilitySourceDeclaration(
        source_id=_source_identity(value["source_id"], "source identifier"),
        kind=_source_kind(value["kind"]),
        package_ref=package_ref,
        payload_sha256=payload_sha256,
        private_locator=private_locator,
    )


def validate_capability_source_lock(value: object) -> CapabilitySourceLock:
    """Validate one closed exact source-lock document."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CapabilitySourceProtocolError("capability source lock must be an object")
    if value.keys() != LOCK_FIELDS:
        raise CapabilitySourceProtocolError(
            "capability source lock fields are not recognized"
        )
    if value["protocol"] != CAPABILITY_LOCK_PROTOCOL_VERSION:
        raise CapabilitySourceProtocolError("capability source lock protocol is invalid")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list):
        raise CapabilitySourceProtocolError("capability source lock entries are invalid")
    entries = tuple(_source_lock_entry(entry) for entry in raw_entries)
    return CapabilitySourceLock(entries=entries)


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str) or CAPABILITY_ID.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(f"{label} is invalid")
    return value


def _benchmark_identity(value: object, label: str) -> str:
    try:
        return _identity(value, label)
    except CapabilityPackageProtocolError as error:
        raise BenchmarkSuiteProtocolError(f"{label} is invalid") from error


def _source_identity(value: object, label: str) -> str:
    try:
        return _identity(value, label)
    except CapabilityPackageProtocolError as error:
        raise CapabilitySourceProtocolError(f"{label} is invalid") from error


def _version(value: object, label: str) -> str:
    if not isinstance(value, str) or SEMANTIC_VERSION.fullmatch(value) is None:
        raise CapabilityPackageProtocolError(f"{label} is invalid")
    return value


def _benchmark_version(value: object, label: str) -> str:
    try:
        return _version(value, label)
    except CapabilityPackageProtocolError as error:
        raise BenchmarkSuiteProtocolError(f"{label} is invalid") from error


def _source_version(value: object, label: str) -> str:
    try:
        return _version(value, label)
    except CapabilityPackageProtocolError as error:
        raise CapabilitySourceProtocolError(f"{label} is invalid") from error


def _capability_refs(value: object) -> tuple[CapabilityRef, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError("capability package capabilities are invalid")
    refs = tuple(
        CapabilityRef(
            _identity(
                _mapping_field(item, {"capability_id", "version"}, "capability_id"),
                "capability identifier",
            ),
            _version(
                _mapping_field(item, {"capability_id", "version"}, "version"),
                "capability version",
            ),
        )
        for item in value
    )
    if refs != tuple(sorted(refs)) or len(refs) != len(set(refs)):
        raise CapabilityPackageProtocolError(
            "capability package capabilities are not sorted and unique"
        )
    return refs


def _benchmark_suite_refs(value: object) -> tuple[BenchmarkSuiteRef, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError("capability package benchmark suites are invalid")
    refs = tuple(
        BenchmarkSuiteRef(
            _identity(
                _mapping_field(item, {"suite_id", "version"}, "suite_id"),
                "suite identifier",
            ),
            _version(
                _mapping_field(item, {"suite_id", "version"}, "version"),
                "suite version",
            ),
        )
        for item in value
    )
    if refs != tuple(sorted(refs)) or len(refs) != len(set(refs)):
        raise CapabilityPackageProtocolError(
            "capability package benchmark suites are not sorted and unique"
        )
    return refs


def _resource_identities(value: object) -> tuple[ResourceIdentity, ...]:
    if not isinstance(value, list):
        raise CapabilityPackageProtocolError("capability package resources are invalid")
    resources = tuple(
        ResourceIdentity(
            _identity(
                _mapping_field(
                    item,
                    {"resource_id", "media_type", "sha256"},
                    "resource_id",
                ),
                "resource identifier",
            ),
            _media_type(
                _mapping_field(
                    item,
                    {"resource_id", "media_type", "sha256"},
                    "media_type",
                )
            ),
            _sha256(
                _mapping_field(
                    item,
                    {"resource_id", "media_type", "sha256"},
                    "sha256",
                )
            ),
        )
        for item in value
    )
    if (
        resources != tuple(sorted(resources))
        or len(resources) != len({resource.resource_id for resource in resources})
    ):
        raise CapabilityPackageProtocolError(
            "capability package resources are not sorted and unique"
        )
    return resources


def _mapping_field(value: object, fields: set[str], name: str) -> object:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CapabilityPackageProtocolError("capability package member is invalid")
    return value[name]


def _media_type(value: object) -> str:
    if not isinstance(value, str) or MEDIA_TYPE.fullmatch(value) is None:
        raise CapabilityPackageProtocolError("resource media type is invalid")
    return value


def _sha256(value: object) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CapabilityPackageProtocolError("resource digest is invalid")
    return value


def _benchmark_package_ref(value: object) -> CapabilityPackageRef:
    return CapabilityPackageRef(
        _benchmark_identity(
            _benchmark_mapping_field(
                value,
                {"package_id", "version"},
                "package_id",
            ),
            "package identifier",
        ),
        _benchmark_version(
            _benchmark_mapping_field(value, {"package_id", "version"}, "version"),
            "package version",
        ),
    )


def _benchmark_tasks(value: object) -> tuple[BenchmarkTaskManifest, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkSuiteProtocolError("benchmark suite tasks are invalid")
    tasks = tuple(_benchmark_task(task) for task in value)
    task_ids = [task.task_id for task in tasks]
    if not is_sorted_unique_scalar_strings(task_ids):
        raise BenchmarkSuiteProtocolError(
            "benchmark suite tasks are not sorted and unique"
        )
    return tasks


def _benchmark_task(value: object) -> BenchmarkTaskManifest:
    if not isinstance(value, Mapping) or set(value) != BENCHMARK_TASK_FIELDS:
        raise BenchmarkSuiteProtocolError("benchmark suite task is invalid")
    capability = value["capability"]
    return BenchmarkTaskManifest(
        task_id=_benchmark_identity(value["task_id"], "task identifier"),
        capability=CapabilityRef(
            _benchmark_identity(
                _benchmark_mapping_field(
                    capability,
                    {"capability_id", "version"},
                    "capability_id",
                ),
                "capability identifier",
            ),
            _benchmark_version(
                _benchmark_mapping_field(
                    capability,
                    {"capability_id", "version"},
                    "version",
                ),
                "capability version",
            ),
        ),
        binding_id=_benchmark_identity(value["binding_id"], "binding identifier"),
        metric_contract_id=_contract_id(
            value["metric_contract_id"],
            "benchmark metric contract",
        ),
        result_contract_id=_contract_id(
            value["result_contract_id"],
            "benchmark result contract",
        ),
        note=_benchmark_note(value["note"]),
    )


def _benchmark_mapping_field(
    value: object,
    fields: set[str],
    name: str,
) -> object:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise BenchmarkSuiteProtocolError("benchmark suite member is invalid")
    return value[name]


def _contract_id(value: object, label: str) -> str:
    if not isinstance(value, str) or CONTRACT_ID.fullmatch(value) is None:
        raise BenchmarkSuiteProtocolError(f"{label} is invalid")
    return value


def _benchmark_note(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 512
        or "\n" in value
        or "\r" in value
    ):
        raise BenchmarkSuiteProtocolError("benchmark task note is invalid")
    return value


def _benchmark_media_types(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite artifact media types are invalid"
        )
    try:
        media_types = tuple(_media_type(item) for item in value)
    except CapabilityPackageProtocolError as error:
        raise BenchmarkSuiteProtocolError(
            "benchmark suite artifact media types are invalid"
        ) from error
    if not is_sorted_unique_scalar_strings(list(media_types)):
        raise BenchmarkSuiteProtocolError(
            "benchmark suite artifact media types are not sorted and unique"
        )
    return media_types


def _bounded_integer(value: object, label: str, *, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > maximum
    ):
        raise BenchmarkSuiteProtocolError(f"{label} is invalid")
    return value


def _source_package_ref(value: object) -> CapabilityPackageRef:
    return CapabilityPackageRef(
        _source_identity(
            _source_mapping_field(value, {"package_id", "version"}, "package_id"),
            "package identifier",
        ),
        _source_version(
            _source_mapping_field(value, {"package_id", "version"}, "version"),
            "package version",
        ),
    )


def _source_mapping_field(value: object, fields: set[str], name: str) -> object:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CapabilitySourceProtocolError("capability source member is invalid")
    return value[name]


def _source_kind(value: object) -> str:
    if not isinstance(value, str) or value not in SOURCE_KINDS:
        raise CapabilitySourceProtocolError("capability source kind is invalid")
    return value


def _source_sha256(value: object) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CapabilitySourceProtocolError("capability source digest is invalid")
    return value


def _validate_source_value(source: CapabilitySourceDeclaration) -> None:
    _source_identity(source.source_id, "source identifier")
    _source_kind(source.kind)
    _source_identity(source.package_ref.package_id, "package identifier")
    _source_version(source.package_ref.version, "package version")
    if source.payload_sha256 is not None:
        _source_sha256(source.payload_sha256)


def _source_lock_entry(value: object) -> CapabilitySourceLockEntry:
    return CapabilitySourceLockEntry(
        package_ref=_source_package_ref(
            _source_mapping_field(value, LOCK_ENTRY_FIELDS, "package_ref")
        ),
        payload_sha256=_source_sha256(
            _source_mapping_field(value, LOCK_ENTRY_FIELDS, "payload_sha256")
        ),
        source_id=_source_identity(
            _source_mapping_field(value, LOCK_ENTRY_FIELDS, "source_id"),
            "source identifier",
        ),
    )


def _lock_entry_key(
    entry: CapabilitySourceLockEntry,
) -> tuple[CapabilityPackageRef, str, str]:
    return (entry.package_ref, entry.payload_sha256, entry.source_id)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value
