"""Stable third-party capability package SDK."""

from asterion.capabilities.catalog import CapabilityRef
from asterion.capabilities.execution import (
    CapabilityImplementationBinding,
    CapabilityExecutionError,
    CapabilityExecutionResult,
    CapabilityInvocation,
)
from asterion.capability_packages.model import (
    BenchmarkTaskBinding,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.payload import open_portable_payload
from asterion.capability_packages.protocol import CapabilityPackageRef
from asterion.capability_sdk.author import copy_portable_payload
from asterion.capability_sdk.conformance import run_capability_conformance
from asterion.capability_sdk.provider import (
    CapabilityPackageProvider,
    HostServices,
)
from asterion.benchmarks.model import BenchmarkTaskInvocation, BenchmarkTaskRequest
from asterion.runtime.host import CancellationSignal


__all__ = [
    "CapabilityRef",
    "CapabilityPackageRef",
    "CapabilityInvocation",
    "CapabilityExecutionResult",
    "CapabilityExecutionError",
    "CapabilityImplementationBinding",
    "CapabilityPackageProvider",
    "InstalledCapabilityPackage",
    "BenchmarkTaskBinding",
    "BenchmarkTaskInvocation",
    "BenchmarkTaskRequest",
    "CancellationSignal",
    "HostServices",
    "open_portable_payload",
    "copy_portable_payload",
    "run_capability_conformance",
]
