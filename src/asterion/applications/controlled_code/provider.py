"""First-party controlled-code application binding."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.capabilities.controlled_code import controlled_code_bindings


def create_provider() -> InstalledApplicationProvider:
    """Return the immutable controlled-code application binding."""

    root = Path(str(resources.files("asterion"))).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="controlled-code",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="code.quality",
                version="1.0.0",
                assembly_paths=(
                    root
                    / "applications/controlled_code/assemblies/controlled-code-validation.json",
                ),
                catalog_roots=(root / "capabilities/controlled_code/manifests",),
                implementations=controlled_code_bindings(),
                runtime_ids=("pi.reference",),
            ),
        ),
    )
