"""Exact public-release metadata for native Prime applications.

This module deliberately contains declarative identities only. It can be used
by package and acceptance checks without importing a provider, runtime,
payload, or executable implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

from asterion.capability_packages import CapabilityPackageRef


@dataclass(frozen=True)
class PrimeReleaseApplication:
    """One exact publicly indexed Prime application."""

    application_id: str
    version: str
    assembly_filename: str
    capability_package: CapabilityPackageRef

    @property
    def assembly_identity(self) -> str:
        return f"applications/prime/assemblies/{self.assembly_filename}"

    @property
    def index_name(self) -> str:
        return f"{self.application_id}__{self.version}"


PRIME_RELEASE_INVENTORY = (
    PrimeReleaseApplication(
        "prime.arc-agi-3-solving",
        "1.0.0",
        "prime-arc-agi-3-solving.json",
        CapabilityPackageRef("prime-arc-agi-3-solver", "1.0.0"),
    ),
    PrimeReleaseApplication(
        "prime.bounded-autonomy",
        "1.0.0",
        "prime-bounded-autonomy.json",
        CapabilityPackageRef("prime-bounded-autonomy-native", "1.0.0"),
    ),
    PrimeReleaseApplication(
        "prime.continual-improvement",
        "1.0.0",
        "prime-continual-improvement.json",
        CapabilityPackageRef("prime-continual-improvement-native", "1.0.0"),
    ),
    PrimeReleaseApplication(
        "prime.ipython-coding",
        "1.0.0",
        "prime-ipython-coding.json",
        CapabilityPackageRef("prime-ipython-coding-native", "1.0.0"),
    ),
    PrimeReleaseApplication(
        "prime.long-session-continuity",
        "1.0.0",
        "prime-long-session-continuity.json",
        CapabilityPackageRef("prime-long-session-continuity-native", "1.0.0"),
    ),
    PrimeReleaseApplication(
        "prime.recursive-workflow",
        "1.0.0",
        "prime-recursive-workflow.json",
        CapabilityPackageRef("prime-recursive-workflow-native", "1.0.0"),
    ),
    PrimeReleaseApplication(
        "prime.programmatic-long-context",
        "1.0.0",
        "prime-programmatic-long-context.json",
        CapabilityPackageRef("prime-programmatic-long-context-native", "1.0.0"),
    ),
)


def prime_assembly_identities() -> tuple[str, ...]:
    """Return the exact package-relative Prime assembly identities."""

    return tuple(item.assembly_identity for item in PRIME_RELEASE_INVENTORY)


def prime_application_index() -> dict[str, str]:
    """Return exact static selector-to-provider targets for release checks."""

    return {
        item.index_name: "asterion.applications.prime:create_provider"
        for item in PRIME_RELEASE_INVENTORY
    }


def prime_release_application(application_id: str) -> PrimeReleaseApplication:
    """Return one declared application by its canonical, exact ID."""

    for item in PRIME_RELEASE_INVENTORY:
        if item.application_id == application_id:
            return item
    raise ValueError("unknown Prime release application")


__all__ = (
    "PRIME_RELEASE_INVENTORY",
    "PrimeReleaseApplication",
    "prime_application_index",
    "prime_assembly_identities",
    "prime_release_application",
)
