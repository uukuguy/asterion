"""First-party DCI application binding shipped with Asterion."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
)
from asterion.capabilities.dci_research import DciLocalResearchImplementation
from asterion.capabilities.dci_research.complete import complete_dci_bindings
from asterion.dci.application_executor import EnvironmentDciRunExecutor
from asterion.dci.bridge import DciRunExecutor
from asterion.dci.verification import create_dci_product
from asterion.packages.catalog import PackageRef


def create_provider(
    *, native_executor: DciRunExecutor | None = None
) -> InstalledApplicationProvider:
    """Return the immutable built-in DCI research application binding."""

    executor = EnvironmentDciRunExecutor() if native_executor is None else native_executor
    complete_executor = (
        EnvironmentDciRunExecutor(honor_request_tools=True)
        if native_executor is None
        else native_executor
    )
    root = Path(str(resources.files("asterion"))).resolve()
    application_root = root / "applications/dci_agent_lite"
    capability_root = root / "capabilities/dci_research"
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
                catalog_roots=(capability_root / "manifests",),
                implementations=(
                    (
                        PackageRef("dci.research", "1.0.0"),
                        DciLocalResearchImplementation(native_executor=executor),
                    ),
                ),
                runtime_ids=("claude-code.reference", "pi.reference"),
            ),
            InstalledApplication(
                application_id="dci.complete-application",
                version="1.0.0",
                assembly_paths=(
                    application_root / "assemblies/dci-complete-application-claude.json",
                    application_root / "assemblies/dci-complete-application-pi.json",
                ),
                catalog_roots=(capability_root / "manifests",),
                implementations=complete_dci_bindings(native_executor=complete_executor),
                runtime_ids=("claude-code.reference", "pi.reference"),
            ),
        ),
        product=create_dci_product(),
    )
