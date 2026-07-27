"""Metadata-first adapter for installed capability-package distributions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import (
    IDENTIFIER,
    SEMANTIC_VERSION,
    CapabilityPackageRef,
)


ENTRY_POINT_GROUP = "asterion.capability_packages"
PAYLOAD_DATA_ROOT = "asterion_capability_packages"


class DistributionCapabilitySourceError(ValueError):
    """Raised when an installed capability distribution is invalid."""


@dataclass(frozen=True, slots=True)
class _DistributionRecord:
    candidate: CapabilityPackageCandidate
    entry_point: object
    payload_root: Path


class DistributionCapabilityPackageSource:
    """Discover distribution metadata without importing provider modules."""

    def __init__(
        self,
        distributions: Iterable[metadata.Distribution] | None = None,
    ) -> None:
        self._distributions = None if distributions is None else tuple(distributions)

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        """Return candidates using entry-point and wheel-file metadata only."""

        return tuple(
            sorted(
                (record.candidate for record in self._records()),
                key=lambda candidate: (
                    candidate.package_ref,
                    candidate.source_id,
                ),
            )
        )

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        """Open the exact selected distribution payload without provider load."""

        record = self._selected_record(candidate)
        try:
            payload = open_portable_payload(record.payload_root)
        except Exception:
            raise DistributionCapabilitySourceError(
                "installed capability distribution payload is invalid"
            ) from None
        self.validate_source_identity(candidate, payload)
        return payload

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        """Bind metadata-selected distribution content to its exact candidate."""

        self._selected_record(candidate)
        if (
            not isinstance(payload, PortableCapabilityPayload)
            or payload.manifest.package_ref != candidate.package_ref
        ):
            raise DistributionCapabilitySourceError(
                "installed capability distribution identity is invalid"
            )

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        """Load one selected provider only after duplicate and payload checks."""

        record = self._selected_record(candidate)
        payload = self.open_payload(candidate)
        try:
            loader = getattr(record.entry_point, "load", None)
            if not callable(loader):
                raise TypeError("capability provider entry point is invalid")
            factory = loader()
            if not callable(factory):
                raise TypeError("capability provider factory is not callable")
            installed = factory()
        except Exception:
            raise DistributionCapabilitySourceError(
                "installed capability distribution provider is unavailable"
            ) from None
        if (
            not isinstance(installed, InstalledCapabilityPackage)
            or installed.package_ref != candidate.package_ref
            or installed.payload_sha256 != payload.payload_sha256
            or installed.source_id != candidate.source_id
            or installed.source_kind != "python-distribution"
            or not _provider_resources_match(
                installed,
                payload_root=record.payload_root,
                payload=payload,
            )
        ):
            raise DistributionCapabilitySourceError(
                "installed capability distribution provider identity is invalid"
            )
        return installed

    def _selected_record(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> _DistributionRecord:
        if not isinstance(candidate, CapabilityPackageCandidate):
            raise DistributionCapabilitySourceError(
                "installed capability distribution candidate is invalid"
            )
        matches = tuple(
            record for record in self._records() if record.candidate == candidate
        )
        if len(matches) != 1:
            raise DistributionCapabilitySourceError(
                "installed capability distribution selection is invalid"
            )
        return matches[0]

    def _records(self) -> tuple[_DistributionRecord, ...]:
        records: list[_DistributionRecord] = []
        for distribution, entry_point in self._entry_points():
            record = _record(distribution, entry_point)
            if record is not None:
                records.append(record)
        return tuple(records)

    def _entry_points(self) -> tuple[tuple[object, object], ...]:
        if self._distributions is None:
            pairs: list[tuple[object, object]] = []
            for entry_point in metadata.entry_points(group=ENTRY_POINT_GROUP):
                distribution = getattr(entry_point, "dist", None)
                if distribution is not None:
                    pairs.append((distribution, entry_point))
                    continue
                pairs.extend(
                    (owner, entry_point)
                    for owner in metadata.distributions()
                    if entry_point in getattr(owner, "entry_points", ())
                )
            return tuple(pairs)
        return tuple(
            (distribution, entry_point)
            for distribution in self._distributions
            for entry_point in getattr(distribution, "entry_points", ())
            if getattr(entry_point, "group", None) == ENTRY_POINT_GROUP
        )


def _record(
    distribution: object,
    entry_point: object,
) -> _DistributionRecord | None:
    package_ref = _package_ref(getattr(entry_point, "name", None))
    if package_ref is None:
        raise DistributionCapabilitySourceError(
            "installed capability distribution entry point is invalid"
        )
    distribution_name = getattr(distribution, "name", None)
    distribution_version = getattr(distribution, "version", None)
    if (
        not isinstance(distribution_name, str)
        or not distribution_name
        or not isinstance(distribution_version, str)
        or not distribution_version
    ):
        return None
    payload_root = _payload_root(distribution, package_ref)
    if payload_root is None:
        return None
    candidate = CapabilityPackageCandidate(
        package_ref=package_ref,
        source_id=_source_id(
            package_ref,
            distribution_name=distribution_name,
            distribution_version=distribution_version,
        ),
        source_kind="python-distribution",
        payload_sha256=None,
        metadata={
            "distribution_name": distribution_name,
            "distribution_version": distribution_version,
        },
    )
    return _DistributionRecord(candidate, entry_point, payload_root)


def _package_ref(value: object) -> CapabilityPackageRef | None:
    if not isinstance(value, str) or value.count("@") != 1:
        return None
    package_id, version = value.split("@")
    if (
        IDENTIFIER.fullmatch(package_id) is None
        or SEMANTIC_VERSION.fullmatch(version) is None
    ):
        return None
    return CapabilityPackageRef(package_id, version)


def _payload_root(
    distribution: object,
    package_ref: CapabilityPackageRef,
) -> Path | None:
    expected = f"{PAYLOAD_DATA_ROOT}/{package_ref.selector}/capability-package.json"
    files = getattr(distribution, "files", None)
    matches = tuple(file for file in files or () if str(file) == expected)
    if len(matches) != 1:
        return None
    try:
        located = getattr(distribution, "locate_file")(matches[0])
        root = Path(located).parent
        if root.is_symlink():
            return None
        return root.resolve(strict=True)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _source_id(
    package_ref: CapabilityPackageRef,
    *,
    distribution_name: str,
    distribution_version: str,
) -> str:
    return (
        "python-distribution:"
        f"{distribution_name}@{distribution_version}:{package_ref.selector}"
    )


def _provider_resources_match(
    installed: InstalledCapabilityPackage,
    *,
    payload_root: Path,
    payload: PortableCapabilityPayload,
) -> bool:
    try:
        root = payload_root.resolve(strict=True)
        expected_catalog = (root / "capabilities").resolve(strict=True)
        if expected_catalog.is_symlink() or installed.catalog_roots != (
            expected_catalog,
        ):
            return False
        suite_paths = installed.benchmark_suite_paths
        if len(suite_paths) != len(payload.manifest.benchmark_suites):
            return False
        if not suite_paths:
            return True
        suite_root = (root / "benchmark-suites").resolve(strict=True)
        return all(
            path == path.resolve(strict=True)
            and path.parent == suite_root
            and path.suffix == ".json"
            and path.is_file()
            and not path.is_symlink()
            for path in suite_paths
        )
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return False
