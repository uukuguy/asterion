"""Compatibility exports for first-party capability-package registrations."""

from __future__ import annotations

from asterion.applications.first_party_packages import (
    CONTROLLED_CODE_PACKAGE,
    CONTROLLED_CODE_SOURCE_ID,
    DCI_PACKAGE,
    builtin_capability_registrations as builtin_capability_sources,
    create_controlled_code_package,
    create_dci_package,
)
from asterion.capability_packages.sources.builtin import BuiltinCapabilityRegistration


__all__ = (
    "CONTROLLED_CODE_PACKAGE",
    "CONTROLLED_CODE_SOURCE_ID",
    "DCI_PACKAGE",
    "BuiltinCapabilityRegistration",
    "builtin_capability_sources",
    "create_controlled_code_package",
    "create_dci_package",
)
