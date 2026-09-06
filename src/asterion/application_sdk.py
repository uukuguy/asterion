"""Stable public contracts for independently installed applications."""

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL as APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication as InstalledApplication,
    InstalledApplicationProvider as InstalledApplicationProvider,
)
from asterion.capability_packages.protocol import CapabilityPackageRef as CapabilityPackageRef
from asterion.runtime.factory import (
    RuntimeFactoryBinding as RuntimeFactoryBinding,
    RuntimeFactoryContext as RuntimeFactoryContext,
    RuntimeFactoryError as RuntimeFactoryError,
)
from asterion.runtime.host import (
    AgentRuntimeClient as AgentRuntimeClient,
    CancellationSignal as CancellationSignal,
    RunEvent as RunEvent,
    RunRequest as RunRequest,
    RuntimeManifest as RuntimeManifest,
    parse_event_stream as parse_event_stream,
)


__all__ = (
    "APPLICATION_PROVIDER_PROTOCOL",
    "InstalledApplication",
    "InstalledApplicationProvider",
    "CapabilityPackageRef",
    "RuntimeFactoryBinding",
    "RuntimeFactoryContext",
    "AgentRuntimeClient",
    "CancellationSignal",
    "RunEvent",
    "RunRequest",
    "RuntimeManifest",
    "parse_event_stream",
    "RuntimeFactoryError",
)
