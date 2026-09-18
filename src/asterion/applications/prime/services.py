"""Narrow operator-facing host services for native Asterion Prime applications.

Currently exports the ``prime.continuity-store`` host service factory, which
wraps a :class:`FilePrimeSessionStore` in a public-safe async-context-manager
shape. The store's private path is never exposed through this surface; only
the on-disk identity's digests, the recoverable checkpoint, and the current
sealed generation are returned.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    PrimeRecoveredCheckpoint,
)
from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
    HostServiceRegistryError,
)


_OPTION_ROOT = "root"


class ContinuityStoreServiceError(HostServiceRegistryError):
    """Raised when ``prime.continuity-store`` cannot be opened safely."""


@dataclass(frozen=True)
class _PublicContinuityIdentity:
    """Content-safe identity projection of a bound continuity store.

    Carries only digests, not the private root path. ``generation`` is the
    store's bound generation; ``prior_generation`` is the generation it was
    continued from, if any.
    """

    provider_id: str
    application_id: str
    runtime_id: str
    continuation_id: str
    generation: int
    prior_generation: int | None
    worker_identity_sha256: str
    continuation_root_sha256: str
    ceilings_sha256: str

    @property
    def is_continued(self) -> bool:
        return self.prior_generation is not None


class ContinuityStoreHostService:
    """Public-safe view of a bound :class:`FilePrimeSessionStore`.

    Holds a reference to the live store, redacts its private-root identity,
    and offers the operator the narrow surface it needs: ask for the public
    identity, recover the latest sealed checkpoint, and read the current
    generation number.
    """

    def __init__(self, store: FilePrimeSessionStore) -> None:
        self._store = store

    @property
    def public_identity(self) -> _PublicContinuityIdentity:
        identity: PrimeBackendIdentity = self._store.identity
        continued_from = self._store.continued_from
        return _PublicContinuityIdentity(
            provider_id=identity.provider_id,
            application_id=identity.application_id,
            runtime_id=identity.runtime_id,
            continuation_id=identity.continuation_id,
            generation=identity.generation,
            prior_generation=(
                None if continued_from is None else continued_from.generation
            ),
            worker_identity_sha256=identity.worker_identity_sha256,
            continuation_root_sha256=identity.private_root_identity,
            ceilings_sha256=identity.ceilings_sha256,
        )

    @property
    def current_generation(self) -> int:
        return self._store.identity.generation

    @property
    def highest_sealed_generation(self) -> int:
        return self._store.highest_sealed_generation

    def recover_checkpoint(self) -> PrimeRecoveredCheckpoint | None:
        return self._store.recover_checkpoint()


def _validate_options(context: HostServiceFactoryContext) -> Path:
    if (
        context.provider_id != "prime-applications"
        or context.application_id != "prime.long-session-continuity"
        or context.application_version != "1.0.0"
        or context.capability_id != "prime.continuity-store"
    ):
        raise ContinuityStoreServiceError(
            "continuity store context identity is invalid"
        )
    if set(context.options) != {_OPTION_ROOT}:
        raise ContinuityStoreServiceError("continuity store options are invalid")
    raw_root = context.options[_OPTION_ROOT]
    if type(raw_root) is not str or not raw_root:
        raise ContinuityStoreServiceError("continuity store root is invalid")
    root = Path(raw_root)
    if (
        not root.is_absolute()
        or str(root) != raw_root
        or any(component in {"", ".", ".."} for component in root.parts[1:])
    ):
        raise ContinuityStoreServiceError("continuity store root is invalid")
    return root


def create_continuity_store_host_service() -> HostServiceFactoryBinding:
    """Return the exact factory binding for ``prime.continuity-store``."""

    return HostServiceFactoryBinding(
        capability_id="prime.continuity-store",
        option_names=(_OPTION_ROOT,),
        factory=_open_continuity_store_service,
    )


@asynccontextmanager
async def _open_continuity_store_service(context: HostServiceFactoryContext):
    root = _validate_options(context)
    store = FilePrimeSessionStore(root, _initial_identity(root))
    try:
        yield ContinuityStoreHostService(store)
    finally:
        store.close()


def _initial_identity(root: Path) -> PrimeBackendIdentity:
    """Construct a generation-1 identity bound to the supplied root.

    Used by the host service's first-open path: the store's ``__init__``
    refuses to bind against a different identity, so the operator's identity
    (provided through the runner) drives this. Here we only need a valid
    identity that matches the root; the operator will override it through
    ``open_continued`` after the witness commits.
    """

    from asterion.agents.prime.store import private_root_identity

    return PrimeBackendIdentity(
        session_id="prime.continuity-store",
        generation=1,
        provider_id="prime-applications",
        application_id="prime.long-session-continuity",
        application_version="1.0.0",
        runtime_id="asterion.prime",
        pi_command_sha256=_ZERO_SHA256,
        extension_binding_fingerprint=_ZERO_SHA256,
        worker_identity_sha256=_ZERO_SHA256,
        continuation_id="continuity-initial",
        private_root_identity=private_root_identity(root),
        ceilings_sha256=_ZERO_SHA256,
    )


# A 64-character zero digest is the canonical "no host has run yet" marker.
_ZERO_SHA256 = "0" * 64


__all__ = (
    "ContinuityStoreHostService",
    "ContinuityStoreServiceError",
    "create_continuity_store_host_service",
)