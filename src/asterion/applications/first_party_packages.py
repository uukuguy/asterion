"""First-party capability-package registrations shipped with Asterion."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.capabilities.execution import CapabilityImplementationBinding
from asterion.capability_packages.model import (
    BenchmarkTaskBinding,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import BuiltinCapabilityRegistration


CONTROLLED_CODE_PACKAGE = CapabilityPackageRef("controlled-code", "1.0.0")
CONTROLLED_CODE_SOURCE_ID = "controlled-code.builtin"
DCI_PACKAGE = CapabilityPackageRef("dci", "1.0.0")
PRIME_AGENT_PACKAGE = CapabilityPackageRef("prime-agent", "1.0.0")


def builtin_capability_registrations() -> tuple[BuiltinCapabilityRegistration, ...]:
    """Return explicit first-party registrations without loading providers."""

    package_root = Path(str(resources.files("asterion.capabilities"))).resolve()
    return (
        BuiltinCapabilityRegistration(
            CONTROLLED_CODE_PACKAGE,
            package_root / "controlled_code/payload",
            create_controlled_code_package,
        ),
        BuiltinCapabilityRegistration(
            DCI_PACKAGE,
            package_root / "dci/payload",
            create_dci_package,
        ),
        BuiltinCapabilityRegistration(
            PRIME_AGENT_PACKAGE,
            package_root / "prime_agent/payload",
            create_prime_agent_package,
        ),
    )


def create_controlled_code_package() -> InstalledCapabilityPackage:
    """Load the selected controlled-code provider after payload validation."""

    payload_root = Path(str(resources.files("asterion.capabilities"))).resolve() / (
        "controlled_code/payload"
    )
    payload = open_portable_payload(payload_root)
    from asterion.capabilities.controlled_code import controlled_code_bindings

    return InstalledCapabilityPackage(
        package_ref=CONTROLLED_CODE_PACKAGE,
        payload_sha256=payload.payload_sha256,
        source_id=CONTROLLED_CODE_SOURCE_ID,
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=tuple(
            CapabilityImplementationBinding(ref, implementation)
            for ref, implementation in controlled_code_bindings()
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=CONTROLLED_CODE_PACKAGE,
                binding_id="controlled-code.conformance",
                implementation=object(),
            ),
        ),
    )


def create_dci_package() -> InstalledCapabilityPackage:
    """Load the selected DCI provider only after source selection."""

    from asterion.capabilities.dci.provider import create_provider

    return create_provider()


def create_prime_agent_package() -> InstalledCapabilityPackage:
    """Load the selected Prime package only after source selection."""

    from asterion.capabilities.prime_agent import create_prime_agent_package as create

    return create()


__all__ = (
    "CONTROLLED_CODE_PACKAGE",
    "CONTROLLED_CODE_SOURCE_ID",
    "DCI_PACKAGE",
    "PRIME_AGENT_PACKAGE",
    "builtin_capability_registrations",
    "create_controlled_code_package",
    "create_dci_package",
    "create_prime_agent_package",
)
