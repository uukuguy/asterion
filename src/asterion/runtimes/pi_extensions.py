"""Pi-named re-exports of the neutral pinned-extension machinery.

The pinned-resource lease machinery lives in ``asterion.runtime.pinned_extension``
under neutral names. This module retains the historical Pi-facing names for the
runtime-adjacent layers that still reference them directly (``runtime.defaults``,
the ``asterion.agents.prime`` session/execution/backend kernels, and DCI).
"""

from __future__ import annotations

from asterion.runtime.pinned_extension import (
    ExtensionBinding as PiExtensionBinding,
    ExtensionDependencies as PiExtensionDependencies,
    ExtensionLease as PiExtensionLease,
    extension_loader_path as pi_extension_loader_path,
)

__all__ = (
    "PiExtensionBinding",
    "PiExtensionDependencies",
    "PiExtensionLease",
    "pi_extension_loader_path",
)
