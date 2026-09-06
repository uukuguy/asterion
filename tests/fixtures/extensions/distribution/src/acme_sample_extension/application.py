"""Selected application provider for the public-extension reference."""

from __future__ import annotations

import os
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


if os.environ.get("ASTERION_TEST_FORBID_APPLICATION_IMPORT") == "1":
    raise RuntimeError("acme application provider imported")


def create_application_provider() -> InstalledApplicationProvider:
    distribution = metadata.distribution("asterion-acme-sample-extension")
    root = Path(
        str(distribution.locate_file("asterion_applications/acme.sample/1.0.0"))
    ).resolve()
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="acme-sample",
        resource_root=root,
        applications=(
            InstalledApplication(
                application_id="acme.research-application",
                version="1.0.0",
                assembly_paths=(root / "assembly.json",),
                capability_packages=(CapabilityPackageRef("acme.sample", "1.0.0"),),
                runtime_ids=("acme.inline",),
            ),
        ),
        runtime_factory_bindings=(RuntimeFactoryBinding("acme.inline", (), create_runtime),),
    )
