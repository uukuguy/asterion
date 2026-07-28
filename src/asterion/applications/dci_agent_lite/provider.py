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
    DciApplicationAcceptanceInventory,
    create_dci_product,
)
from asterion.capability_packages.protocol import CapabilityPackageRef


_EXPECTED_PACKAGED_ASSEMBLIES = (
    "applications/controlled_code/assemblies/controlled-code-validation.json",
    "applications/dci_agent_lite/assemblies/dci-complete-application-claude.json",
    "applications/dci_agent_lite/assemblies/dci-complete-application-pi.json",
    "applications/dci_agent_lite/assemblies/dci-local-research.json",
    "applications/dci_agent_lite/assemblies/dci-research-capability-claude.json",
    "applications/dci_agent_lite/assemblies/dci-research-capability.json",
)
_EXPECTED_BOUND_ASSEMBLIES = tuple(
    identity
    for identity in _EXPECTED_PACKAGED_ASSEMBLIES
    if not identity.endswith("/dci-local-research.json")
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
            application_acceptance_inventory_factory=(
                create_application_acceptance_inventory
            ),
        ),
    )


def create_application_acceptance_inventory() -> DciApplicationAcceptanceInventory:
    """Return application-owned identities for provider-free acceptance."""

    from asterion.applications.controlled_code import (
        create_provider as create_controlled_provider,
    )
    from asterion.applications.dci_agent_lite import (
        create_provider as create_dci_provider,
    )
    from asterion.capabilities.builtin import create_controlled_code_package
    from asterion.capabilities.dci.provider import (
        create_provider as create_installed_dci_package,
    )

    package_root = Path(str(resources.files("asterion"))).resolve()

    def assembly_identity(path: Path) -> str | None:
        if path.is_symlink():
            return None
        try:
            relative = path.resolve(strict=True).relative_to(package_root)
        except (OSError, ValueError):
            return None
        identity = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not identity.startswith("applications/")
        ):
            return None
        return identity

    try:
        packaged_assemblies = tuple(
            sorted(
                identity
                for path in (package_root / "applications").glob(
                    "*/assemblies/*.json"
                )
                if (identity := assembly_identity(path)) is not None
            )
        )
    except OSError:
        packaged_assemblies = ()
    return DciApplicationAcceptanceInventory(
        provider_factories=(create_controlled_provider, create_dci_provider),
        package_factories=(
            create_controlled_code_package,
            create_installed_dci_package,
        ),
        expected_provider_ids=("controlled-code", "dci-agent-lite"),
        expected_bound_assemblies=_EXPECTED_BOUND_ASSEMBLIES,
        packaged_assemblies=packaged_assemblies,
        expected_packaged_assemblies=_EXPECTED_PACKAGED_ASSEMBLIES,
        assembly_identity=assembly_identity,
    )
