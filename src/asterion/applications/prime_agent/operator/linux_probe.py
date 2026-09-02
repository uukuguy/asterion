"""Injected, Linux-only readiness classification for the Prime worker backend."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal


class PrimeLinuxBackendProbeError(ValueError):
    """Raised when injected backend facts are not a closed typed value."""


@dataclass(frozen=True, repr=False)
class LinuxBackendFacts:
    """Private operator observations; these are never returned by the probe."""

    engine: str
    daemon_available: bool
    image_available: bool
    operator_ready: bool
    safety_matches: bool

    def __post_init__(self) -> None:
        if type(self.engine) is not str or not self.engine or any(
            type(value) is not bool
            for value in (
                self.daemon_available,
                self.image_available,
                self.operator_ready,
                self.safety_matches,
            )
        ):
            raise PrimeLinuxBackendProbeError("prime linux backend facts are invalid")

    def __repr__(self) -> str:
        return "LinuxBackendFacts(redacted)"


@dataclass(frozen=True)
class PrimeLinuxBackendReadiness:
    """Small public readiness state, deliberately not a Prime evidence receipt."""

    status: Literal["ready", "External-limited", "failure"]
    reason: Literal[
        "unsupported-platform",
        "unsupported-engine",
        "missing-precondition",
        "safety-mismatch",
        "native-linux-ready",
    ]


class PrimeLinuxBackendProbe:
    """Classify only operator-injected native Linux backend facts.

    The action is intentionally not called for a non-Linux platform, so this
    adapter neither invokes Docker nor discovers operator configuration.
    """

    def __init__(self, platform_name: str, inspect: Callable[[], LinuxBackendFacts]) -> None:
        if type(platform_name) is not str or not callable(inspect):
            raise PrimeLinuxBackendProbeError("prime linux backend probe is invalid")
        self._platform_name = platform_name
        self._inspect = inspect

    def probe(self) -> PrimeLinuxBackendReadiness:
        if self._platform_name != "Linux":
            return PrimeLinuxBackendReadiness("External-limited", "unsupported-platform")

        facts = self._inspect()
        if type(facts) is not LinuxBackendFacts:
            return PrimeLinuxBackendReadiness("failure", "safety-mismatch")
        if facts.engine != "native-docker":
            return PrimeLinuxBackendReadiness("External-limited", "unsupported-engine")
        if not (facts.daemon_available and facts.image_available and facts.operator_ready):
            return PrimeLinuxBackendReadiness("External-limited", "missing-precondition")
        if facts.safety_matches is not True:
            return PrimeLinuxBackendReadiness("failure", "safety-mismatch")
        return PrimeLinuxBackendReadiness("ready", "native-linux-ready")
