"""Metadata-only installed application provider for the Prime program."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.capability_packages import CapabilityPackageRef


def create_provider() -> InstalledApplicationProvider:
    """Return the Prime capability-program metadata binding."""

    root = Path(str(resources.files("asterion"))).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-agent",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="prime.capability-program",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime_agent/assemblies/prime-capability-program.json",
                ),
                capability_packages=(CapabilityPackageRef("prime-agent", "1.0.0"),),
                runtime_ids=("prime.restricted-worker",),
            ),
        ),
    )
