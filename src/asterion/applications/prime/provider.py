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
    """Return sorted native Prime applications and one peer runtime binding."""

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
                    root / "applications/prime/assemblies/prime-arc-agi-3-solving.json",
                ),
                capability_packages=(PRIME_ARC_AGI_3_SOLVER_PACKAGE,),
                runtime_ids=("asterion.prime",),
            ),
            # prime.ipython-coding is deliberately NOT published. It has no
            # native package and no installed-route witness yet, and the
            # detachment spec requires an unmigrated selector to be omitted so
            # metadata lookup rejects it before importing a runtime or starting
            # a process. Publishing it here also made resolution impossible for
            # the P7 route: the closure is validated for every published
            # application, so a P7 run failed unless P1's package was supplied
            # too. It returns when Phase 4 supplies its witness.
        ),
        runtime_factory_bindings=(asterion_prime_runtime_binding(),),
    )


__all__ = ("create_provider",)
