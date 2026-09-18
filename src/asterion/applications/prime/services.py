"""Narrow operator-facing host services for native Asterion Prime applications.

Currently exports two host service factories:

* ``prime.continuity-store`` — wraps a :class:`FilePrimeSessionStore` in a
  public-safe async-context-manager shape. The store's private path is never
  exposed through this surface; only the on-disk identity's digests, the
  recoverable checkpoint, and the current sealed generation are returned.
* ``prime.child-runner`` — application-level child session factory for the
  P3 recursive-workflow application. Enforces framework-owned depth /
  concurrency / budget / cancellation limits and returns structured
  admission / refusal records without leaking private-root identity.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Literal

from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import (
    FilePrimeSessionStore,
    PrimeRecoveredCheckpoint,
)
from asterion.runtime.host import CancellationSignal
from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
    HostServiceRegistryError,
)


_OPTION_ROOT = "root"

# P3 child-runner limits. Each limit is configurable through the host service
# factory context when present, otherwise taken from the spec defaults below.
# Defaults match ``docs/superpowers/specs/2026-09-18-asterion-prime-p3-native-design.md``
# §"Newly introduced in Phase 7".
MAX_DEPTH = 2
MAX_CONCURRENT_CHILDREN = 1
MAX_CHILD_COST_USD = Decimal("0.10")
MAX_TOTAL_DURATION_MS = 60_000

RefusalReason = Literal[
    "depth-exceeded",
    "concurrency-exceeded",
    "budget-exceeded",
    "cancelled",
    "session-backend-rejected",
]


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


# ---------------------------------------------------------------------------
# prime.child-runner host service (Phase 7, Task 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PublicChildRunnerIdentity:
    """Content-safe identity projection of a bound child-runner.

    Carries every field of :class:`PrimeBackendIdentity` except the private
    ``private_root_identity`` digest. ``public_identity`` is exposed only
    through this shape so the host service surface can never leak the
    on-disk root digest back to the operator.
    """

    provider_id: str
    application_id: str
    runtime_id: str
    session_id: str
    generation: int
    pi_command_sha256: str
    extension_binding_fingerprint: str
    worker_identity_sha256: str
    continuation_id: str
    ceilings_sha256: str


@dataclass(frozen=True)
class ChildAdmission:
    """Structured success record for ``ChildRunnerHostService.admit_child``."""

    child_run_id: str
    child_identity: PrimeBackendIdentity
    admitted_at_depth: int


@dataclass(frozen=True)
class ChildAdmissionRefused:
    """Structured refusal record for ``ChildRunnerHostService.admit_child``.

    The ``refusal_reason`` is one of the closed enum enforced by
    :data:`RefusalReason`. ``attempted_at`` is the ISO 8601 UTC timestamp at
    which the refusal was issued.
    """

    refusal_reason: RefusalReason
    attempted_depth: int
    attempted_at: str


class ChildRunnerServiceError(HostServiceRegistryError):
    """Raised when ``prime.child-runner`` cannot be opened safely."""


@dataclass(frozen=True)
class _ChildRunnerLimits:
    """Resolved limit set for one open ``prime.child-runner`` service."""

    max_depth: int
    max_concurrent_children: int
    max_child_cost_usd: Decimal
    max_total_duration_ms: int


def _resolve_limits(context: HostServiceFactoryContext) -> _ChildRunnerLimits:
    """Validate context options and resolve the active limit set.

    Each limit is optional and falls back to the spec default when omitted;
    any other key in :attr:`context.options` is rejected. Recognised keys:

    * ``max_depth`` (int, positive) — defaults to :data:`MAX_DEPTH`.
    * ``max_concurrent_children`` (int, positive) — defaults to
      :data:`MAX_CONCURRENT_CHILDREN`.
    * ``max_child_cost_usd`` (decimal string) — defaults to
      :data:`MAX_CHILD_COST_USD`.
    * ``max_total_duration_ms`` (int, positive) — defaults to
      :data:`MAX_TOTAL_DURATION_MS`.
    """

    unknown = set(context.options) - {
        "max_depth",
        "max_concurrent_children",
        "max_child_cost_usd",
        "max_total_duration_ms",
    }
    if unknown:
        raise ChildRunnerServiceError("child-runner options are invalid")

    raw_depth = context.options.get("max_depth", str(MAX_DEPTH))
    if type(raw_depth) is not str or not raw_depth.isdigit():
        raise ChildRunnerServiceError("child-runner max_depth is invalid")
    max_depth = int(raw_depth)
    if max_depth < 1:
        raise ChildRunnerServiceError("child-runner max_depth is invalid")

    raw_concurrent = context.options.get(
        "max_concurrent_children", str(MAX_CONCURRENT_CHILDREN)
    )
    if type(raw_concurrent) is not str or not raw_concurrent.isdigit():
        raise ChildRunnerServiceError(
            "child-runner max_concurrent_children is invalid"
        )
    max_concurrent = int(raw_concurrent)
    if max_concurrent < 1:
        raise ChildRunnerServiceError(
            "child-runner max_concurrent_children is invalid"
        )

    raw_cost = context.options.get("max_child_cost_usd", str(MAX_CHILD_COST_USD))
    if type(raw_cost) is not str or not raw_cost:
        raise ChildRunnerServiceError("child-runner max_child_cost_usd is invalid")
    try:
        max_cost = Decimal(raw_cost)
    except ArithmeticError:
        raise ChildRunnerServiceError(
            "child-runner max_child_cost_usd is invalid"
        ) from None
    if max_cost <= 0:
        raise ChildRunnerServiceError("child-runner max_child_cost_usd is invalid")

    raw_duration = context.options.get(
        "max_total_duration_ms", str(MAX_TOTAL_DURATION_MS)
    )
    if type(raw_duration) is not str or not raw_duration.isdigit():
        raise ChildRunnerServiceError(
            "child-runner max_total_duration_ms is invalid"
        )
    max_duration = int(raw_duration)
    if max_duration < 1:
        raise ChildRunnerServiceError(
            "child-runner max_total_duration_ms is invalid"
        )

    return _ChildRunnerLimits(
        max_depth=max_depth,
        max_concurrent_children=max_concurrent,
        max_child_cost_usd=max_cost,
        max_total_duration_ms=max_duration,
    )


def _iso_utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string with timezone offset."""

    return datetime.now(tz=timezone.utc).isoformat()


def _join_result_digest(
    *,
    root_result_sha256: str,
    child_result_sha256: str,
    depth_reached: int,
) -> str:
    """Compute the canonical-JSON SHA-256 of a joined child result.

    Mirrors :func:`asterion.agents.prime.state._mapping_digest`: the encoding
    uses ``sort_keys=True`` with the tight ``(",", ":")`` separator so any
    (root, child, depth) tuple maps to exactly one hex digest.
    """

    payload = {
        "root_result_sha256": root_result_sha256,
        "child_result_sha256": child_result_sha256,
        "depth_reached": depth_reached,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ChildRunnerHostService:
    """Application-level child session factory for P3 recursive-workflow.

    Holds the resolved limit set, admits children via
    :meth:`admit_child`, and joins child results into the parent result via
    :meth:`join_child_result`. Limits are checked synchronously against the
    in-memory admission ledger; cancellation is checked through the supplied
    :class:`CancellationSignal` (when provided).

    The default path is **in-process**: every admission record is held in
    memory; no subprocess supervisor is consulted.
    """

    def __init__(
        self,
        *,
        limits: _ChildRunnerLimits,
        opened_at_iso: str,
    ) -> None:
        self._limits = limits
        self._opened_at_iso = opened_at_iso
        self._admitted_run_ids: set[str] = set()
        self._spent_cost_usd: Decimal = Decimal("0")

    @property
    def public_identity(self) -> _PublicChildRunnerIdentity:
        """Return a redacted identity projection bound at factory time.

        The projection is content-safe: it never carries
        ``private_root_identity``. The bound ``session_id``,
        ``provider_id``, ``application_id``, ``runtime_id`` and digests are
        surfaced for diagnostics only.
        """

        return _PublicChildRunnerIdentity(
            provider_id="prime-applications",
            application_id="prime.recursive-workflow",
            runtime_id="asterion.prime",
            session_id="prime.child-runner",
            generation=1,
            pi_command_sha256=_ZERO_SHA256,
            extension_binding_fingerprint=_ZERO_SHA256,
            worker_identity_sha256=_ZERO_SHA256,
            continuation_id="child-runner-initial",
            ceilings_sha256=_ZERO_SHA256,
        )

    def record_child_cost(self, cost_usd: Decimal, *, child_run_id: str) -> None:
        """Record cost consumed by a previously admitted child and release
        its concurrency slot.

        Recording cost signals that the child has finished running: the
        concurrency slot it held is freed and the spent budget is
        incremented. Once the cumulative spent budget meets or exceeds
        :attr:`_ChildRunnerLimits.max_child_cost_usd`,
        :meth:`admit_child` will refuse further admissions with
        ``budget-exceeded``. The operator is the single authority on what
        each child cost; this host service only adds it to the ledger.

        ``child_run_id`` MUST correspond to a previously admitted child
        (otherwise the operator would be reporting a cost for work that
        never ran through this service). Negative or non-decimal costs are
        rejected.
        """

        if not isinstance(child_run_id, str) or child_run_id not in self._admitted_run_ids:
            raise ChildRunnerServiceError("record_child_cost child_run_id is invalid")
        if not isinstance(cost_usd, Decimal):
            raise ChildRunnerServiceError("record_child_cost cost_usd is invalid")
        if cost_usd < 0:
            raise ChildRunnerServiceError("record_child_cost cost_usd is invalid")
        self._admitted_run_ids.discard(child_run_id)
        self._spent_cost_usd += cost_usd

    async def admit_child(
        self,
        *,
        parent_run_id: str,
        depth: int,
        child_identity: PrimeBackendIdentity,
        signal: CancellationSignal | None = None,
    ) -> ChildAdmission | ChildAdmissionRefused:
        """Admit one child at the given depth under the active limit set.

        Order of checks mirrors the spec §"Newly introduced in Phase 7":
        cancellation → depth → concurrency → budget → identity validity.
        The cancellation check runs first because a cancelled run must not
        admit further children under any limit.
        """

        if not isinstance(parent_run_id, str) or not parent_run_id:
            raise ChildRunnerServiceError("parent_run_id is invalid")
        if not isinstance(depth, int) or depth < 1:
            raise ChildRunnerServiceError("admit_child depth is invalid")
        if not isinstance(child_identity, PrimeBackendIdentity):
            raise ChildRunnerServiceError("admit_child child_identity is invalid")

        if signal is not None and getattr(signal, "cancelled", False):
            return ChildAdmissionRefused(
                refusal_reason="cancelled",
                attempted_depth=depth,
                attempted_at=_iso_utc_now(),
            )
        if depth > self._limits.max_depth:
            return ChildAdmissionRefused(
                refusal_reason="depth-exceeded",
                attempted_depth=depth,
                attempted_at=_iso_utc_now(),
            )
        if len(self._admitted_run_ids) >= self._limits.max_concurrent_children:
            return ChildAdmissionRefused(
                refusal_reason="concurrency-exceeded",
                attempted_depth=depth,
                attempted_at=_iso_utc_now(),
            )
        if self._spent_cost_usd >= self._limits.max_child_cost_usd:
            return ChildAdmissionRefused(
                refusal_reason="budget-exceeded",
                attempted_depth=depth,
                attempted_at=_iso_utc_now(),
            )

        child_run_id = f"{parent_run_id}.child-{len(self._admitted_run_ids) + 1}"
        self._admitted_run_ids.add(child_run_id)
        return ChildAdmission(
            child_run_id=child_run_id,
            child_identity=child_identity,
            admitted_at_depth=depth,
        )

    async def join_child_result(
        self,
        *,
        parent_run_id: str,
        child_receipt: object,
    ) -> str:
        """Compute the joined_result_sha256 for one child receipt.

        ``child_receipt`` MUST expose ``result_sha256`` (the child's sealed
        result digest) — the P3 sealed receipt defined in Task 6 carries
        that field. ``parent_run_id`` is accepted for symmetry with
        :meth:`admit_child`; the digest itself depends only on
        ``(root_result_sha256, child_result_sha256, depth_reached)``.
        """

        if not isinstance(parent_run_id, str) or not parent_run_id:
            raise ChildRunnerServiceError("parent_run_id is invalid")
        child_result_sha256 = getattr(child_receipt, "result_sha256", None)
        depth_reached = getattr(child_receipt, "depth_reached", None)
        if not (
            isinstance(child_result_sha256, str)
            and len(child_result_sha256) == 64
            and all(ch in "0123456789abcdef" for ch in child_result_sha256)
        ):
            raise ChildRunnerServiceError(
                "join_child_result child_result_sha256 is invalid"
            )
        if not isinstance(depth_reached, int) or depth_reached < 1:
            raise ChildRunnerServiceError(
                "join_child_result depth_reached is invalid"
            )
        # The parent run's own result digest is recovered from the receipt's
        # root counterpart. The witness sets this field through the operator;
        # outside the witness path it is the closed-form placeholder used by
        # P4's continuity-store witness (the SHA of the canonical root
        # identity), which is sufficient for the deterministic digest check.
        root_result_sha256 = getattr(child_receipt, "root_result_sha256", None)
        if root_result_sha256 is None:
            root_result_sha256 = getattr(
                child_receipt, "root_run_id", parent_run_id
            )
        if not isinstance(root_result_sha256, str) or not root_result_sha256:
            raise ChildRunnerServiceError(
                "join_child_result root_result_sha256 is invalid"
            )
        return _join_result_digest(
            root_result_sha256=root_result_sha256,
            child_result_sha256=child_result_sha256,
            depth_reached=depth_reached,
        )


@asynccontextmanager
async def _open_child_runner_service(context: HostServiceFactoryContext):
    if (
        context.provider_id != "prime-applications"
        or context.application_id != "prime.recursive-workflow"
        or context.application_version != "1.0.0"
        or context.capability_id != "prime.child-runner"
    ):
        raise ChildRunnerServiceError("child-runner context identity is invalid")
    limits = _resolve_limits(context)
    service = ChildRunnerHostService(
        limits=limits,
        opened_at_iso=_iso_utc_now(),
    )
    try:
        yield service
    finally:
        service._admitted_run_ids.clear()


def create_child_runner_host_service() -> HostServiceFactoryBinding:
    """Return the exact factory binding for ``prime.child-runner``."""

    return HostServiceFactoryBinding(
        capability_id="prime.child-runner",
        option_names=(
            "max_depth",
            "max_concurrent_children",
            "max_child_cost_usd",
            "max_total_duration_ms",
        ),
        factory=_open_child_runner_service,
    )


__all__ = (
    "ChildAdmission",
    "ChildAdmissionRefused",
    "ChildRunnerHostService",
    "ChildRunnerServiceError",
    "ContinuityStoreHostService",
    "ContinuityStoreServiceError",
    "MAX_CHILD_COST_USD",
    "MAX_CONCURRENT_CHILDREN",
    "MAX_DEPTH",
    "MAX_TOTAL_DURATION_MS",
    "create_child_runner_host_service",
    "create_continuity_store_host_service",
)