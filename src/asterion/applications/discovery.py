"""Metadata-only listing and selected-only installed provider loading."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata
from typing import cast

from asterion.applications.provider import (
    ApplicationProviderError,
    InstalledApplicationProvider,
    validate_installed_provider_metadata,
)
from asterion.applications.selection import (
    ApplicationSelector,
    parse_application_selector,
)


APPLICATION_ENTRY_POINT_GROUP = "asterion.applications"
APPLICATION_INDEX_ENTRY_POINT_GROUP = "asterion.application_index"
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
            provider_id=str(getattr(entry, "name")),
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
        raise ApplicationProviderError(
            "installed application provider identity is invalid"
        )
    matches = [
        entry
        for entry in _entry_points(entry_points)
        if getattr(entry, "name", None) == provider_id
    ]
    if len(matches) != 1:
        raise ApplicationProviderError(
            "installed application provider selection is invalid"
        )
    try:
        factory = getattr(matches[0], "load")()
        if not callable(factory):
            raise TypeError("provider entry point is not callable")
        value = factory()
    except Exception:
        raise ApplicationProviderError(
            "installed application provider failed to load"
        ) from None
    return validate_installed_provider_metadata(
        cast(InstalledApplicationProvider, value), selected_id=provider_id
    )


def select_application_provider_id(
    application: object,
    *,
    application_entry_points: Iterable[object] | None = None,
    provider_entry_points: Iterable[object] | None = None,
) -> str:
    """Select one provider for an exact application without importing code."""

    selector = _application_selector(application)
    index_name = f"{selector.application_id}__{selector.version}"
    index_matches = [
        entry
        for entry in _group_entry_points(
            APPLICATION_INDEX_ENTRY_POINT_GROUP, application_entry_points
        )
        if getattr(entry, "name", None) == index_name
    ]
    if len(index_matches) != 1:
        raise ApplicationProviderError(
            "installed application index selection is invalid"
        )
    target = getattr(index_matches[0], "value", None)
    if not isinstance(target, str) or not target:
        raise ApplicationProviderError(
            "installed application index selection is invalid"
        )
    provider_matches = [
        entry
        for entry in _group_entry_points(
            APPLICATION_ENTRY_POINT_GROUP, provider_entry_points
        )
        if getattr(entry, "value", None) == target
        and _valid_provider_id(getattr(entry, "name", None))
    ]
    if len(provider_matches) != 1:
        raise ApplicationProviderError(
            "installed application index selection is invalid"
        )
    return str(getattr(provider_matches[0], "name"))


def _entry_points(values: Iterable[object] | None) -> tuple[object, ...]:
    return _group_entry_points(APPLICATION_ENTRY_POINT_GROUP, values)


def _group_entry_points(
    group: str, values: Iterable[object] | None
) -> tuple[object, ...]:
    if values is None:
        return tuple(metadata.entry_points(group=group))
    return tuple(
        entry for entry in values if getattr(entry, "group", None) == group
    )


def _application_selector(value: object) -> ApplicationSelector:
    try:
        if isinstance(value, str):
            return parse_application_selector(value)
        application_id = getattr(value, "application_id")
        version = getattr(value, "version")
        if not isinstance(application_id, str) or not isinstance(version, str):
            raise TypeError
        return parse_application_selector(f"{application_id}@{version}")
    except Exception:
        raise ApplicationProviderError(
            "installed application index selection is invalid"
        ) from None


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
