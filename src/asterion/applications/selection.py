"""Exact selection of applications within one validated provider."""

from __future__ import annotations

from dataclasses import dataclass

from asterion.applications.provider import (
    IDENTIFIER,
    SEMANTIC_VERSION,
    ApplicationProviderError,
    InstalledApplication,
    InstalledApplicationProvider,
)


@dataclass(frozen=True)
class ApplicationSelector:
    application_id: str
    version: str


def parse_application_selector(value: str) -> ApplicationSelector:
    """Parse one canonical exact ``application_id@version`` selector."""

    if not isinstance(value, str) or value.strip() != value or value.count("@") != 1:
        raise ApplicationProviderError("installed application selector is invalid")
    application_id, version = value.split("@", 1)
    if (
        IDENTIFIER.fullmatch(application_id) is None
        or SEMANTIC_VERSION.fullmatch(version) is None
    ):
        raise ApplicationProviderError("installed application selector is invalid")
    return ApplicationSelector(application_id=application_id, version=version)


def select_installed_application(
    provider: InstalledApplicationProvider,
    selector: ApplicationSelector,
) -> InstalledApplication:
    """Return the unique application matching *selector*."""

    if not isinstance(provider, InstalledApplicationProvider) or not isinstance(
        selector, ApplicationSelector
    ):
        raise ApplicationProviderError("installed application selection is invalid")
    matches = tuple(
        application
        for application in provider.applications
        if application.application_id == selector.application_id
        and application.version == selector.version
    )
    if len(matches) != 1:
        raise ApplicationProviderError("installed application selection is invalid")
    return matches[0]
