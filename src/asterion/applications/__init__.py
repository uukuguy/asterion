"""Installed Asterion application provider contracts."""

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledAssembly,
    InstalledApplicationProvider,
    compose_installed_provider,
    resolve_installed_provider,
    validate_installed_provider,
    validate_installed_provider_metadata,
)
from asterion.applications.discovery import (
    APPLICATION_ENTRY_POINT_GROUP,
    InstalledProviderMetadata,
    list_application_providers,
    load_application_provider,
)

__all__ = (
    "APPLICATION_PROVIDER_PROTOCOL",
    "APPLICATION_ENTRY_POINT_GROUP",
    "ApplicationProviderError",
    "InstalledApplication",
    "InstalledAssembly",
    "InstalledApplicationProvider",
    "InstalledProviderMetadata",
    "compose_installed_provider",
    "list_application_providers",
    "load_application_provider",
    "resolve_installed_provider",
    "validate_installed_provider",
    "validate_installed_provider_metadata",
)
