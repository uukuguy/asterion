"""Installed Python distribution capability-package source adapter."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata
from os import PathLike
from pathlib import Path, PurePosixPath

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


ENTRY_POINT_GROUP = "asterion.capability_packages"
SOURCE_KIND = "python-distribution"
_PAYLOAD_ROOT_PREFIX = PurePosixPath("asterion_capability_packages")
_ERROR_MESSAGE = "installed capability distribution source is invalid"


class DistributionCapabilitySourceError(ValueError):
    """Raised when installed-distribution source handling fails closed."""


class DistributionCapabilityPackageSource:
    def __init__(
        self,
        distributions: Iterable[metadata.Distribution] | None = None,
    ) -> None:
        self._distributions = None if distributions is None else tuple(distributions)

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        failed = False
        try:
            records = self._validated_records()
            return tuple(
                CapabilityPackageCandidate(
                    package_ref=record.package_ref,
                    source_id=_source_id(record.package_ref),
                    source_kind=SOURCE_KIND,
                    payload_sha256=record.payload.payload_sha256,
                    metadata={
                        "distribution_name": _distribution_name(record.distribution),
                        "distribution_version": _distribution_version(
                            record.distribution
                        ),
                    },
                )
                for record in records
            )
        except DistributionCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        failed = False
        try:
            record = self._record_for(candidate)
            payload = record.payload
            self.validate_source_identity(candidate, payload)
            return payload
        except DistributionCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        failed = False
        try:
            if (
                type(candidate) is not CapabilityPackageCandidate
                or type(payload) is not PortableCapabilityPayload
                or candidate.source_kind != SOURCE_KIND
                or candidate.source_id != _source_id(candidate.package_ref)
                or payload.manifest.package_ref != candidate.package_ref
                or candidate.payload_sha256 != payload.payload_sha256
            ):
                raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        except DistributionCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        failed = False
        try:
            record = self._record_for(candidate)
            self.validate_source_identity(candidate, record.payload)
            factory = record.entry_point.load()
            if not callable(factory):
                raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
            installed = factory()
            if (
                type(installed) is not InstalledCapabilityPackage
                or installed.package_ref != candidate.package_ref
                or installed.payload_sha256 != record.payload.payload_sha256
                or installed.source_id != candidate.source_id
                or installed.source_kind != candidate.source_kind
            ):
                raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
            return installed
        except DistributionCapabilitySourceError:
            raise
        except Exception:
            failed = True
        if failed:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)

    def _record_for(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> "_DistributionRecord":
        if type(candidate) is not CapabilityPackageCandidate:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        matches = tuple(
            record
            for record in self._validated_records()
            if record.package_ref == candidate.package_ref
            and _source_id(record.package_ref) == candidate.source_id
        )
        if len(matches) != 1:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        if candidate.source_kind != SOURCE_KIND:
            raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
        return matches[0]

    def _validated_records(self) -> tuple["_DistributionRecord", ...]:
        records: list[_DistributionRecord] = []
        for entry_record in self._validated_entry_records():
            payload_root = _payload_root_for(
                entry_record.distribution, entry_record.package_ref
            )
            payload = open_portable_payload(payload_root)
            if payload.manifest.package_ref != entry_record.package_ref:
                raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
            records.append(
                _DistributionRecord(
                    distribution=entry_record.distribution,
                    entry_point=entry_record.entry_point,
                    package_ref=entry_record.package_ref,
                    payload=payload,
                )
            )
        return tuple(records)

    def _validated_entry_records(self) -> tuple["_EntryRecord", ...]:
        records: list[_EntryRecord] = []
        seen_entries: set[str] = set()
        seen_refs: set[CapabilityPackageRef] = set()
        for distribution in self._distribution_values():
            for entry_point in _entry_points_for(distribution):
                entry_name = _entry_name(entry_point)
                package_ref = _parse_entry_point_name(entry_name)
                if entry_name in seen_entries or package_ref in seen_refs:
                    raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
                records.append(
                    _EntryRecord(
                        distribution=distribution,
                        entry_point=entry_point,
                        package_ref=package_ref,
                    )
                )
                seen_entries.add(entry_name)
                seen_refs.add(package_ref)
        return tuple(records)

    def _distribution_values(self) -> tuple[metadata.Distribution, ...]:
        if self._distributions is None:
            return tuple(metadata.distributions())
        return self._distributions


class _DistributionRecord:
    __slots__ = ("distribution", "entry_point", "package_ref", "payload")

    def __init__(
        self,
        *,
        distribution: metadata.Distribution,
        entry_point: metadata.EntryPoint,
        package_ref: CapabilityPackageRef,
        payload: PortableCapabilityPayload,
    ) -> None:
        self.distribution = distribution
        self.entry_point = entry_point
        self.package_ref = package_ref
        self.payload = payload


class _EntryRecord:
    __slots__ = ("distribution", "entry_point", "package_ref")

    def __init__(
        self,
        *,
        distribution: metadata.Distribution,
        entry_point: metadata.EntryPoint,
        package_ref: CapabilityPackageRef,
    ) -> None:
        self.distribution = distribution
        self.entry_point = entry_point
        self.package_ref = package_ref


def _entry_points_for(distribution: metadata.Distribution) -> tuple[metadata.EntryPoint, ...]:
    entries = tuple(distribution.entry_points)
    return tuple(
        entry for entry in entries if getattr(entry, "group", None) == ENTRY_POINT_GROUP
    )


def _entry_name(entry_point: metadata.EntryPoint) -> str:
    name = getattr(entry_point, "name", None)
    if not isinstance(name, str):
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
    return name


def _parse_entry_point_name(value: str) -> CapabilityPackageRef:
    parts = value.split("@")
    if len(parts) != 2:
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
    return CapabilityPackageRef(parts[0], parts[1])


def _payload_root_for(
    distribution: metadata.Distribution,
    package_ref: CapabilityPackageRef,
) -> Path:
    relative_root = _payload_relative_root(package_ref)
    descriptor = relative_root / "capability-package.json"
    files = _distribution_files(distribution)
    matches = tuple(path for path in files if PurePosixPath(str(path)) == descriptor)
    if len(matches) != 1:
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
    distribution_base = _distribution_base(distribution)
    descriptor_path = _declared_descriptor_path(distribution, matches[0])
    expected_descriptor = distribution_base / descriptor
    expected_root = distribution_base / relative_root
    failed = False
    expected_descriptor_path: Path | None = None
    expected_root_path: Path | None = None
    try:
        expected_descriptor_path = expected_descriptor.resolve(strict=True)
        expected_root_path = expected_root.resolve(strict=True)
    except Exception:
        failed = True
    if (
        failed
        or expected_descriptor_path is None
        or expected_root_path is None
        or descriptor_path != expected_descriptor_path
        or descriptor_path.parent != expected_root_path
    ):
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
    return descriptor_path.parent


def _distribution_files(distribution: metadata.Distribution) -> tuple[object, ...]:
    files = getattr(distribution, "files", None)
    if files is None:
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
    return tuple(files)


def _distribution_base(distribution: metadata.Distribution) -> Path:
    return Path(str(distribution.locate_file(PurePosixPath("")))).resolve(strict=True)


def _declared_descriptor_path(
    distribution: metadata.Distribution,
    declared_descriptor: object,
) -> Path:
    locate = getattr(declared_descriptor, "locate", None)
    if callable(locate):
        return Path(str(locate())).resolve(strict=True)
    if not isinstance(declared_descriptor, (str, PathLike)):
        raise DistributionCapabilitySourceError(_ERROR_MESSAGE)
    return Path(str(distribution.locate_file(declared_descriptor))).resolve(strict=True)


def _payload_relative_root(package_ref: CapabilityPackageRef) -> PurePosixPath:
    return _PAYLOAD_ROOT_PREFIX / package_ref.package_id / package_ref.version / "payload"


def _source_id(package_ref: CapabilityPackageRef) -> str:
    return f"{package_ref.package_id}.python-distribution"


def _distribution_name(distribution: metadata.Distribution) -> str:
    name = getattr(distribution, "name", None)
    if isinstance(name, str) and name:
        return name
    distribution_metadata = getattr(distribution, "metadata", None)
    if distribution_metadata is not None:
        value = distribution_metadata.get("Name")
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _distribution_version(distribution: metadata.Distribution) -> str:
    value = getattr(distribution, "version", None)
    return value if isinstance(value, str) and value else "unknown"


__all__ = (
    "ENTRY_POINT_GROUP",
    "DistributionCapabilityPackageSource",
    "DistributionCapabilitySourceError",
)
