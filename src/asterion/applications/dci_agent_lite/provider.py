"""First-party DCI application binding shipped with Asterion."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.capability_packages import CapabilityPackageRef
from asterion.applications.dci_agent_lite.acceptance import (
    installed_acceptance_checks,
)
from asterion.capabilities.dci.implementation.reproduction.verification import create_dci_product


DCI_PACKAGE = CapabilityPackageRef("dci", "1.0.0")


def create_provider() -> InstalledApplicationProvider:
    """Return the immutable built-in DCI research application binding."""

    root = Path(str(resources.files("asterion"))).resolve()
    application_root = root / "applications/dci_agent_lite"
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="dci-agent-lite",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="dci.research-capability",
                version="1.0.0",
                assembly_paths=(
                    application_root
                    / "assemblies/dci-research-capability-claude.json",
                    application_root / "assemblies/dci-research-capability.json",
                ),
                capability_packages=(DCI_PACKAGE,),
                runtime_ids=("claude-code.reference", "pi.reference"),
            ),
            InstalledApplication(
                application_id="dci.complete-application",
                version="1.0.0",
                assembly_paths=(
                    application_root / "assemblies/dci-complete-application-claude.json",
                    application_root / "assemblies/dci-complete-application-pi.json",
                ),
                capability_packages=(DCI_PACKAGE,),
                runtime_ids=("claude-code.reference", "pi.reference"),
            ),
        ),
        product=create_dci_product(
            repo_root=root,
            acceptance_checks=installed_acceptance_checks,
        ),
    )
