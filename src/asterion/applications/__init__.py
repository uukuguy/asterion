"""Installed Asterion application provider contracts."""

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
    validate_installed_provider,
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
    "InstalledApplicationProvider",
    "InstalledProviderMetadata",
    "list_application_providers",
    "load_application_provider",
    "validate_installed_provider",
)
