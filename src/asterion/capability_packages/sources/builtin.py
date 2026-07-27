"""Explicit metadata-first source adapter for built-in capability packages."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef


class BuiltinCapabilitySourceError(ValueError):
    """Raised when a built-in source registration or identity is invalid."""


@dataclass(frozen=True, slots=True)
class BuiltinCapabilityRegistration:
    """One explicit built-in package payload and deferred provider factory."""

    package_ref: CapabilityPackageRef
    payload_root: Path
    provider_factory: Callable[[], InstalledCapabilityPackage]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.package_ref, CapabilityPackageRef)
            or not isinstance(self.payload_root, Path)
            or not callable(self.provider_factory)
        ):
            raise BuiltinCapabilitySourceError(
                "built-in capability registration is invalid"
            )


class BuiltinCapabilityPackageSource:
    """Expose explicitly registered built-ins without scanning or early imports."""

    def __init__(
        self,
        registrations: Iterable[BuiltinCapabilityRegistration] | None = None,
    ) -> None:
        if registrations is None:
            from asterion.capabilities.builtin import (
                builtin_capability_sources,
            )

            registrations = builtin_capability_sources()
        values = tuple(registrations)
        if (
            not values
            or any(
                not isinstance(value, BuiltinCapabilityRegistration) for value in values
            )
            or len({value.package_ref for value in values}) != len(values)
        ):
            raise BuiltinCapabilitySourceError(
                "built-in capability registrations are invalid"
            )
        self._registrations = values

    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]:
        """Return safe registered identities without touching payload or code."""

        return tuple(
            CapabilityPackageCandidate(
                package_ref=registration.package_ref,
                source_id=_source_id(registration.package_ref),
                source_kind="builtin",
                payload_sha256=None,
                metadata={},
            )
            for registration in self._registrations
        )

    def open_payload(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> PortableCapabilityPayload:
        """Validate and snapshot the exact selected built-in payload."""

        registration = self._registration_for(candidate)
        payload = open_portable_payload(registration.payload_root)
        self.validate_source_identity(candidate, payload)
        return payload

    def validate_source_identity(
        self,
        candidate: CapabilityPackageCandidate,
        payload: PortableCapabilityPayload,
    ) -> None:
        """Bind registered metadata to the validated portable package."""

        registration = self._registration_for(candidate)
        if (
            not isinstance(payload, PortableCapabilityPayload)
            or payload.manifest.package_ref != registration.package_ref
        ):
            raise BuiltinCapabilitySourceError(
                "built-in capability source identity is invalid"
            )

    def load_provider(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> InstalledCapabilityPackage:
        """Load only the selected factory and bind it to validated content."""

        registration = self._registration_for(candidate)
        payload = self.open_payload(candidate)
        try:
            installed = registration.provider_factory()
        except Exception:
            raise BuiltinCapabilitySourceError(
                "built-in capability provider is unavailable"
            ) from None
        if (
            not isinstance(installed, InstalledCapabilityPackage)
            or installed.package_ref != candidate.package_ref
            or installed.payload_sha256 != payload.payload_sha256
            or installed.source_id != candidate.source_id
            or installed.source_kind != "builtin"
            or not _provider_resources_match(
                installed,
                registration=registration,
                payload=payload,
            )
        ):
            raise BuiltinCapabilitySourceError(
                "built-in capability provider identity is invalid"
            )
        return installed

    def _registration_for(
        self,
        candidate: CapabilityPackageCandidate,
    ) -> BuiltinCapabilityRegistration:
        if not isinstance(candidate, CapabilityPackageCandidate):
            raise BuiltinCapabilitySourceError(
                "built-in capability candidate is invalid"
            )
        matches = tuple(
            registration
            for registration in self._registrations
            if candidate.package_ref == registration.package_ref
            and candidate.source_id == _source_id(registration.package_ref)
            and candidate.source_kind == "builtin"
            and candidate.payload_sha256 is None
            and not candidate.metadata
        )
        if len(matches) != 1:
            raise BuiltinCapabilitySourceError(
                "built-in capability candidate is unavailable"
            )
        return matches[0]


def _source_id(package_ref: CapabilityPackageRef) -> str:
    return f"builtin:{package_ref.package_id}@{package_ref.version}"


def _provider_resources_match(
    installed: InstalledCapabilityPackage,
    *,
    registration: BuiltinCapabilityRegistration,
    payload: PortableCapabilityPayload,
) -> bool:
    try:
        payload_root = registration.payload_root.resolve(strict=True)
        expected_catalog = (payload_root / "capabilities").resolve(strict=True)
        if (
            installed.catalog_roots != (expected_catalog,)
            or expected_catalog.is_symlink()
        ):
            return False
        suite_paths = installed.benchmark_suite_paths
        if len(suite_paths) != len(payload.manifest.benchmark_suites):
            return False
        if not suite_paths:
            return True
        suite_root = (payload_root / "benchmark-suites").resolve(strict=True)
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
