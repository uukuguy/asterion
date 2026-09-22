"""P6 candidate-store host service over one framework HarnessCoordinator.

The Prime services module re-exports these objects for existing integrations.
This module owns candidate admission, holdout evaluation, promotion, and the
explicit inverse cleanup boundary; it does not import the service facade.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Callable, Literal

from asterion.control.harness import (
    HarnessCoordinator, HarnessError as _HarnessError, HarnessProposal,
    HarnessRevision, HarnessScope,
)
from asterion.runtime.host import CancellationSignal
from asterion.services.registry import (
    HostServiceFactoryBinding, HostServiceFactoryContext, HostServiceRegistryError,
)

_ZERO_SHA256 = "0" * 64


# ---------------------------------------------------------------------------
# prime.candidate-store host service (Phase 9, Task 3)
# ---------------------------------------------------------------------------

# P6 candidate-store limits. Each limit is configurable through the host
# service factory context when present, otherwise taken from the spec
# defaults below. Defaults match
# ``docs/superpowers/specs/2026-09-19-asterion-prime-p6-native-design.md``
# §"Newly introduced in Phase 9".
MAX_CANDIDATE_REVISIONS_PER_RUN = 1
MAX_HOLDOUT_EVALUATIONS_PER_RUN = 1
MAX_ROLLBACK_INVOCATIONS_PER_RUN = 1
MAX_ACTIONS = 1
MAX_USAGE_PROVIDER_OPS = 4
MAX_DEADLINE_MS = 60_000
MAX_COST_USD = Decimal("0.05")
CANDIDATE_STORE_DEFAULT_SCOPE = "project"


# Public closed 2-element enum for the receipt contract. The oracle's
# 3-element verdict enum (``preserved`` / ``rolled-back`` /
# ``global-rejected``) is internal-only and folds into the public
# ``rolled-back`` surface for the boundary-rejection case (spec L182–L189).
CandidateStoreTerminalOutcome = Literal["preserved", "rolled-back"]

# Internal closed 3-element enum for the oracle verdict. Exposed as a
# type alias only — never published through the host service's public
# identity (D-2026-09-19-02).
CandidateStoreVerdict = Literal["preserved", "rolled-back", "global-rejected"]


@dataclass(frozen=True)
class _PublicCandidateStoreIdentity:
    """Content-safe identity projection of a bound candidate-store loop.

    Carries every field of :class:`PrimeBackendIdentity` except the private
    ``private_root_identity`` digest. Exposed only through
    :attr:`CandidateStoreLoop.public_identity` so the host service surface
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
class _CandidateStoreLimits:
    """Resolved limit set for one open ``prime.candidate-store`` service."""

    max_candidate_revisions_per_run: int
    max_holdout_evaluations_per_run: int
    max_rollback_invocations_per_run: int
    max_actions: int
    max_usage_provider_ops: int
    max_deadline_ms: int
    max_cost_usd: Decimal


def _resolve_candidate_store_limits(
    context: HostServiceFactoryContext,
) -> _CandidateStoreLimits:
    """Validate context options and resolve the active P6 limit set.

    Each limit is optional and falls back to the spec default when omitted;
    any other key in :attr:`context.options` is rejected. Recognised keys:

    * ``max_candidate_revisions_per_run`` (int, >= 1) — defaults to
      :data:`MAX_CANDIDATE_REVISIONS_PER_RUN`.
    * ``max_holdout_evaluations_per_run`` (int, >= 1) — defaults to
      :data:`MAX_HOLDOUT_EVALUATIONS_PER_RUN`.
    * ``max_rollback_invocations_per_run`` (int, >= 1) — defaults to
      :data:`MAX_ROLLBACK_INVOCATIONS_PER_RUN`.
    * ``max_actions`` (int, >= 1) — defaults to :data:`MAX_ACTIONS`.
    * ``max_usage_provider_ops`` (int, >= 1) — defaults to
      :data:`MAX_USAGE_PROVIDER_OPS`.
    * ``max_deadline_ms`` (int, >= 1) — defaults to :data:`MAX_DEADLINE_MS`.
    * ``max_cost_usd`` (decimal string) — defaults to :data:`MAX_COST_USD`.
    """

    unknown = set(context.options) - {
        "max_candidate_revisions_per_run",
        "max_holdout_evaluations_per_run",
        "max_rollback_invocations_per_run",
        "max_actions",
        "max_usage_provider_ops",
        "max_deadline_ms",
        "max_cost_usd",
    }
    if unknown:
        raise CandidateStoreServiceError(
            "candidate-store options are invalid"
        )

    def _read_positive_int(key: str, default: int) -> int:
        raw = context.options.get(key, str(default))
        if type(raw) is not str or not raw.isdigit():
            raise CandidateStoreServiceError(
                f"candidate-store {key} is invalid"
            )
        value = int(raw)
        if value < 1:
            raise CandidateStoreServiceError(
                f"candidate-store {key} is invalid"
            )
        return value

    max_candidate_revisions_per_run = _read_positive_int(
        "max_candidate_revisions_per_run", MAX_CANDIDATE_REVISIONS_PER_RUN
    )
    max_holdout_evaluations_per_run = _read_positive_int(
        "max_holdout_evaluations_per_run", MAX_HOLDOUT_EVALUATIONS_PER_RUN
    )
    max_rollback_invocations_per_run = _read_positive_int(
        "max_rollback_invocations_per_run", MAX_ROLLBACK_INVOCATIONS_PER_RUN
    )
    max_actions = _read_positive_int("max_actions", MAX_ACTIONS)
    max_usage_provider_ops = _read_positive_int(
        "max_usage_provider_ops", MAX_USAGE_PROVIDER_OPS
    )
    max_deadline_ms = _read_positive_int("max_deadline_ms", MAX_DEADLINE_MS)

    raw_cost = context.options.get("max_cost_usd", str(MAX_COST_USD))
    if type(raw_cost) is not str:
        raise CandidateStoreServiceError(
            "candidate-store max_cost_usd is invalid"
        )
    try:
        max_cost_usd = Decimal(raw_cost)
    except ArithmeticError:
        raise CandidateStoreServiceError(
            "candidate-store max_cost_usd is invalid"
        ) from None
    if max_cost_usd <= 0:
        raise CandidateStoreServiceError(
            "candidate-store max_cost_usd is invalid"
        )

    return _CandidateStoreLimits(
        max_candidate_revisions_per_run=max_candidate_revisions_per_run,
        max_holdout_evaluations_per_run=max_holdout_evaluations_per_run,
        max_rollback_invocations_per_run=max_rollback_invocations_per_run,
        max_actions=max_actions,
        max_usage_provider_ops=max_usage_provider_ops,
        max_deadline_ms=max_deadline_ms,
        max_cost_usd=max_cost_usd,
    )


class CandidateStoreServiceError(HostServiceRegistryError):
    """Raised when ``prime.candidate-store`` cannot be opened safely."""


def _error_digest(exc: BaseException) -> str:
    """Compute a 64-hex SHA-256 diagnostic digest for an exception.

    The digest payload is the canonical-form of
    ``{kind: str, message: str, frame_fingerprints: list[str]}`` — no
    prompt bodies, no model prose, no source locations
    (spec L437–L438). ``__cause__`` / ``__context__`` are intentionally
    walked only when the immediate ``kind`` does not name the underlying
    cause; the fingerprint list captures the chain without leaking the
    actual frame text.
    """

    frame_fingerprints: list[str] = []
    current: BaseException | None = exc
    depth = 0
    while current is not None and depth < 4:
        frame_fingerprints.append(
            hashlib.sha256(
                f"{type(current).__name__}:{depth}".encode("utf-8")
            ).hexdigest()
        )
        current = current.__cause__ if current.__cause__ is not None else current.__context__
        depth += 1
    payload = {
        "kind": type(exc).__name__,
        "message": str(exc),
        "frame_fingerprints": frame_fingerprints,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# The holdout callable is the operator-injected P6 oracle seam. It
# receives the admitted candidate revision and the baseline snapshot
# entry projection and returns a ``HoldoutResult`` whose
# ``task_b_result_sha256`` is a 64-hex SHA-256 and whose
# ``non_regressing`` is the boolean verdict.
@dataclass(frozen=True)
class HoldoutResult:
    """Public-safe record returned by the holdout callable.

    ``task_b_result_sha256`` is the canonical-form SHA-256 of the task B
    result. ``non_regressing`` is the holdout verdict (``True`` for the
    ``preserved`` path; ``False`` for the ``rolled-back`` path).
    """

    task_b_result_sha256: str
    non_regressing: bool


HoldoutCallable = Callable[[HarnessRevision, object], HoldoutResult]


class CandidateStoreLoop:
    """Application-level wrapper around the framework-owned ``HarnessCoordinator``.

    Owns the admitted-candidate lifecycle (admit → holdout → preserve or
    rollback) under the framework-owned ``HarnessCoordinator``'s
    append-only revision authority. **Composition over duplication**: the
    wrapper does NOT reimplement the coordinator's revision authority,
    scope mapping, inverse-rollback logic, or snapshot projection. Every
    admission, promotion, and rollback call is delegated to the wrapped
    coordinator via its public API (``apply(proposal)`` /
    ``rollback(...)``).

    The wrapper owns:

    * Single-candidate-per-run enforcement
      (:data:`MAX_CANDIDATE_REVISIONS_PER_RUN`).
    * Single-holdout-per-run enforcement
      (:data:`MAX_HOLDOUT_EVALUATIONS_PER_RUN`).
    * Single-rollback-per-run enforcement
      (:data:`MAX_ROLLBACK_INVOCATIONS_PER_RUN`).
    * Finite action / usage / deadline / cost ceilings (mirrors
      P5's :class:`BoundedAutonomyLoop`).
    * Public ``terminal_outcome`` enum (closed 2-element) and internal
      :data:`CandidateStoreVerdict` (closed 3-element); ``global-rejected``
      folds into ``terminal_outcome="rolled-back"`` +
      ``global_activation_approved=False`` so the public enum stays closed.
    * Error folding: cancellation, candidate-admission errors,
      holdout-evaluation errors, and promotion-action errors all fold to
      ``terminal_outcome="rolled-back"`` with a 64-hex diagnostic digest
      (spec L283–L292).

    Default scope: ``project`` (matches the pre-detachment spec's fixed
    acceptance candidate — a project-scoped memory update). Scope
    ``global`` requires ``global_activation_approved=True``; the boundary
    rejection is a pre-orchestration short-circuit that does NOT enter
    the harness journal.
    """

    def __init__(
        self,
        *,
        limits: _CandidateStoreLimits,
        opened_at_iso: str,
        scope: HarnessScope,
        coordinator: HarnessCoordinator,
        global_activation_approved: bool,
        holdout_callable: HoldoutCallable | None = None,
    ) -> None:
        self._limits = limits
        self._opened_at_iso = opened_at_iso
        self._scope = scope
        self._coordinator = coordinator
        self._global_activation_approved = global_activation_approved
        self._holdout_callable = holdout_callable
        self._candidate_revision: HarnessRevision | None = None
        self._holdout_result: HoldoutResult | None = None
        self._promotion_revision: HarnessRevision | None = None
        self._rollback_revision: HarnessRevision | None = None
        self._admission_count = 0
        self._holdout_count = 0
        self._rollback_count = 0
        self._cleanup_attempted = False
        self._last_evaluation_digest: str | None = None

    @property
    def public_identity(self) -> _PublicCandidateStoreIdentity:
        """Return a redacted identity projection bound at factory time.

        The projection is content-safe: it never carries
        ``private_root_identity``. The bound ``session_id``,
        ``provider_id``, ``application_id``, ``runtime_id`` and digests are
        surfaced for diagnostics only.
        """

        return _PublicCandidateStoreIdentity(
            provider_id="prime-applications",
            application_id="prime.continual-improvement",
            runtime_id="asterion.prime",
            session_id="prime.candidate-store",
            generation=1,
            pi_command_sha256=_ZERO_SHA256,
            extension_binding_fingerprint=_ZERO_SHA256,
            worker_identity_sha256=_ZERO_SHA256,
            continuation_id="candidate-store-initial",
            ceilings_sha256=_ZERO_SHA256,
        )

    @property
    def last_evaluation_digest(self) -> str | None:
        """Return the canonical-form SHA-256 of the most recent holdout result.

        ``None`` until :meth:`evaluate_holdout` has been called at least
        once during the current open run. The digest is the canonical-JSON
        SHA-256 of the holdout result's
        ``task_b_result_sha256`` + ``non_regressing`` tuple.
        """

        return self._last_evaluation_digest

    @property
    def rollback_invocation_count(self) -> int:
        """Return the number of inverse revisions the wrapper has applied."""

        return self._rollback_count

    def set_holdout_callable(self, *, holdout_callable: HoldoutCallable) -> None:
        """Inject the operator-provided holdout callable.

        The callable receives the admitted ``HarnessRevision`` and the
        baseline entry projection (``tuple[HarnessEntryDescriptor, ...]``)
        and returns a :class:`HoldoutResult`. It MUST be set before the
        first :meth:`evaluate_holdout` call.
        """

        self._holdout_callable = holdout_callable

    def admit_candidate(
        self,
        *,
        proposal: HarnessProposal,
        signal: CancellationSignal | None = None,
    ) -> HarnessRevision:
        """Admit one candidate via the wrapped ``HarnessCoordinator.apply``.

        Enforces :data:`MAX_CANDIDATE_REVISIONS_PER_RUN`; a second
        ``admit_candidate`` call within the same open run raises
        :class:`CandidateStoreServiceError` (folded to
        ``rolled-back`` by :meth:`promote_or_rollback`). The boundary
        rejection for ``scope=global`` + ``global_activation_approved=False``
        fires pre-orchestration: no ``HarnessRevision`` is created, the
        wrapped coordinator's snapshot is unchanged.
        """

        if self._is_cancelled(signal):
            raise CandidateStoreServiceError(
                "candidate-store cancellation is set"
            )
        if self._admission_count >= self._limits.max_candidate_revisions_per_run:
            raise CandidateStoreServiceError(
                "candidate-store admits only one candidate per run"
            )
        if (
            self._scope.kind == "global"
            and not self._global_activation_approved
        ):
            # Pre-orchestration boundary rejection: NO HarnessRevision is
            # created, the wrapped coordinator's snapshot is unchanged.
            # The caller is expected to fold this into
            # ``terminal_outcome="rolled-back"`` via
            # :meth:`promote_or_rollback`.
            raise CandidateStoreServiceError(
                "candidate-store global-scope requires operator authorization"
            )
        try:
            revision = self._coordinator.apply(proposal)
        except _HarnessError as exc:
            raise CandidateStoreServiceError(
                "candidate-store admission raised"
            ) from exc
        self._candidate_revision = revision
        self._admission_count += 1
        return revision

    def evaluate_holdout(
        self,
        *,
        candidate: HarnessRevision,
        baseline: object,
        signal: CancellationSignal | None = None,
    ) -> HoldoutResult:
        """Evaluate the admitted candidate on the task B holdout.

        Enforces :data:`MAX_HOLDOUT_EVALUATIONS_PER_RUN`; a second
        ``evaluate_holdout`` call within the same open run raises
        :class:`CandidateStoreServiceError`. The holdout callable MUST be
        set via :meth:`set_holdout_callable` before this call.
        """

        if self._is_cancelled(signal):
            raise CandidateStoreServiceError(
                "candidate-store cancellation is set"
            )
        if self._holdout_count >= self._limits.max_holdout_evaluations_per_run:
            raise CandidateStoreServiceError(
                "candidate-store evaluates holdout only once per run"
            )
        if self._holdout_callable is None:
            raise CandidateStoreServiceError(
                "candidate-store holdout_callable is not configured"
            )
        if not isinstance(candidate, HarnessRevision):
            raise CandidateStoreServiceError(
                "candidate-store candidate is invalid"
            )
        try:
            result = self._holdout_callable(candidate, baseline)
        except _HarnessError as exc:
            raise CandidateStoreServiceError(
                "candidate-store holdout raised"
            ) from exc
        except CandidateStoreServiceError:
            raise
        except Exception as exc:
            raise CandidateStoreServiceError(
                "candidate-store holdout raised"
            ) from exc
        if not isinstance(result, HoldoutResult):
            raise CandidateStoreServiceError(
                "candidate-store holdout result is invalid"
            )
        if (
            not isinstance(result.task_b_result_sha256, str)
            or len(result.task_b_result_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in result.task_b_result_sha256
            )
        ):
            raise CandidateStoreServiceError(
                "candidate-store holdout task_b_result_sha256 is invalid"
            )
        self._holdout_result = result
        self._holdout_count += 1
        self._last_evaluation_digest = _compute_holdout_digest(result)
        return result

    def promote_or_rollback(
        self,
        *,
        promotion_action: HarnessProposal,
        rollback_proposal_id: str,
        rollback_authority_id: str,
        rollback_authority_revision: int,
        rollback_target_revision_id: str,
        rollback_rationale_ref: str,
        rollback_rationale_digest: str,
        rollback_expected_outcome_digest: str,
        signal: CancellationSignal | None = None,
    ) -> tuple[CandidateStoreVerdict, CandidateStoreTerminalOutcome, dict[str, object]]:
        """Apply the explicit promotion OR exact inverse rollback and seal.

        Returns a tuple ``(verdict, terminal_outcome, summary)`` where:

        * ``verdict`` is the internal closed 3-element
          :data:`CandidateStoreVerdict` (``preserved`` | ``rolled-back``
          | ``global-rejected``).
        * ``terminal_outcome`` is the public closed 2-element
          :data:`CandidateStoreTerminalOutcome` (``preserved`` |
          ``rolled-back``).
        * ``summary`` carries the diagnostic-digest fields plus the
          rollback-invocation count. ``global-rejected`` verdicts fold
          into ``terminal_outcome="rolled-back"`` +
          ``global_activation_approved=False`` (spec L182–L189).
        """

        if self._is_cancelled(signal):
            if self._candidate_revision is not None:
                # The caller owns cleanup of this admitted effect. A tuple
                # claiming rollback before an inverse revision exists would
                # hide the recovery obligation from direct callers.
                raise CandidateStoreServiceError(
                    "candidate-store effects require recovery"
                )
            digest = _error_digest(
                CandidateStoreServiceError("candidate-store cancellation is set")
            )
            return (
                "rolled-back",
                "rolled-back",
                {
                    "cancellation_digest": digest,
                    "rollback_invocation_count": self._rollback_count,
                    "global_activation_approved": (
                        self._global_activation_approved
                    ),
                },
            )

        # Pre-orchestration boundary rejection for ``scope=global`` +
        # ``global_activation_approved=False``: NO HarnessRevision is
        # ever created, NO holdout runs, baseline snapshot unchanged.
        if (
            self._scope.kind == "global"
            and not self._global_activation_approved
        ):
            return (
                "global-rejected",
                "rolled-back",
                {
                    "rollback_invocation_count": self._rollback_count,
                    "global_activation_approved": False,
                },
            )

        candidate = self._candidate_revision
        holdout = self._holdout_result
        if candidate is None or holdout is None:
            digest = _error_digest(
                CandidateStoreServiceError(
                    "candidate-store missing candidate or holdout"
                )
            )
            return (
                "rolled-back",
                "rolled-back",
                {
                    "promotion_action_error_digest": digest,
                    "rollback_invocation_count": self._rollback_count,
                    "global_activation_approved": (
                        self._global_activation_approved
                    ),
                },
            )

        if holdout.non_regressing:
            return self._apply_promotion(promotion_action, signal=signal)

        return self._apply_rollback(
            proposal_id=rollback_proposal_id,
            authority_id=rollback_authority_id,
            authority_revision=rollback_authority_revision,
            target_revision_id=rollback_target_revision_id,
            rationale_ref=rollback_rationale_ref,
            rationale_digest=rollback_rationale_digest,
            expected_outcome_digest=rollback_expected_outcome_digest,
            signal=signal,
        )

    # -- Internal composition-over-duplication methods (load-bearing) -----

    def _admit_proposal(
        self,
        proposal: HarnessProposal,
        *,
        signal: CancellationSignal | None,
    ) -> HarnessRevision:
        """Internal admission wrapper around ``HarnessCoordinator.apply``.

        Composes — does not reimplement — the coordinator's admission
        semantics. Refuses a second call within the same open run.
        """

        if self._admission_count >= self._limits.max_candidate_revisions_per_run:
            raise CandidateStoreServiceError(
                "candidate-store admits only one candidate per run"
            )
        revision = self._coordinator.apply(proposal)
        self._candidate_revision = revision
        self._admission_count += 1
        return revision

    def _evaluate_on_holdout(
        self,
        candidate: HarnessRevision,
        baseline: object,
        *,
        signal: CancellationSignal | None,
    ) -> HoldoutResult:
        """Internal holdout-evaluation wrapper.

        Delegates to the operator-injected holdout callable. Refuses a
        second call within the same open run.
        """

        if self._holdout_count >= self._limits.max_holdout_evaluations_per_run:
            raise CandidateStoreServiceError(
                "candidate-store evaluates holdout only once per run"
            )
        if self._holdout_callable is None:
            raise CandidateStoreServiceError(
                "candidate-store holdout_callable is not configured"
            )
        result = self._holdout_callable(candidate, baseline)
        self._holdout_result = result
        self._holdout_count += 1
        self._last_evaluation_digest = _compute_holdout_digest(result)
        return result

    def _apply_promotion(
        self,
        promotion_action: HarnessProposal,
        *,
        signal: CancellationSignal | None,
    ) -> tuple[CandidateStoreVerdict, CandidateStoreTerminalOutcome, dict[str, object]]:
        """Wrap the explicit promotion action via ``HarnessCoordinator.apply``.

        Composition: the wrapper does not compute the promotion payload;
        it asks the wrapped coordinator to apply the operator's exact
        ``promotion_action`` proposal. On admission failure, folds to
        ``rolled-back`` with a diagnostic digest (spec L283–L292).
        """

        try:
            revision = self._coordinator.apply(promotion_action)
        except _HarnessError as exc:
            digest = _error_digest(exc)
            return (
                "rolled-back",
                "rolled-back",
                {
                    "promotion_action_error_digest": digest,
                    "rollback_invocation_count": self._rollback_count,
                    "global_activation_approved": (
                        self._global_activation_approved
                    ),
                },
            )
        self._promotion_revision = revision
        return (
            "preserved",
            "preserved",
            {
                "rollback_invocation_count": 0,
                "global_activation_approved": (
                    self._global_activation_approved
                ),
            },
        )

    def rollback_admitted_candidate(
        self,
        *,
        proposal_id: str,
        authority_id: str,
        authority_revision: int,
        rationale_ref: str,
        rationale_digest: str,
        expected_outcome_digest: str,
    ) -> HarnessRevision:
        """Apply the operator-authorized inverse after a stopped workflow.

        Cleanup is a distinct bounded action and does not reuse the cancelled
        work signal. The same coordinator still validates authority, scope and
        exact current revision. A failure never becomes a rolled-back result.
        """
        candidate = self._candidate_revision
        if (
            self._cleanup_attempted
            or self._rollback_count != 0
            or candidate is None
            or candidate.status != "succeeded"
            or self._coordinator.snapshot().revision_id != candidate.revision_id
        ):
            raise CandidateStoreServiceError("candidate-store effects require recovery")
        self._cleanup_attempted = True
        self._apply_rollback(
            proposal_id=proposal_id,
            authority_id=authority_id,
            authority_revision=authority_revision,
            target_revision_id=candidate.revision_id,
            rationale_ref=rationale_ref,
            rationale_digest=rationale_digest,
            expected_outcome_digest=expected_outcome_digest,
            signal=None,
        )
        revision = self._rollback_revision
        if (
            self._rollback_count != 1
            or revision is None
            or revision.status != "succeeded"
            or revision.rollback_revision_id != candidate.revision_id
        ):
            raise CandidateStoreServiceError("candidate-store effects require recovery")
        return revision

    def _apply_rollback(
        self,
        *,
        proposal_id: str,
        authority_id: str,
        authority_revision: int,
        target_revision_id: str,
        rationale_ref: str,
        rationale_digest: str,
        expected_outcome_digest: str,
        signal: CancellationSignal | None,
    ) -> tuple[CandidateStoreVerdict, CandidateStoreTerminalOutcome, dict[str, object]]:
        """Wrap the exact inverse rollback via ``HarnessCoordinator.rollback``.

        Composition: the wrapper does not compute the inverse edits; the
        coordinator's ``rollback`` derives the exact inverse from the
        admitted candidate's revision. Enforces
        :data:`MAX_ROLLBACK_INVOCATIONS_PER_RUN`. On rollback failure,
        folds to ``rolled-back`` with a diagnostic digest.
        """

        if self._rollback_count >= self._limits.max_rollback_invocations_per_run:
            digest = _error_digest(
                CandidateStoreServiceError(
                    "candidate-store rolls back only once per run"
                )
            )
            return (
                "rolled-back",
                "rolled-back",
                {
                    "promotion_action_error_digest": digest,
                    "rollback_invocation_count": self._rollback_count,
                    "global_activation_approved": (
                        self._global_activation_approved
                    ),
                },
            )
        try:
            revision = self._coordinator.rollback(
                proposal_id=proposal_id,
                authority_id=authority_id,
                authority_revision=authority_revision,
                target_revision_id=target_revision_id,
                rationale_ref=rationale_ref,
                rationale_digest=rationale_digest,
                expected_outcome_digest=expected_outcome_digest,
            )
        except _HarnessError as exc:
            digest = _error_digest(exc)
            return (
                "rolled-back",
                "rolled-back",
                {
                    "promotion_action_error_digest": digest,
                    "rollback_invocation_count": self._rollback_count,
                    "global_activation_approved": (
                        self._global_activation_approved
                    ),
                },
            )
        self._rollback_revision = revision
        self._rollback_count += 1
        return (
            "rolled-back",
            "rolled-back",
            {
                "rollback_invocation_count": self._rollback_count,
                "global_activation_approved": (
                    self._global_activation_approved
                ),
            },
        )

    @staticmethod
    def _is_cancelled(signal: CancellationSignal | None) -> bool:
        return signal is not None and getattr(signal, "cancelled", False)


def _compute_holdout_digest(result: HoldoutResult) -> str:
    """Compute the canonical-form SHA-256 of one :class:`HoldoutResult`."""

    payload = {
        "non_regressing": result.non_regressing,
        "task_b_result_sha256": result.task_b_result_sha256,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_scope_kind(context: HostServiceFactoryContext) -> str:
    raw_scope = context.options.get("scope", CANDIDATE_STORE_DEFAULT_SCOPE)
    if raw_scope not in {"session", "project", "global"}:
        raise CandidateStoreServiceError(
            "candidate-store scope is invalid"
        )
    return raw_scope


def _read_global_activation(context: HostServiceFactoryContext) -> bool:
    raw = context.options.get("global_activation_approved", "false")
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise CandidateStoreServiceError(
        "candidate-store global_activation_approved is invalid"
    )


@asynccontextmanager
async def _open_candidate_store_service(
    context: HostServiceFactoryContext,
):
    if (
        context.provider_id != "prime-applications"
        or context.application_id != "prime.continual-improvement"
        or context.application_version != "1.0.0"
        or context.capability_id != "prime.candidate-store"
    ):
        raise CandidateStoreServiceError(
            "candidate-store context identity is invalid"
        )
    limits = _resolve_candidate_store_limits(context)
    scope_kind = _read_scope_kind(context)
    global_activation_approved = _read_global_activation(context)
    if scope_kind == "project":
        scope = HarnessScope.project("prime.continual-improvement")
    elif scope_kind == "session":
        scope = HarnessScope.session("prime.continual-improvement")
    else:
        scope = HarnessScope.global_scope()

    # The wrapper composes over the framework-owned coordinator. The
    # no-op effect sender is the default path; the witness replaces it
    # with a deterministic fake-worker through the registry. Tests
    # construct the wrapper directly and supply their own coordinator.
    coordinator = HarnessCoordinator(
        journal=_default_coordinator_journal(),
        scope=scope,
        effect_sender=_no_op_effect_sender,
        cancellation_signal=None,
    )
    service = CandidateStoreLoop(
        limits=limits,
        opened_at_iso=datetime.now(tz=timezone.utc).isoformat(),
        scope=scope,
        coordinator=coordinator,
        global_activation_approved=global_activation_approved,
    )
    try:
        yield service
    finally:
        # No subprocess supervisor — the in-process coordinator is the
        # default path (mirror of P5's asyncio loop default).
        service._candidate_revision = None
        service._holdout_result = None
        service._promotion_revision = None
        service._rollback_revision = None


def _no_op_effect_sender(proposal: HarnessProposal):  # pragma: no cover
    """Default effect sender used when the host service is opened with no
    overrides. Real callers (the runtime binding Task 9) inject a
    ``prime.pi-extension`` sender through the wrapper's coordinator; this
    default keeps the in-process path safe when neither the witness nor
    the operator has wired one yet.
    """

    raise CandidateStoreServiceError(
        "candidate-store effect sender is not configured"
    )


def _default_coordinator_journal():
    """Return an in-memory canonical journal for the default coordinator.

    The host-service surface does not own a private-root identity; tests
    construct the wrapper directly with a wired coordinator. The default
    coordinator exists only so the wrapper can be opened through the
    registry without an injected effect sender (the registry path is
    used by integration tests only; the witness injects a deterministic
    fake-worker through the operator's runtime binding).
    """

    from asterion.control.journal import JournalRecord, MemoryCanonicalJournal

    journal = MemoryCanonicalJournal("prime.candidate-store")
    journal.append(
        0,
        JournalRecord.system_bound(
            system_id="prime.candidate-store",
            system_version="1.0.0",
        ),
    )
    journal.append(
        1,
        JournalRecord.authority_bound(
            authority_id="prime.candidate-store",
            authority_revision=1,
        ),
    )
    return journal


def create_candidate_store_host_service() -> HostServiceFactoryBinding:
    """Return the exact factory binding for ``prime.candidate-store``."""

    return HostServiceFactoryBinding(
        capability_id="prime.candidate-store",
        option_names=(
            "max_candidate_revisions_per_run",
            "max_holdout_evaluations_per_run",
            "max_rollback_invocations_per_run",
            "max_actions",
            "max_usage_provider_ops",
            "max_deadline_ms",
            "max_cost_usd",
            "scope",
            "global_activation_approved",
        ),
        factory=_open_candidate_store_service,
    )


def create_candidate_store_host_service_for_test(  # pragma: no cover - test convenience
    *,
    limits: _CandidateStoreLimits,
    opened_at_iso: str,
    scope: HarnessScope,
    coordinator: HarnessCoordinator,
    global_activation_approved: bool,
    holdout_callable: HoldoutCallable | None = None,
) -> CandidateStoreLoop:
    """Build a :class:`CandidateStoreLoop` directly.

    Tests inject their own coordinator and holdout callable so the
    wrapper's composition over the framework-owned
    ``HarnessCoordinator`` is exercised without the registry / context-
    validation overhead. Not part of the public host-service surface.
    """

    return CandidateStoreLoop(
        limits=limits,
        opened_at_iso=opened_at_iso,
        scope=scope,
        coordinator=coordinator,
        global_activation_approved=global_activation_approved,
        holdout_callable=holdout_callable,
    )
