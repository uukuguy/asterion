"""Provider-free safety checks for the Prime capability program."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerError,
    PrimeRestrictedWorkerProfile,
    validate_prime_restricted_worker,
)
from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    PrimeSourceLockError,
    verify_prime_source_lock,
)


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
    expected_source_lock: PrimeSourceLock,
    source_root: Path,
) -> PrimePreflightResult:
    """Validate injected contracts without accessing provider resources."""

    if profile is None:
        return PrimePreflightResult("worker-unavailable")
    try:
        validate_prime_restricted_worker(profile)
    except (PrimeRestrictedWorkerError, TypeError):
        return PrimePreflightResult("worker-invalid")
    try:
        verify_prime_source_lock(source_root, expected_source_lock)
    except (PrimeSourceLockError, TypeError):
        return PrimePreflightResult("source-invalid")
    return PrimePreflightResult("PASS")
