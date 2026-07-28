"""First-party DCI application binding shipped with Asterion."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.capabilities.dci.implementation.reproduction.verification import (
    create_dci_product,
)
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capabilities.dci_research.provider import (
    create_provider as create_dci_package,
)


def create_provider() -> InstalledApplicationProvider:
    """Return the immutable built-in DCI research application binding."""

    root = Path(str(resources.files("asterion"))).resolve()
    application_root = root / "applications/dci_agent_lite"
    package_ref = CapabilityPackageRef("dci", "1.0.0")
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="dci-agent-lite",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="dci.research-capability",
                version="1.0.0",
                assembly_paths=(
                    application_root / "assemblies/dci-research-capability-claude.json",
                    application_root / "assemblies/dci-research-capability.json",
                ),
                capability_packages=(package_ref,),
                runtime_ids=("claude-code.reference", "pi.reference"),
            ),
            InstalledApplication(
                application_id="dci.complete-application",
                version="1.0.0",
                assembly_paths=(
                    application_root
                    / "assemblies/dci-complete-application-claude.json",
                    application_root / "assemblies/dci-complete-application-pi.json",
                ),
                capability_packages=(package_ref,),
                runtime_ids=("claude-code.reference", "pi.reference"),
            ),
        ),
        product=create_dci_product(
            repo_root=root,
            dci_application_provider_factory=create_provider,
            dci_capability_package_factory=create_dci_package,
        ),
    )
