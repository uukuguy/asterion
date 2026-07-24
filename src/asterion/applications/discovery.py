"""Metadata-only listing and selected-only installed provider loading."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata

from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplicationProvider,
    validate_installed_provider,
)


APPLICATION_ENTRY_POINT_GROUP = "asterion.applications"
PROVIDER_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


@dataclass(frozen=True, order=True)
class InstalledProviderMetadata:
    provider_id: str
    distribution_name: str
    distribution_version: str


def list_application_providers(
    *, entry_points: Iterable[object] | None = None
) -> tuple[InstalledProviderMetadata, ...]:
    """List installed provider metadata without importing provider code."""

    entries = _entry_points(entry_points)
    values = {
        InstalledProviderMetadata(
            provider_id=str(entry.name),
            distribution_name=_distribution_name(entry),
            distribution_version=_distribution_version(entry),
        )
        for entry in entries
        if _valid_provider_id(getattr(entry, "name", None))
    }
    return tuple(sorted(values))


def load_application_provider(
    provider_id: str, *, entry_points: Iterable[object] | None = None
) -> InstalledApplicationProvider:
    """Load and validate only one explicitly selected provider."""

    if not _valid_provider_id(provider_id):
        raise ApplicationProviderError("installed application provider identity is invalid")
    matches = [
        entry for entry in _entry_points(entry_points) if entry.name == provider_id
    ]
    if len(matches) != 1:
        raise ApplicationProviderError("installed application provider selection is invalid")
    try:
        factory = matches[0].load()
        if not callable(factory):
            raise TypeError("provider entry point is not callable")
        value = factory()
    except Exception:
        raise ApplicationProviderError(
            "installed application provider failed to load"
        ) from None
    return validate_installed_provider(value, selected_id=provider_id)


def _entry_points(values: Iterable[object] | None) -> tuple[object, ...]:
    if values is None:
        return tuple(metadata.entry_points(group=APPLICATION_ENTRY_POINT_GROUP))
    return tuple(
        entry
        for entry in values
        if getattr(entry, "group", None) == APPLICATION_ENTRY_POINT_GROUP
    )


def _distribution_name(entry: object) -> str:
    distribution = getattr(entry, "dist", None)
    name = getattr(distribution, "name", None)
    if isinstance(name, str) and name:
        return name
    distribution_metadata = getattr(distribution, "metadata", None)
    if distribution_metadata is not None:
        value = distribution_metadata.get("Name")
        if isinstance(value, str) and value:
            return value
    return "unknown"


def _distribution_version(entry: object) -> str:
    value = getattr(getattr(entry, "dist", None), "version", None)
    return value if isinstance(value, str) and value else "unknown"


def _valid_provider_id(value: object) -> bool:
    return isinstance(value, str) and PROVIDER_ID.fullmatch(value) is not None
