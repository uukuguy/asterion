"""Explicit built-in capability-package registrations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from asterion.capability_packages.model import InstalledCapabilityPackage
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capabilities.execution import CapabilityImplementationBinding


CONTROLLED_CODE_PACKAGE = CapabilityPackageRef("controlled-code", "1.0.0")
CONTROLLED_CODE_SOURCE_ID = "controlled-code.builtin"


@dataclass(frozen=True, slots=True)
class BuiltinCapabilityRegistration:
    package_ref: CapabilityPackageRef
    payload_root: Path = field(repr=False)
    provider_factory: Callable[[], InstalledCapabilityPackage] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.package_ref) is not CapabilityPackageRef:
            raise ValueError("built-in capability registration is invalid")
        object.__setattr__(self, "payload_root", Path(self.payload_root))
        if not callable(self.provider_factory):
            raise ValueError("built-in capability registration is invalid")


def builtin_capability_sources() -> tuple[BuiltinCapabilityRegistration, ...]:
    """Return the immutable explicit table of first-party capability packages."""

    package_root = Path(str(resources.files("asterion.capabilities"))).resolve()
    return (
        BuiltinCapabilityRegistration(
            CONTROLLED_CODE_PACKAGE,
            package_root / "controlled_code/payload",
            create_controlled_code_package,
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
        benchmark_bindings=(),
    )


__all__ = (
    "BuiltinCapabilityRegistration",
    "builtin_capability_sources",
    "create_controlled_code_package",
)
