"""Native host that assembles installed capability packages on one runtime."""

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
    """Return the Native application that names both installed packages."""

    root = Path(str(resources.files("asterion"))).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="native",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="native.packages",
                version="1.0.0",
                assembly_paths=(
                    root / "applications/native/assemblies/native-packages.json",
                ),
                capability_packages=(
                    CapabilityPackageRef("controlled-code", "1.0.0"),
                    CapabilityPackageRef("dci", "1.0.0"),
                ),
                runtime_ids=("pi.reference",),
            ),
        ),
    )
