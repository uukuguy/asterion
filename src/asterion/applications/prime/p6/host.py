"""Typed candidate evidence and the operator-owned P6 workflow boundary.

The host uses one CandidateStoreLoop/HarnessCoordinator for admission, holdout,
promotion or rollback and oracle verification. The runtime invokes that whole
bounded operation through run_candidate; it never reconstructs revisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:
    from asterion.applications.prime.p6.receipt import P6NativeReceipt

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
    """Operator-owned candidate workflow with explicit materials and authority.

    One host retains one CandidateStoreLoop and HarnessCoordinator, evaluates
    the holdout, applies promotion or rollback and requires oracle acceptance.
    """

    def validate_runtime_services(self, services: Mapping[str, object]) -> None: ...

    async def run_candidate(
        self, *, root_run_id: str, signal: CancellationSignal
    ) -> P6NativeReceipt: ...


__all__ = (
    "P6AdmittedProposal",
    "P6BaselineSnapshot",
    "P6CandidateRevision",
    "P6HoldoutResult",
    "P6PromotionAction",
    "P6RuntimeHost",
    "P6TerminalOutcome",
)
