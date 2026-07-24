"""Host-service protocol contracts."""

from asterion.services.registry import (
    HOST_SERVICE_ENTRY_POINT_GROUP,
    HostServiceFactory,
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
    HostServiceFactoryRegistry,
    HostServiceRegistryError,
    parse_host_service_options,
)

__all__ = [
    "HOST_SERVICE_ENTRY_POINT_GROUP",
    "HostServiceFactory",
    "HostServiceFactoryBinding",
    "HostServiceFactoryContext",
    "HostServiceFactoryRegistry",
    "HostServiceRegistryError",
    "parse_host_service_options",
]
