from importlib import metadata
from pathlib import Path
from asterion.application_sdk import (
    APPLICATION_PROVIDER_PROTOCOL,
    CapabilityPackageRef,
    InstalledApplication,
    InstalledApplicationProvider,
    RuntimeFactoryBinding,
)
from .runtime import create_runtime


def create_application_provider() -> InstalledApplicationProvider:
    r = Path(
        str(
            metadata.distribution("asterion-contoso-audit-extension").locate_file(
                "asterion_applications/contoso.audit/1.0.0"
            )
        )
    ).resolve()
    return InstalledApplicationProvider(
        APPLICATION_PROVIDER_PROTOCOL,
        "contoso-audit",
        r,
        (
            InstalledApplication(
                "contoso.audited-research",
                "1.0.0",
                (r / "assembly.json",),
                (
                    CapabilityPackageRef("acme.sample", "1.0.0"),
                    CapabilityPackageRef("contoso.audit", "1.0.0"),
                ),
                ("contoso.inline",),
            ),
        ),
        runtime_factory_bindings=(
            RuntimeFactoryBinding("contoso.inline", (), create_runtime),
        ),
    )
