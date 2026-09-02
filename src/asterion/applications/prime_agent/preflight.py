"""Provider-free safety checks for the Prime capability program."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerError,
    PrimeRestrictedWorkerProfile,
    validate_prime_restricted_worker,
)
from asterion.applications.prime_agent.source_lock import PrimeSourceLock


_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LOCK_FIELDS = frozenset({"commit", "tree_sha256", "package_lock_sha256"})
_STATUSES = frozenset(
    {"PASS", "worker-invalid", "worker-unavailable", "source-invalid"}
)


@dataclass(frozen=True)
class PrimePreflightResult:
    """A public-safe result of static Prime preflight validation."""

    status: Literal["PASS", "worker-invalid", "worker-unavailable", "source-invalid"]

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError("Prime preflight status is invalid")


def prime_preflight(
    profile: PrimeRestrictedWorkerProfile | None,
    source_lock: PrimeSourceLock,
) -> PrimePreflightResult:
    """Validate injected static contracts without accessing any provider resource."""

    if profile is None:
        return PrimePreflightResult("worker-unavailable")
    try:
        validate_prime_restricted_worker(profile)
    except (PrimeRestrictedWorkerError, TypeError):
        return PrimePreflightResult("worker-invalid")
    if not _valid_source_lock(source_lock):
        return PrimePreflightResult("source-invalid")
    return PrimePreflightResult("PASS")


def _valid_source_lock(value: object) -> bool:
    return (
        type(value) is PrimeSourceLock
        and frozenset(vars(value)) == _LOCK_FIELDS
        and type(value.commit) is str
        and _COMMIT.fullmatch(value.commit) is not None
        and type(value.tree_sha256) is str
        and _SHA256.fullmatch(value.tree_sha256) is not None
        and type(value.package_lock_sha256) is str
        and _SHA256.fullmatch(value.package_lock_sha256) is not None
    )
