"""Exact source-lock resolution for capability-package candidates."""

from __future__ import annotations

from collections.abc import Sequence

from asterion.capabilities.protocol import CAPABILITY_ID, SEMANTIC_VERSION
from asterion.capability_packages.model import CapabilityPackageCandidate
from asterion.capability_packages.protocol import (
    CapabilityPackageRef,
    CapabilitySourceLock,
    CapabilitySourceLockEntry,
    SHA256,
)


class CapabilitySourceResolutionError(ValueError):
    """Raised when exact capability-package source selection fails."""


def resolve_capability_source(
    package_ref: CapabilityPackageRef,
    candidates: Sequence[CapabilityPackageCandidate],
    lock: CapabilitySourceLock | None,
) -> CapabilityPackageCandidate:
    """Return the original candidate selected by exact package/source identity."""

    _validate_package_ref(package_ref)
    candidate_values = _candidate_tuple(candidates)
    lock_entries = _lock_entries(lock)

    matches = _matching_candidates(package_ref, candidate_values)
    if lock_entries is None:
        if not matches:
            raise CapabilitySourceResolutionError("capability source is unavailable")
        if len(matches) != 1:
            raise CapabilitySourceResolutionError("capability source is ambiguous")
        return matches[0]

    selected_lock = _lock_entry_for_package(package_ref, lock_entries)
    if selected_lock is None:
        if not matches:
            raise CapabilitySourceResolutionError("capability source is unavailable")
        if len(matches) != 1:
            raise CapabilitySourceResolutionError("capability source is ambiguous")
        return matches[0]

    source_matches = _matching_source_candidates(selected_lock, matches)
    if not source_matches:
        raise CapabilitySourceResolutionError("capability source is unavailable")
    digest_matches = tuple(
        candidate
        for candidate in source_matches
        if candidate.payload_sha256 == selected_lock.payload_sha256
    )
    if not digest_matches:
        raise CapabilitySourceResolutionError("capability source digest is rejected")
    if len(digest_matches) != 1:
        raise CapabilitySourceResolutionError("capability source is ambiguous")
    return digest_matches[0]


def _candidate_tuple(
    candidates: Sequence[CapabilityPackageCandidate],
) -> tuple[CapabilityPackageCandidate, ...]:
    if not isinstance(candidates, Sequence):
        raise CapabilitySourceResolutionError(
            "capability source candidates are invalid"
        )
    failed = False
    values: tuple[CapabilityPackageCandidate, ...] = ()
    try:
        values = tuple(candidates)
    except Exception:
        failed = True
    if failed:
        raise CapabilitySourceResolutionError(
            "capability source candidates are invalid"
        )
    for candidate in values:
        _validate_candidate(candidate)
    return values


def _lock_entries(
    lock: CapabilitySourceLock | None,
) -> tuple[CapabilitySourceLockEntry, ...] | None:
    if lock is None:
        return None
    if type(lock) is not CapabilitySourceLock:
        raise CapabilitySourceResolutionError("capability source lock is invalid")
    failed = False
    entries: tuple[CapabilitySourceLockEntry, ...] = ()
    try:
        entries = tuple(lock.entries)
    except Exception:
        failed = True
    if failed:
        raise CapabilitySourceResolutionError("capability source lock is invalid")
    for entry in entries:
        _validate_lock_entry(entry)
    return entries


def _matching_candidates(
    package_ref: CapabilityPackageRef,
    candidates: tuple[CapabilityPackageCandidate, ...],
) -> tuple[CapabilityPackageCandidate, ...]:
    failed = False
    matches: tuple[CapabilityPackageCandidate, ...] = ()
    try:
        matches = tuple(
            candidate
            for candidate in candidates
            if candidate.package_ref == package_ref
        )
    except Exception:
        failed = True
    if failed:
        raise CapabilitySourceResolutionError(
            "capability source candidates are invalid"
        )
    return matches


def _lock_entry_for_package(
    package_ref: CapabilityPackageRef,
    entries: tuple[CapabilitySourceLockEntry, ...],
) -> CapabilitySourceLockEntry | None:
    failed = False
    selected: tuple[CapabilitySourceLockEntry, ...] = ()
    try:
        selected = tuple(entry for entry in entries if entry.package_ref == package_ref)
    except Exception:
        failed = True
    if failed:
        raise CapabilitySourceResolutionError("capability source lock is invalid")
    if len(selected) > 1:
        raise CapabilitySourceResolutionError("capability source lock is invalid")
    return selected[0] if selected else None


def _matching_source_candidates(
    lock_entry: CapabilitySourceLockEntry,
    candidates: tuple[CapabilityPackageCandidate, ...],
) -> tuple[CapabilityPackageCandidate, ...]:
    failed = False
    matches: tuple[CapabilityPackageCandidate, ...] = ()
    try:
        matches = tuple(
            candidate
            for candidate in candidates
            if candidate.source_id == lock_entry.source_id
        )
    except Exception:
        failed = True
    if failed:
        raise CapabilitySourceResolutionError(
            "capability source candidates are invalid"
        )
    return matches


def _validate_candidate(candidate: object) -> None:
    if type(candidate) is not CapabilityPackageCandidate:
        raise CapabilitySourceResolutionError(
            "capability source candidates are invalid"
        )
    _validate_package_ref(
        candidate.package_ref,
        message="capability source candidates are invalid",
    )
    _validate_identifier(candidate.source_id, "capability source candidates are invalid")
    if candidate.payload_sha256 is not None:
        _validate_digest(
            candidate.payload_sha256,
            "capability source candidates are invalid",
        )


def _validate_lock_entry(entry: object) -> None:
    if type(entry) is not CapabilitySourceLockEntry:
        raise CapabilitySourceResolutionError("capability source lock is invalid")
    _validate_package_ref(entry.package_ref, message="capability source lock is invalid")
    _validate_identifier(entry.source_id, "capability source lock is invalid")
    _validate_digest(entry.payload_sha256, "capability source lock is invalid")


def _validate_package_ref(
    package_ref: object,
    *,
    message: str = "capability source request is invalid",
) -> None:
    if type(package_ref) is not CapabilityPackageRef:
        raise CapabilitySourceResolutionError(message)
    _validate_identifier(package_ref.package_id, message)
    if not (
        isinstance(package_ref.version, str)
        and SEMANTIC_VERSION.fullmatch(package_ref.version) is not None
    ):
        raise CapabilitySourceResolutionError(message)


def _validate_identifier(value: object, message: str) -> None:
    if not isinstance(value, str) or CAPABILITY_ID.fullmatch(value) is None:
        raise CapabilitySourceResolutionError(message)


def _validate_digest(value: object, message: str) -> None:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise CapabilitySourceResolutionError(message)


__all__ = (
    "CapabilitySourceResolutionError",
    "resolve_capability_source",
)
