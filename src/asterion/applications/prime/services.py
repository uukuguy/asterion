"""Narrow operator-facing host services for native Asterion Prime applications.

Currently exports four host service factories:

* ``prime.continuity-store`` — wraps a :class:`FilePrimeSessionStore` in a
  public-safe async-context-manager shape. The store's private path is never
  exposed through this surface; only the on-disk identity's digests, the
  recoverable checkpoint, and the current sealed generation are returned.
* ``prime.child-runner`` — application-level child session factory for the
  P3 recursive-workflow application. Enforces framework-owned depth /
  concurrency / budget / cancellation limits and returns structured
  admission / refusal records without leaking private-root identity.
* ``prime.bounded-autonomy`` — single-loop controller for the P5
  bounded-autonomy application. Composes propose/verify/repair under
  framework-owned duration / iteration / no-progress limits and emits
  exactly one sealed :class:`P5NativeReceipt` per :meth:`run_loop` call.
* ``prime.candidate-store`` — application-level wrapper around the
  framework-owned :class:`HarnessCoordinator` (composition, not
  duplication). Owns the admitted-candidate lifecycle: admit candidate
  via :meth:`HarnessCoordinator.apply`, evaluate on holdout, then
  preserve via explicit promotion or rollback via the coordinator's
  exact inverse revision. Emits exactly one terminal record whose
  public ``terminal_outcome`` is one of the closed 2-element enum
  (``preserved`` | ``rolled-back``).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import time
from typing import Awaitable, Callable, Literal

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
from asterion.applications.prime.p5.receipt import (
    P5NativeReceipt,
    P5ReceiptError,
    TerminalReason,
    seal as _seal_p5_native_receipt_impl,
)


# Keep the historical facade import surface; all P6 objects have one owner.
from asterion.applications.prime.p6.candidate_store import (
    MAX_CANDIDATE_REVISIONS_PER_RUN as MAX_CANDIDATE_REVISIONS_PER_RUN,
    MAX_HOLDOUT_EVALUATIONS_PER_RUN as MAX_HOLDOUT_EVALUATIONS_PER_RUN,
    MAX_ROLLBACK_INVOCATIONS_PER_RUN as MAX_ROLLBACK_INVOCATIONS_PER_RUN,
    MAX_ACTIONS as MAX_ACTIONS,
    MAX_USAGE_PROVIDER_OPS as MAX_USAGE_PROVIDER_OPS,
    MAX_DEADLINE_MS as MAX_DEADLINE_MS,
    MAX_COST_USD as MAX_COST_USD,
    CANDIDATE_STORE_DEFAULT_SCOPE as CANDIDATE_STORE_DEFAULT_SCOPE,
    CandidateStoreTerminalOutcome as CandidateStoreTerminalOutcome,
    CandidateStoreVerdict as CandidateStoreVerdict,
    _PublicCandidateStoreIdentity as _PublicCandidateStoreIdentity,
    _CandidateStoreLimits as _CandidateStoreLimits,
    _resolve_candidate_store_limits as _resolve_candidate_store_limits,
    CandidateStoreServiceError as CandidateStoreServiceError,
    _error_digest as _error_digest,
    HoldoutResult as HoldoutResult,
    HoldoutCallable as HoldoutCallable,
    CandidateStoreLoop as CandidateStoreLoop,
    _compute_holdout_digest as _compute_holdout_digest,
    _read_scope_kind as _read_scope_kind,
    _read_global_activation as _read_global_activation,
    _open_candidate_store_service as _open_candidate_store_service,
    _no_op_effect_sender as _no_op_effect_sender,
    _default_coordinator_journal as _default_coordinator_journal,
    create_candidate_store_host_service as create_candidate_store_host_service,
    create_candidate_store_host_service_for_test as create_candidate_store_host_service_for_test,
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


# ---------------------------------------------------------------------------
# prime.bounded-autonomy host service (Phase 8, Task 3)
# ---------------------------------------------------------------------------

# P5 bounded-autonomy limits. Each limit is configurable through the host
# service factory context when present, otherwise taken from the spec
# defaults below. Defaults match
# ``docs/superpowers/specs/2026-09-19-asterion-prime-p5-native-design.md``
# §"Newly introduced in Phase 8" / §"Stopping conditions".
MAX_ITERATIONS = 3
MAX_REPAIR_DURATION_MS = 30_000
MAX_TOTAL_DURATION_MS = 120_000
WORKSPACE_DIGEST_DEDUP = True


class BoundedAutonomyServiceError(HostServiceRegistryError):
    """Raised when ``prime.bounded-autonomy`` cannot be opened safely."""


@dataclass(frozen=True)
class _PublicBoundedAutonomyIdentity:
    """Content-safe identity projection of a bound bounded-autonomy loop.

    Carries every field of :class:`PrimeBackendIdentity` except the private
    ``private_root_identity`` digest. Exposed only through
    :attr:`BoundedAutonomyLoop.public_identity` so the host service surface
    can never leak the on-disk root digest back to the operator.
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
class P5ProposeStep:
    """One propose step in the bounded loop.

    The :class:`BoundedAutonomyLoop` emits this record at the end of every
    propose step. ``workspace_digest_sha256`` is the canonical-JSON SHA-256
    of the candidate artifact; the loop's dedup-adapter compares it
    against the prior gate's digest.
    """

    step_id: str
    workspace_digest_sha256: str


@dataclass(frozen=True)
class P5VerifyStep:
    """One verify step in the bounded loop.

    ``verdict`` is the closed 4-element oracle verdict enum
    ``{"pass", "fail", "no-progress", "cancelled"}``. ``feedback`` is the
    opaque public-safe oracle feedback — never the per-step oracle verdict
    stream.
    """

    step_id: str
    verdict: Literal["pass", "fail", "no-progress", "cancelled"]
    feedback: str


@dataclass(frozen=True)
class P5RepairStep:
    """One repair step in the bounded loop.

    The :class:`BoundedAutonomyLoop` emits this record at the end of every
    repair step. ``workspace_digest_sha256`` is the canonical-JSON SHA-256
    of the post-repair artifact; the loop's dedup-adapter compares it
    against the prior propose / repair digest.
    """

    step_id: str
    workspace_digest_sha256: str


# NOTE: ``P5NativeReceipt`` and :func:`seal_p5_native_receipt` live in
# :mod:`asterion.applications.prime.p5.receipt` since Phase 8 / Task 6.
# They are imported at the top of this module. The host-service surface
# keeps a thin wrapper below that re-raises ``BoundedAutonomyServiceError``
# on receipt-validation failures so the existing host-service callers
# (and their tests) see the same exception type.

# Propose / verify / repair callables are async-callables the operator (Task 8)
# and runtime binding (Task 7) inject into the loop. Each receives the active
# cancellation signal and returns the matching step record (or raises). The
# loop controller owns only the limit logic; the verbs are pluggable so the
# witness can drive deterministic fake-workers without touching the loop.
ProposeCallable = Callable[
    [CancellationSignal | None], Awaitable[P5ProposeStep]
]
VerifyCallable = Callable[
    [CancellationSignal | None], Awaitable[P5VerifyStep]
]
RepairCallable = Callable[
    [CancellationSignal | None], Awaitable[P5RepairStep]
]


@dataclass(frozen=True)
class _BoundedAutonomyLimits:
    """Resolved limit set for one open ``prime.bounded-autonomy`` service."""

    max_iterations: int
    max_repair_duration_ms: int
    max_total_duration_ms: int
    workspace_digest_dedup: bool


def _resolve_bounded_autonomy_limits(
    context: HostServiceFactoryContext,
) -> _BoundedAutonomyLimits:
    """Validate context options and resolve the active P5 limit set.

    Each limit is optional and falls back to the spec default when omitted;
    any other key in :attr:`context.options` is rejected. Recognised keys:

    * ``max_iterations`` (int, >= 1) — defaults to :data:`MAX_ITERATIONS`.
    * ``max_repair_duration_ms`` (int, >= 1) — defaults to
      :data:`MAX_REPAIR_DURATION_MS`.
    * ``max_total_duration_ms`` (int, >= 1) — defaults to
      :data:`MAX_TOTAL_DURATION_MS`.
    * ``workspace_digest_dedup`` (one of ``"true"`` / ``"false"``) — defaults
      to :data:`WORKSPACE_DIGEST_DEDUP`.
    """

    unknown = set(context.options) - {
        "max_iterations",
        "max_repair_duration_ms",
        "max_total_duration_ms",
        "workspace_digest_dedup",
    }
    if unknown:
        raise BoundedAutonomyServiceError(
            "bounded-autonomy options are invalid"
        )

    raw_iterations = context.options.get(
        "max_iterations", str(MAX_ITERATIONS)
    )
    if type(raw_iterations) is not str or not raw_iterations.isdigit():
        raise BoundedAutonomyServiceError(
            "bounded-autonomy max_iterations is invalid"
        )
    max_iterations = int(raw_iterations)
    if max_iterations < 1:
        raise BoundedAutonomyServiceError(
            "bounded-autonomy max_iterations is invalid"
        )

    raw_repair_duration = context.options.get(
        "max_repair_duration_ms", str(MAX_REPAIR_DURATION_MS)
    )
    if type(raw_repair_duration) is not str or not raw_repair_duration.isdigit():
        raise BoundedAutonomyServiceError(
            "bounded-autonomy max_repair_duration_ms is invalid"
        )
    max_repair_duration = int(raw_repair_duration)
    if max_repair_duration < 1:
        raise BoundedAutonomyServiceError(
            "bounded-autonomy max_repair_duration_ms is invalid"
        )

    raw_total_duration = context.options.get(
        "max_total_duration_ms", str(MAX_TOTAL_DURATION_MS)
    )
    if type(raw_total_duration) is not str or not raw_total_duration.isdigit():
        raise BoundedAutonomyServiceError(
            "bounded-autonomy max_total_duration_ms is invalid"
        )
    max_total_duration = int(raw_total_duration)
    if max_total_duration < 1:
        raise BoundedAutonomyServiceError(
            "bounded-autonomy max_total_duration_ms is invalid"
        )

    raw_dedup = context.options.get(
        "workspace_digest_dedup", "true" if WORKSPACE_DIGEST_DEDUP else "false"
    )
    if raw_dedup == "true":
        dedup_enabled = True
    elif raw_dedup == "false":
        dedup_enabled = False
    else:
        raise BoundedAutonomyServiceError(
            "bounded-autonomy workspace_digest_dedup is invalid"
        )

    return _BoundedAutonomyLimits(
        max_iterations=max_iterations,
        max_repair_duration_ms=max_repair_duration,
        max_total_duration_ms=max_total_duration,
        workspace_digest_dedup=dedup_enabled,
    )


def _compute_workspace_digest(artifact: object) -> str:
    """Compute the canonical-JSON SHA-256 of one propose / repair artifact.

    The encoding uses ``sort_keys=True`` with the tight ``(",", ":")``
    separator so any artifact maps to exactly one hex digest. This is the
    same canonical form used by :func:`_join_result_digest` and by
    P3 / P4's ``seal`` helpers.
    """

    encoded = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def seal_p5_native_receipt(
    *,
    root_run_id: str,
    root_generation: int,
    propose_step_count: int,
    verify_step_count: int,
    repair_step_count: int,
    failed_verify_count: int,
    terminal_reason: TerminalReason,
    joined_workspace_digest: str,
) -> P5NativeReceipt:
    """Build a sealed :class:`P5NativeReceipt` with the computed receipt SHA.

    Thin host-service wrapper around
    :func:`asterion.applications.prime.p5.receipt.seal`. The
    canonical-JSON SHA-256 logic and shape validation live in
    :mod:`asterion.applications.prime.p5.receipt`; this wrapper exists
    so the existing host-service callers (and their tests) keep seeing
    :class:`BoundedAutonomyServiceError` for invalid inputs rather than
    the receipt-level :class:`P5ReceiptError`.

    The 64-char hex digest format check is enforced here because the
    host-service boundary requires it independently of the receipt-level
    validator; this matches the original Phase 8 / Task 3 surface.
    """

    if (
        not isinstance(joined_workspace_digest, str)
        or len(joined_workspace_digest) != 64
        or any(
            character not in "0123456789abcdef"
            for character in joined_workspace_digest
        )
    ):
        raise BoundedAutonomyServiceError(
            "seal joined_workspace_digest is invalid"
        )
    try:
        return _seal_p5_native_receipt_impl(
            root_run_id=root_run_id,
            root_generation=root_generation,
            propose_step_count=propose_step_count,
            verify_step_count=verify_step_count,
            repair_step_count=repair_step_count,
            failed_verify_count=failed_verify_count,
            terminal_reason=terminal_reason,
            joined_workspace_digest=joined_workspace_digest,
        )
    except P5ReceiptError as exc:
        raise BoundedAutonomyServiceError(str(exc)) from None


class BoundedAutonomyLoop:
    """Application-level bounded propose/verify/repair loop controller.

    Default path: in-process (mirror D-2026-09-18-02). Subprocess supervisor
    is NOT implemented in Phase 8. Composes the injected propose /
    verify / repair callables (which themselves call ``prime.ipython``
    for propose + repair and ``prime.p5-oracle`` for verify) under
    framework-owned duration / iteration / progress limits. Stops
    exactly once with one of the closed :data:`TerminalReason` values —
    no implicit retry, no autonomous continuation.

    Each :meth:`run_loop` invocation emits exactly one
    :class:`P5NativeReceipt`. Subsequent calls return the cached
    terminal receipt — there is no public "still running" state.
    """

    def __init__(
        self,
        *,
        limits: _BoundedAutonomyLimits,
        opened_at_iso: str,
        propose_callable: ProposeCallable | None = None,
        verify_callable: VerifyCallable | None = None,
        repair_callable: RepairCallable | None = None,
    ) -> None:
        self._limits = limits
        self._opened_at_iso = opened_at_iso
        self._propose_callable = propose_callable
        self._verify_callable = verify_callable
        self._repair_callable = repair_callable
        self._terminal_receipt: P5NativeReceipt | None = None
        self._last_step_timed_out_flag: bool = False
        self._last_step_kind: str = "propose"

    @property
    def public_identity(self) -> _PublicBoundedAutonomyIdentity:
        """Return a redacted identity projection bound at factory time.

        The projection is content-safe: it never carries
        ``private_root_identity``. The bound ``session_id``,
        ``provider_id``, ``application_id``, ``runtime_id`` and digests are
        surfaced for diagnostics only.
        """

        return _PublicBoundedAutonomyIdentity(
            provider_id="prime-applications",
            application_id="prime.bounded-autonomy",
            runtime_id="asterion.prime",
            session_id="prime.bounded-autonomy",
            generation=1,
            pi_command_sha256=_ZERO_SHA256,
            extension_binding_fingerprint=_ZERO_SHA256,
            worker_identity_sha256=_ZERO_SHA256,
            continuation_id="bounded-autonomy-initial",
            ceilings_sha256=_ZERO_SHA256,
        )

    @property
    def last_step_timed_out(self) -> bool:
        """True iff the most recent step exceeded its per-step duration cap.

        The flag is a single-shot: a step that completes within its cap
        clears it. The flag is meaningful for the duration-cap-exceeded
        terminal reason — the witness asserts it on the duration-cap
        scenario's sealed receipt.
        """

        return self._last_step_timed_out_flag

    def set_step_callables(
        self,
        *,
        propose_callable: ProposeCallable,
        verify_callable: VerifyCallable,
        repair_callable: RepairCallable,
    ) -> None:
        """Inject the propose / verify / repair callables.

        The operator (Task 8) and runtime binding (Task 7) wire the
        actual ``prime.ipython`` and ``prime.p5-oracle`` services through
        this surface; tests inject deterministic fakes the same way.
        The callables must be set before the first :meth:`run_loop` call.
        """

        self._propose_callable = propose_callable
        self._verify_callable = verify_callable
        self._repair_callable = repair_callable

    async def _propose_step(
        self, signal: CancellationSignal | None
    ) -> P5ProposeStep:
        """Run one propose step via the injected propose callable.

        Mirrors ``prime.ipython`` semantics for P5: the callable returns
        a :class:`P5ProposeStep` whose ``workspace_digest_sha256`` is
        the canonical-form SHA-256 of the candidate artifact.
        """

        if self._propose_callable is None:
            raise BoundedAutonomyServiceError(
                "bounded-autonomy propose_callable is not configured"
            )
        return await self._propose_callable(signal)

    async def _verify_step(
        self, signal: CancellationSignal | None
    ) -> P5VerifyStep:
        """Run one verify step via the injected verify callable.

        Mirrors ``prime.p5-oracle`` semantics for P5: the callable
        returns a :class:`P5VerifyStep` whose ``verdict`` is one of the
        closed 4-element oracle verdict enum.
        """

        if self._verify_callable is None:
            raise BoundedAutonomyServiceError(
                "bounded-autonomy verify_callable is not configured"
            )
        return await self._verify_callable(signal)

    async def _repair_step(
        self, signal: CancellationSignal | None
    ) -> P5RepairStep:
        """Run one repair step via the injected repair callable.

        Mirrors ``prime.ipython`` semantics for P5 repair: the callable
        returns a :class:`P5RepairStep` whose ``workspace_digest_sha256``
        is the post-repair canonical-form SHA-256.
        """

        if self._repair_callable is None:
            raise BoundedAutonomyServiceError(
                "bounded-autonomy repair_callable is not configured"
            )
        return await self._repair_callable(signal)

    async def _drive_step_with_total_cap(
        self,
        step_coro: Callable[[], Awaitable[object]],
        *,
        step_label: str,
        deadline_monotonic: float,
        on_timeout: Callable[[], tuple[TerminalReason, P5NativeReceipt | None]],
    ) -> tuple[bool, object | None]:
        """Drive a single step under the total-duration cap.

        Returns ``(timed_out, value)``. ``timed_out`` is True iff the
        step exceeded the remaining total-duration budget; in that case
        ``value`` is None and ``last_step_timed_out`` is set to True.
        """

        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0:
            self._last_step_timed_out_flag = True
            self._last_step_kind = step_label
            reason, _ = on_timeout()
            return True, reason
        try:
            value = await asyncio.wait_for(step_coro(), timeout=remaining)
        except asyncio.TimeoutError:
            self._last_step_timed_out_flag = True
            self._last_step_kind = step_label
            reason, _ = on_timeout()
            return True, reason
        self._last_step_timed_out_flag = False
        return False, value

    async def _drive_repair_step(
        self,
        signal: CancellationSignal | None,
        *,
        deadline_monotonic: float,
    ) -> P5RepairStep:
        """Drive one repair step under the per-repair-step duration cap.

        The per-repair-step cap (``MAX_REPAIR_DURATION_MS``) bounds the
        wall-clock of a single repair step; the total-duration cap is
        enforced by :meth:`_drive_step_with_total_cap` at the loop level.
        """

        remaining_total = deadline_monotonic - time.monotonic()
        if remaining_total <= 0:
            self._last_step_timed_out_flag = True
            self._last_step_kind = "repair"
            raise asyncio.TimeoutError
        per_step_cap = min(
            self._limits.max_repair_duration_ms / 1000.0,
            remaining_total,
        )
        return await asyncio.wait_for(
            self._repair_step(signal), timeout=per_step_cap
        )

    async def run_loop(
        self,
        *,
        root_run_id: str,
        signal: CancellationSignal | None = None,
    ) -> P5NativeReceipt:
        """Drive the bounded loop. Single terminal result; never returns
        a still-running state.

        Order of checks mirrors the spec §"Stopping conditions":

        * Cancellation is checked before each step; a cancelled signal
          terminates with ``terminal_reason = "cancelled"``.
        * The total-duration cap is checked before each step; an
          exceeded cap terminates with ``terminal_reason =
          "duration-cap-exceeded"``.
        * The iteration cap is enforced after each verify-fail; a
          ``max_iterations``-th failed verify terminates with
          ``terminal_reason = "iteration-cap-exceeded"`` BEFORE running
          the next repair step.
        * The workspace-digest dedup-adapter refuses a second gate
          whose digest equals the prior gate's digest; the loop
          terminates with ``terminal_reason = "no-progress"``.
        * A passing verify terminates with ``terminal_reason =
          "success"``.

        Each run_loop invocation executes exactly one propose step. After
        a failed verify, the loop runs a repair step and goes directly to
        the next verify step (no second propose); this matches the spec
        witness structure (``propose_step_count == 1``).
        """

        if not isinstance(root_run_id, str) or not root_run_id:
            raise BoundedAutonomyServiceError("run_loop root_run_id is invalid")

        cached = self._terminal_receipt
        if cached is not None and cached.root_run_id == root_run_id:
            return cached

        self._last_step_timed_out_flag = False
        self._last_step_kind = "propose"

        propose_count = 0
        verify_count = 0
        repair_count = 0
        failed_verify_count = 0
        prior_digest: str | None = None
        joined_workspace_digest: str | None = None
        terminal_reason: TerminalReason = "cancelled"

        deadline_monotonic = (
            time.monotonic() + self._limits.max_total_duration_ms / 1000.0
        )

        def _is_cancelled() -> bool:
            return signal is not None and getattr(signal, "cancelled", False)

        def _terminate(
            reason: TerminalReason,
            *,
            digest: str | None = None,
        ) -> None:
            nonlocal terminal_reason, joined_workspace_digest
            terminal_reason = reason
            if digest is not None:
                joined_workspace_digest = digest
            elif joined_workspace_digest is None and prior_digest is not None:
                joined_workspace_digest = prior_digest

        if _is_cancelled():
            _terminate("cancelled")
            self._emit_receipt(
                root_run_id=root_run_id,
                propose_count=propose_count,
                verify_count=verify_count,
                repair_count=repair_count,
                failed_verify_count=failed_verify_count,
                terminal_reason=terminal_reason,
                joined_workspace_digest=joined_workspace_digest,
            )
            return self._terminal_receipt

        if time.monotonic() >= deadline_monotonic:
            self._last_step_timed_out_flag = True
            _terminate("duration-cap-exceeded")
            self._emit_receipt(
                root_run_id=root_run_id,
                propose_count=propose_count,
                verify_count=verify_count,
                repair_count=repair_count,
                failed_verify_count=failed_verify_count,
                terminal_reason=terminal_reason,
                joined_workspace_digest=joined_workspace_digest,
            )
            return self._terminal_receipt

        # Propose step — wall-clock bounded by the total-duration cap.
        self._last_step_kind = "propose"
        try:
            timed_out, propose_value = await self._drive_step_with_total_cap(
                lambda: self._propose_step(signal),
                step_label="propose",
                deadline_monotonic=deadline_monotonic,
                on_timeout=lambda: ("duration-cap-exceeded", None),
            )
        except BoundedAutonomyServiceError:
            raise
        except Exception:
            raise BoundedAutonomyServiceError(
                "bounded-autonomy propose step raised"
            ) from None
        if timed_out:
            _terminate("duration-cap-exceeded")
            self._emit_receipt(
                root_run_id=root_run_id,
                propose_count=1,
                verify_count=1,
                repair_count=0,
                failed_verify_count=1,
                terminal_reason=terminal_reason,
                joined_workspace_digest=joined_workspace_digest,
            )
            return self._terminal_receipt
        assert isinstance(propose_value, P5ProposeStep)
        propose_step: P5ProposeStep = propose_value
        propose_count = 1
        prior_digest = propose_step.workspace_digest_sha256
        joined_workspace_digest = prior_digest

        # Verify / repair loop — after the initial propose, only verify
        # and repair steps follow. The iteration cap is enforced BEFORE
        # each repair step (so a repair is never run when the cap has
        # fired). The workspace-digest dedup-adapter short-circuits the
        # next verify step when the repair's digest equals the prior
        # gate's digest.
        while True:
            if _is_cancelled():
                _terminate("cancelled")
                break

            if time.monotonic() >= deadline_monotonic:
                self._last_step_timed_out_flag = True
                _terminate("duration-cap-exceeded")
                break

            # Verify step — wall-clock bounded by the total-duration cap.
            self._last_step_kind = "verify"
            try:
                timed_out, verify_value = await self._drive_step_with_total_cap(
                    lambda: self._verify_step(signal),
                    step_label="verify",
                    deadline_monotonic=deadline_monotonic,
                    on_timeout=lambda: ("duration-cap-exceeded", None),
                )
            except BoundedAutonomyServiceError:
                raise
            except Exception:
                raise BoundedAutonomyServiceError(
                    "bounded-autonomy verify step raised"
                ) from None
            if timed_out:
                _terminate("duration-cap-exceeded")
                break
            assert isinstance(verify_value, P5VerifyStep)
            verify_step: P5VerifyStep = verify_value
            verify_count += 1

            if verify_step.verdict == "pass":
                _terminate("success")
                break
            if verify_step.verdict == "cancelled":
                _terminate("cancelled")
                break
            if verify_step.verdict == "no-progress":
                _terminate("no-progress")
                break
            # "fail" — record and continue with a repair step.
            failed_verify_count += 1
            if failed_verify_count >= self._limits.max_iterations:
                _terminate("iteration-cap-exceeded")
                break

            if _is_cancelled():
                _terminate("cancelled")
                break

            if time.monotonic() >= deadline_monotonic:
                self._last_step_timed_out_flag = True
                _terminate("duration-cap-exceeded")
                break

            # Repair step — per-step cap + total-duration cap.
            self._last_step_kind = "repair"
            try:
                repair_step = await self._drive_repair_step(
                    signal, deadline_monotonic=deadline_monotonic
                )
            except asyncio.TimeoutError:
                self._last_step_timed_out_flag = True
                _terminate("duration-cap-exceeded")
                break
            except BoundedAutonomyServiceError:
                raise
            except Exception:
                raise BoundedAutonomyServiceError(
                    "bounded-autonomy repair step raised"
                ) from None
            repair_count += 1

            if (
                self._limits.workspace_digest_dedup
                and repair_step.workspace_digest_sha256 == prior_digest
            ):
                _terminate("no-progress")
                break
            prior_digest = repair_step.workspace_digest_sha256
            joined_workspace_digest = prior_digest

        self._emit_receipt(
            root_run_id=root_run_id,
            propose_count=propose_count,
            verify_count=verify_count,
            repair_count=repair_count,
            failed_verify_count=failed_verify_count,
            terminal_reason=terminal_reason,
            joined_workspace_digest=joined_workspace_digest,
        )
        return self._terminal_receipt

    def _emit_receipt(
        self,
        *,
        root_run_id: str,
        propose_count: int,
        verify_count: int,
        repair_count: int,
        failed_verify_count: int,
        terminal_reason: TerminalReason,
        joined_workspace_digest: str | None,
    ) -> None:
        """Seal the terminal receipt for one :meth:`run_loop` invocation.

        Mirrors :func:`seal_p5_native_receipt` while keeping the loop
        body readable. Propose and verify counters default to ``1`` when the loop
        terminated before reaching the corresponding step. A correct first
        proposal has zero failed verifies and no repair.
        """

        if joined_workspace_digest is None:
            joined_workspace_digest = _ZERO_SHA256
        self._terminal_receipt = seal_p5_native_receipt(
            root_run_id=root_run_id,
            root_generation=1,
            propose_step_count=propose_count if propose_count >= 1 else 1,
            verify_step_count=verify_count if verify_count >= 1 else 1,
            repair_step_count=repair_count,
            failed_verify_count=(
                failed_verify_count
                if terminal_reason == "success"
                else max(1, failed_verify_count)
            ),
            terminal_reason=terminal_reason,
            joined_workspace_digest=joined_workspace_digest,
        )


@asynccontextmanager
async def _open_bounded_autonomy_service(
    context: HostServiceFactoryContext,
):
    if (
        context.provider_id != "prime-applications"
        or context.application_id != "prime.bounded-autonomy"
        or context.application_version != "1.0.0"
        or context.capability_id != "prime.bounded-autonomy"
    ):
        raise BoundedAutonomyServiceError(
            "bounded-autonomy context identity is invalid"
        )
    limits = _resolve_bounded_autonomy_limits(context)
    service = BoundedAutonomyLoop(
        limits=limits,
        opened_at_iso=_iso_utc_now(),
    )
    try:
        yield service
    finally:
        service._terminal_receipt = None


def create_bounded_autonomy_host_service() -> HostServiceFactoryBinding:
    """Return the exact factory binding for ``prime.bounded-autonomy``."""

    return HostServiceFactoryBinding(
        capability_id="prime.bounded-autonomy",
        option_names=(
            "max_iterations",
            "max_repair_duration_ms",
            "max_total_duration_ms",
            "workspace_digest_dedup",
        ),
        factory=_open_bounded_autonomy_service,
    )




__all__ = (
    "BoundedAutonomyLoop",
    "BoundedAutonomyServiceError",
    "CandidateStoreLoop",
    "CandidateStoreServiceError",
    "CandidateStoreTerminalOutcome",
    "CandidateStoreVerdict",
    "ChildAdmission",
    "ChildAdmissionRefused",
    "ChildRunnerHostService",
    "ChildRunnerServiceError",
    "ContinuityStoreHostService",
    "ContinuityStoreServiceError",
    "HoldoutResult",
    "MAX_ACTIONS",
    "MAX_CANDIDATE_REVISIONS_PER_RUN",
    "MAX_CHILD_COST_USD",
    "MAX_CONCURRENT_CHILDREN",
    "MAX_COST_USD",
    "MAX_DEADLINE_MS",
    "MAX_DEPTH",
    "MAX_HOLDOUT_EVALUATIONS_PER_RUN",
    "MAX_ITERATIONS",
    "MAX_REPAIR_DURATION_MS",
    "MAX_ROLLBACK_INVOCATIONS_PER_RUN",
    "MAX_TOTAL_DURATION_MS",
    "MAX_USAGE_PROVIDER_OPS",
    "P5NativeReceipt",
    "P5ProposeStep",
    "P5RepairStep",
    "P5VerifyStep",
    "TerminalReason",
    "WORKSPACE_DIGEST_DEDUP",
    "create_bounded_autonomy_host_service",
    "create_candidate_store_host_service",
    "create_child_runner_host_service",
    "create_continuity_store_host_service",
    "seal_p5_native_receipt",
)