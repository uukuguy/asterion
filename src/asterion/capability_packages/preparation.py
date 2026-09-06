"""Host-owned preparation and loading for exact capability-package sources."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from asterion.capabilities.protocol import CAPABILITY_ID, SEMANTIC_VERSION
from asterion.capability_packages.model import (
    bind_prepared_package_authority,
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)
from asterion.capability_packages.resolution import resolve_capability_source
from asterion.capability_packages.sources.base import CapabilityPackageSource


class CapabilitySourcePreparationError(ValueError):
    """Raised when host-owned source preparation or loading fails closed."""


@dataclass(frozen=True, slots=True)
class PreparedCapabilityPackage:
    """A frozen process-local handle for one prepared payload and source."""

    candidate: CapabilityPackageCandidate
    payload: PortableCapabilityPayload
    _candidate: object = field(repr=False, compare=False)
    _source: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.candidate) is not CapabilityPackageCandidate
            or type(self.payload) is not PortableCapabilityPayload
            or type(self._candidate) is not CapabilityPackageCandidate
            or self.candidate.package_ref != self.payload.manifest.package_ref
            or self.candidate.payload_sha256 != self.payload.payload_sha256
            or self._candidate.package_ref != self.candidate.package_ref
            or self._candidate.source_id != self.candidate.source_id
            or self._candidate.source_kind != self.candidate.source_kind
            or self._candidate.metadata != self.candidate.metadata
            or self._candidate.payload_sha256
            not in {
                None,
                self.candidate.payload_sha256,
            }
        ):
            raise CapabilitySourcePreparationError(
                "capability source preparation failed"
            )
        _validate_source(self._source)


def prepare_capability_source(
    package_ref: CapabilityPackageRef,
    sources: Sequence[CapabilityPackageSource],
    lock: CapabilitySourceLock | None,
) -> PreparedCapabilityPackage:
    """Discover, select, validate, and snapshot one source without loading it."""

    failed = False
    prepared: PreparedCapabilityPackage | None = None
    try:
        source_values = _validate_request(package_ref, sources, lock)
        records = _discovered_records(package_ref, source_values)
        source, original, candidate = _select_record(package_ref, records, lock)
        payload = source.open_payload(original)
        _validate_payload(candidate, payload)
        source.validate_source_identity(original, payload)
        normalized = CapabilityPackageCandidate(
            package_ref=candidate.package_ref,
            source_id=candidate.source_id,
            source_kind=candidate.source_kind,
            payload_sha256=payload.payload_sha256,
            metadata=candidate.metadata,
        )
        resolve_capability_source(package_ref, (normalized,), lock)
        prepared = PreparedCapabilityPackage(normalized, payload, original, source)
    except Exception:
        failed = True
    if failed or prepared is None:
        raise CapabilitySourcePreparationError("capability source preparation failed")
    return prepared


def load_prepared_capability_source(
    prepared: PreparedCapabilityPackage,
) -> InstalledCapabilityPackage:
    """Revalidate and load exactly the source selected during preparation."""

    failed = False
    installed: InstalledCapabilityPackage | None = None
    try:
        if type(prepared) is not PreparedCapabilityPackage:
            _fail()
        source = prepared._source
        original = prepared._candidate
        _validate_source(source)
        if type(original) is not CapabilityPackageCandidate:
            _fail()
        payload = source.open_payload(original)
        _validate_payload(prepared.candidate, payload)
        source.validate_source_identity(original, payload)
        if payload.payload_sha256 != prepared.payload.payload_sha256:
            _fail()
        installed = source.load_provider(original)
        if (
            type(installed) is not InstalledCapabilityPackage
            or installed.package_ref != prepared.candidate.package_ref
            or installed.source_id != prepared.candidate.source_id
            or installed.source_kind != prepared.candidate.source_kind
            or installed.payload_sha256 != prepared.candidate.payload_sha256
        ):
            _fail()
    except Exception:
        failed = True
    if failed or installed is None:
        raise CapabilitySourcePreparationError("capability source preparation failed")
    try:
        return bind_prepared_package_authority(installed, prepared.payload)
    except Exception:
        raise CapabilitySourcePreparationError(
            "capability source preparation failed"
        ) from None


def _discovered_records(
    package_ref: CapabilityPackageRef,
    sources: Sequence[CapabilityPackageSource],
) -> tuple[
    tuple[
        CapabilityPackageSource, CapabilityPackageCandidate, CapabilityPackageCandidate
    ],
    ...,
]:
    records: list[
        tuple[
            CapabilityPackageSource,
            CapabilityPackageCandidate,
            CapabilityPackageCandidate,
        ]
    ] = []
    for source in sources:
        for candidate in source.discover_metadata():
            if type(candidate) is not CapabilityPackageCandidate:
                _fail()
            snapshot = CapabilityPackageCandidate(
                package_ref=candidate.package_ref,
                source_id=candidate.source_id,
                source_kind=candidate.source_kind,
                payload_sha256=candidate.payload_sha256,
                metadata=candidate.metadata,
            )
            if snapshot.package_ref == package_ref:
                records.append((source, candidate, snapshot))
    return tuple(records)


def _select_record(
    package_ref: CapabilityPackageRef,
    records: tuple[
        tuple[
            CapabilityPackageSource,
            CapabilityPackageCandidate,
            CapabilityPackageCandidate,
        ],
        ...,
    ],
    lock: CapabilitySourceLock | None,
) -> tuple[
    CapabilityPackageSource, CapabilityPackageCandidate, CapabilityPackageCandidate
]:
    selected = records
    if lock is not None:
        entries = tuple(
            entry for entry in lock.entries if entry.package_ref == package_ref
        )
        if len(entries) > 1:
            _fail()
        if entries:
            selected = tuple(
                record
                for record in records
                if record[2].source_id == entries[0].source_id
            )
    if len(selected) != 1:
        _fail()
    return selected[0]


def _validate_request(
    package_ref: object,
    sources: object,
    lock: object,
) -> tuple[CapabilityPackageSource, ...]:
    if type(package_ref) is not CapabilityPackageRef or not isinstance(
        sources, Sequence
    ):
        _fail()
    _validate_ref(package_ref)
    _validate_lock(lock)
    values = tuple(sources)
    if not values:
        _fail()
    for source in values:
        _validate_source(source)
    return values


def _validate_source(source: object) -> None:
    if not all(
        callable(getattr(source, method, None))
        for method in (
            "discover_metadata",
            "open_payload",
            "validate_source_identity",
            "load_provider",
        )
    ):
        _fail()


def _validate_payload(
    candidate: CapabilityPackageCandidate,
    payload: object,
) -> None:
    if (
        type(payload) is not PortableCapabilityPayload
        or payload.manifest.package_ref != candidate.package_ref
        or (
            candidate.payload_sha256 is not None
            and candidate.payload_sha256 != payload.payload_sha256
        )
    ):
        _fail()


def _validate_lock(lock: object) -> None:
    if lock is None:
        return
    if type(lock) is not CapabilitySourceLock:
        _fail()
    entries = tuple(lock.entries)
    if entries != tuple(
        sorted(
            entries,
            key=lambda entry: (entry.package_ref.package_id, entry.package_ref.version),
        )
    ):
        _fail()
    seen: set[CapabilityPackageRef] = set()
    for entry in entries:
        if type(entry) is not CapabilitySourceLockEntry:
            _fail()
        _validate_ref(entry.package_ref)
        if (
            not isinstance(entry.source_id, str)
            or CAPABILITY_ID.fullmatch(entry.source_id) is None
        ):
            _fail()
        if (
            not isinstance(entry.payload_sha256, str)
            or len(entry.payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in entry.payload_sha256
            )
        ):
            _fail()
        if entry.package_ref in seen:
            _fail()
        seen.add(entry.package_ref)


def _validate_ref(package_ref: object) -> None:
    if (
        type(package_ref) is not CapabilityPackageRef
        or not isinstance(package_ref.package_id, str)
        or CAPABILITY_ID.fullmatch(package_ref.package_id) is None
        or not isinstance(package_ref.version, str)
        or SEMANTIC_VERSION.fullmatch(package_ref.version) is None
    ):
        _fail()


def _fail() -> None:
    raise CapabilitySourcePreparationError("capability source preparation failed")


__all__ = (
    "CapabilitySourcePreparationError",
    "PreparedCapabilityPackage",
    "load_prepared_capability_source",
    "prepare_capability_source",
)
