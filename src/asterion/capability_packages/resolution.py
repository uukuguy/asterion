"""Deterministic selection of one discovered capability-package source."""

from __future__ import annotations

from collections.abc import Sequence

from asterion.capability_packages.model import CapabilityPackageCandidate
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
)


class CapabilitySourceResolutionError(ValueError):
    """Raised when a discovered capability-package source is not exact."""


def resolve_capability_source(
    package_ref: CapabilityPackageRef,
    candidates: Sequence[CapabilityPackageCandidate],
    lock: CapabilitySourceLock | None,
) -> CapabilityPackageCandidate:
    """Select one exact discovered source without applying source precedence."""

    matches = tuple(
        candidate
        for candidate in candidates
        if candidate.package_ref == package_ref
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
    entries = tuple(
        entry for entry in lock.entries if entry.package_ref == package_ref
    )
    if len(entries) != 1:
        raise CapabilitySourceResolutionError(
            "capability source is unavailable or rejected"
        )
    return entries[0]
