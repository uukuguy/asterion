"""Explicit built-in capability-package registrations."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_packages.sources.builtin import (
    BuiltinCapabilityRegistration,
)


_CONTROLLED_CODE_REF = CapabilityPackageRef("controlled-code", "1.0.0")
_CONTROLLED_CODE_SOURCE_ID = "builtin:controlled-code@1.0.0"


def builtin_capability_sources() -> tuple[BuiltinCapabilityRegistration, ...]:
    """Return the immutable, non-scanned table of built-in package sources."""

    package_root = Path(str(resources.files("asterion"))).resolve()
    return (
        BuiltinCapabilityRegistration(
            _CONTROLLED_CODE_REF,
            package_root / "capabilities/controlled_code/payload",
            create_controlled_code_package,
        ),
    )


def create_controlled_code_package() -> InstalledCapabilityPackage:
    """Return the selected built-in controlled-code package binding."""

    from asterion.capabilities.controlled_code import (
        controlled_code_bindings,
    )

    payload_root = builtin_capability_sources()[0].payload_root
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=_CONTROLLED_CODE_REF,
        payload_sha256=payload.payload_sha256,
        source_id=_CONTROLLED_CODE_SOURCE_ID,
        source_kind="builtin",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(),
        implementations=controlled_code_bindings(),
        benchmark_bindings=(),
    )
