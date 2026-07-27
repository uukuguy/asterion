"""Deterministic selection of one discovered capability-package source."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from asterion.capability_packages.model import (
    CapabilityPackageCandidate,
    InstalledCapabilityPackage,
    PortableCapabilityPayload,
)
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)
from asterion.capability_packages.sources import CapabilityPackageSource


class CapabilitySourceResolutionError(ValueError):
    """Raised when a discovered capability-package source is not exact."""


def load_installed_capability_packages(
    package_refs: Sequence[CapabilityPackageRef],
    sources: Iterable[CapabilityPackageSource],
) -> tuple[InstalledCapabilityPackage, ...]:
    """Resolve exact refs and load only their selected source providers."""

    refs = tuple(package_refs)
    source_values = tuple(sources)
    if (
        any(not isinstance(ref, CapabilityPackageRef) for ref in refs)
        or tuple(sorted(set(refs))) != refs
    ):
        raise CapabilitySourceResolutionError(
            "capability package refs must be sorted and unique"
        )

    discovered: list[tuple[CapabilityPackageSource, CapabilityPackageCandidate]] = []
    for source in source_values:
        candidates = source.discover_metadata()
        if not isinstance(candidates, tuple) or any(
            not isinstance(candidate, CapabilityPackageCandidate)
            for candidate in candidates
        ):
            raise CapabilitySourceResolutionError(
                "capability source discovery is invalid"
            )
        discovered.extend((source, candidate) for candidate in candidates)

    installed_packages: list[InstalledCapabilityPackage] = []
    all_candidates = tuple(candidate for _, candidate in discovered)
    for package_ref in refs:
        candidate = resolve_capability_source(
            package_ref,
            all_candidates,
            None,
        )
        selected_sources = tuple(
            source
            for source, discovered_candidate in discovered
            if discovered_candidate is candidate
        )
        if len(selected_sources) != 1:
            raise CapabilitySourceResolutionError(
                "capability source is unavailable or ambiguous"
            )
        source = selected_sources[0]
        payload = source.open_payload(candidate)
        if (
            not isinstance(payload, PortableCapabilityPayload)
            or payload.manifest.package_ref != package_ref
            or (
                candidate.payload_sha256 is not None
                and candidate.payload_sha256 != payload.payload_sha256
            )
        ):
            raise CapabilitySourceResolutionError(
                "capability package payload identity is invalid"
            )
        source.validate_source_identity(candidate, payload)
        installed = source.load_provider(candidate)
        if (
            not isinstance(installed, InstalledCapabilityPackage)
            or installed.package_ref != package_ref
            or installed.payload_sha256 != payload.payload_sha256
            or installed.source_id != candidate.source_id
            or installed.source_kind != candidate.source_kind
        ):
            raise CapabilitySourceResolutionError(
                "capability package provider identity is invalid"
            )
        installed_packages.append(installed)
    return tuple(installed_packages)


def resolve_capability_source(
    package_ref: CapabilityPackageRef,
    candidates: Sequence[CapabilityPackageCandidate],
    lock: CapabilitySourceLock | None,
) -> CapabilityPackageCandidate:
    """Select one exact discovered source without applying source precedence."""

    matches = tuple(
        candidate for candidate in candidates if candidate.package_ref == package_ref
    )
    if lock is None:
        if len(matches) != 1:
            raise CapabilitySourceResolutionError(
                "capability source is unavailable or ambiguous"
            )
        return matches[0]

    lock_entry = _lock_entry_for_package(lock, package_ref)
    locked_matches = tuple(
        candidate
        for candidate in matches
        if candidate.source_id == lock_entry.source_id
        and candidate.payload_sha256 == lock_entry.payload_sha256
    )
    if len(locked_matches) != 1:
        raise CapabilitySourceResolutionError(
            "capability source is unavailable or rejected"
        )
    return locked_matches[0]


def _lock_entry_for_package(
    lock: CapabilitySourceLock,
    package_ref: CapabilityPackageRef,
) -> CapabilitySourceLockEntry:
    entries = tuple(entry for entry in lock.entries if entry.package_ref == package_ref)
    if len(entries) != 1:
        raise CapabilitySourceResolutionError(
            "capability source is unavailable or rejected"
        )
    return entries[0]
