"""Metadata-only provider for native Asterion-prime applications."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.first_party_packages import (
    PRIME_ARC_AGI_3_SOLVER_PACKAGE,
)
from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.applications.prime.runtime_binding import (
    asterion_prime_runtime_binding,
)


def create_provider() -> InstalledApplicationProvider:
    """Return the single native P7 application and its peer runtime binding."""

    root = Path(str(resources.files("asterion"))).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="prime-applications",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="prime.arc-agi-3-solving",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/prime/assemblies/prime-arc-agi-3-solving.json",
                ),
                capability_packages=(PRIME_ARC_AGI_3_SOLVER_PACKAGE,),
                runtime_ids=("asterion.prime",),
            ),
        ),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


__all__ = ("create_provider",)
