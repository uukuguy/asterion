"""Runtime-host Protocol + frozen dataclasses for native P6 continual-improvement.

The P6 operator exercises the host surface in a single process: open a
root ``HarnessCoordinator``, admit one candidate revision, evaluate one
holdout task B, then either preserve the candidate (via an explicit
promotion action) or apply an exact inverse rollback. There is no
cross-process continuation and no recovery semantics — those belong
to P4's ``prime.continuity-store`` host service and are not part of
P6's contract. P6 has no recovery.

This module mirrors P3 / P4 / P5's ``host.py`` shape (one
``@runtime_checkable`` Protocol plus frozen dataclasses), but with P6's
load-bearing surface: ``admit_candidate`` / ``evaluate_holdout`` /
``promote_or_rollback`` instead of P5's ``run_loop`` /
``report_loop_stopped`` and P3's ``run_root`` /
``report_admission_refused``.

The closed public ``terminal_outcome`` enum is a 2-element literal
(``preserved`` | ``rolled-back``). The oracle's 3-element internal
verdict enum (``preserved`` | ``rolled-back`` | ``global-rejected``)
does NOT leak through this module — the public surface expresses the
boundary rejection through ``terminal_outcome="rolled-back"`` plus a
``global_activation_approved=False`` flag carried on the sealed
``P6NativeReceipt``. The 2-element public enum is load-bearing; any
addition is a breaking change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol, runtime_checkable

from asterion.control.harness import HarnessEntryDescriptor
from asterion.runtime.host import CancellationSignal


# Closed 2-element terminal_outcome enum. Mirror of P5's
# P5TerminalReason discipline (a Literal[...] type alias) but smaller:
# any non-preserved outcome — including the oracle's internal
# ``global-rejected`` verdict, candidate-admission errors,
# holdout-evaluation errors, promotion-action errors, and cancellation
# — folds into ``"rolled-back"``. This keeps the public surface
# contract closed; new outcomes belong on the oracle's 3-element
# internal verdict enum, not here.
P6TerminalOutcome = Literal["preserved", "rolled-back"]


@dataclass(frozen=True, slots=True)
class P6AdmittedProposal:
    """Record of one candidate admitted through ``admit_candidate``.

    ``proposal_id`` is the operator-supplied stable identifier;
    ``proposal_digest`` is the canonical-form digest of the proposal
    payload; ``revision_id`` is the framework-owned ``HarnessCoordinator``
    revision identifier assigned on admission (``None`` would be
    rejected by the oracle's candidate-admitted invariant). The
    ``admission_timestamp`` carries the closed-clock timestamp the
    host service observed on admission.
    """

    proposal_id: str
    proposal_digest: str
    revision_id: str
    admission_timestamp: datetime


@dataclass(frozen=True, slots=True)
class P6BaselineSnapshot:
    """Closed-form baseline the holdout is evaluated against.

    ``snapshot_id`` is the framework-owned ``HarnessCoordinator``
    snapshot identifier (``None`` for the empty baseline before any
    admit). ``entries`` is a tuple of ``HarnessEntryDescriptor`` —
    frozen by tuple identity (and by the frozen dataclass) so the
    baseline is immutable once projected. Lists are rejected at
    construction time by the closed field type.
    """

    snapshot_id: str
    entries: tuple[HarnessEntryDescriptor, ...]


@dataclass(frozen=True, slots=True)
class P6CandidateRevision:
    """Candidate revision the holdout is evaluated on.

    ``revision_id`` and ``revision_digest`` are the framework-owned
    coordinator's identifiers. ``parent_revision_id`` is ``None`` on
    the first revision (no prior revision exists) and a non-empty
    string on every subsequent revision; the oracle keys on this
    distinction to prove the candidate differs from the empty
    baseline on iteration 1.
    """

    revision_id: str
    revision_digest: str
    parent_revision_id: str | None


@dataclass(frozen=True, slots=True)
class P6PromotionAction:
    """Explicit promotion action that flips the candidate to current.

    The promotion must name a specific ``target_revision_id`` — the
    P6 witness's third clause ("an improving candidate requires an
    explicit admitted promotion action before becoming current") is
    enforced by the oracle refusing a ``preserved`` receipt that does
    not carry this field. ``promotion_timestamp`` carries the
    closed-clock timestamp the host service observed on apply.
    """

    promotion_id: str
    promotion_digest: str
    target_revision_id: str
    promotion_timestamp: datetime


@dataclass(frozen=True, slots=True)
class P6HoldoutResult:
    """Result of one holdout task B evaluation.

    ``task_b_result_sha256`` is the 64-hex SHA-256 of canonical-form
    task B output. On the ``preserved`` path the oracle requires this
    to differ from the baseline snapshot digest (proves the candidate
    produced different output, not a replay). ``non_regressing`` is
    the boolean the oracle keys on to choose between
    ``preserved`` (True) and ``rolled-back`` (False).
    ``evaluation_timestamp`` carries the closed-clock timestamp the
    oracle observed on evaluation.
    """

    task_b_result_sha256: str
    non_regressing: bool
    evaluation_timestamp: datetime


@runtime_checkable
class P6RuntimeHost(Protocol):
    """Protocol surface the P6 operator exercises against a built runtime.

    Five methods, mirroring P3 / P4 / P5's shape but scoped to the
    admit → holdout → preserve-or-rollback lifecycle:

    - ``validate_runtime_services`` — pre-execution capability check
      (set-equality on the six required services; fail-closed on
      missing services).
    - ``admit_candidate`` — admit one candidate through the wrapped
      ``HarnessCoordinator``; the wrapper refuses a second admit
      within the same run (single-candidate limit per spec L161–L164).
    - ``evaluate_holdout`` — evaluate the candidate against task B;
      the wrapper refuses a second evaluation within the same run
      (single-holdout limit per spec L165–L168).
    - ``promote_or_rollback`` — apply the explicit promotion OR exact
      inverse rollback; the wrapper refuses a second rollback within
      the same run (one rollback maximum per spec L169–L171).
    - ``wait_finalization`` — bounded cleanup that transfers the
      terminal classification to the host.
    """

    def validate_runtime_services(self, services: Mapping[str, object]) -> None: ...

    def admit_candidate(
        self,
        *,
        root_run_id: str,
        candidate_proposal: object,
        signal: CancellationSignal,
    ) -> P6AdmittedProposal: ...

    def evaluate_holdout(
        self,
        *,
        root_run_id: str,
        candidate: P6CandidateRevision,
        baseline: P6BaselineSnapshot,
        signal: CancellationSignal,
    ) -> P6HoldoutResult: ...

    def promote_or_rollback(
        self,
        *,
        root_run_id: str,
        candidate: P6CandidateRevision,
        holdout: P6HoldoutResult,
        signal: CancellationSignal,
    ) -> P6PromotionAction: ...

    async def wait_finalization(
        self, *, signal: CancellationSignal
    ) -> None: ...


__all__ = (
    "P6AdmittedProposal",
    "P6BaselineSnapshot",
    "P6CandidateRevision",
    "P6HoldoutResult",
    "P6PromotionAction",
    "P6RuntimeHost",
    "P6TerminalOutcome",
)
