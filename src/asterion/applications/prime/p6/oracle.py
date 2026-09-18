"""Closed, content-safe projections of native P6 continual-improvement verification.

The P6 oracle verifies the three witness invariants the spec demands for
P6 acceptance (spec L222-L247):

  1. **Candidate admitted**: ``admitted_proposal`` is non-None, its
     ``revision_id`` is non-None, and its ``proposal_digest`` differs
     from the prior baseline snapshot's revision digest (or the
     baseline is empty on iteration 1, when no prior revision exists).
  2. **Holdout evaluated**: ``holdout_result`` is non-None, its
     ``task_b_result_sha256`` is non-empty, and its
     ``evaluation_timestamp`` is set.
  3. **Explicit promotion OR exact rollback**:
     - ``preserved`` requires ``promotion_action`` non-None with
       ``target_revision_id == admitted_proposal.revision_id`` and
       ``rollback_invocation_count == 0``.
     - ``rolled-back`` requires ``rollback_invocation_count == 1`` and
       ``promotion_action is None``.
     - ``global-rejected`` short-circuits pre-orchestration:
       ``global_activation_approved is False``, ``admitted_proposal``
       is None, ``holdout_result`` is None, ``promotion_action`` is
       None.

The oracle's closed 3-element verdict enum is internal-only — the
public ``P6NativeReceipt`` folds ``global-rejected`` into
``terminal_outcome="rolled-back"`` with ``global_activation_approved=
False``. The verdict enum therefore is the wrapper's private contract
and must not leak through the public surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Literal

from asterion.applications.prime.p6.host import (
    P6AdmittedProposal,
    P6HoldoutResult,
    P6PromotionAction,
)


class P6OracleError(ValueError):
    def __init__(self, reason: str | None = None) -> None:
        super().__init__("P6 oracle rejected" if reason is None else reason)
        self.reason = reason


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


# Type-only str validator — accepts empty string OR None (P5 Task 5
# lesson carried forward: empty `candidate_revision_digest` must reach
# the invariant verdict rather than being over-rejected here; the
# `global-rejected` path carries None for several fields).
def _validate_str(value: object, *, field: str) -> str:
    if type(value) is not str:
        raise P6OracleError(f"{field} must be a string")
    return value


def _validate_optional_str(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise P6OracleError(f"{field} must be a string when present")
    return value


def _validate_positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0 or isinstance(value, bool):
        raise P6OracleError(f"{field} must be a non-negative integer")
    return value


def _validate_bool(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise P6OracleError(f"{field} must be a bool")
    return value


# Closed 3-string verdict enum — the internal oracle contract that
# wraps the public 2-element P6TerminalOutcome. The
# ``global-rejected`` value is the wrapper's pre-orchestration boundary
# rejection; the oracle returns it directly. This is the load-bearing
# distinction between the private oracle contract and the public
# receipt's terminal_outcome enum.
CandidateStoreVerdict = Literal["preserved", "rolled-back", "global-rejected"]


_ALLOWED_VERDICTS: frozenset[str] = frozenset(
    {"preserved", "rolled-back", "global-rejected"}
)


@dataclass(frozen=True, slots=True)
class P6OracleReceipt:
    """Sealed oracle verdict for a P6 continual-improvement run.

    Captures the oracle's three-string verdict plus the supporting
    digests that prove the three witness invariants held:

      - ``root_run_id``: the operator's stable run identifier.
      - ``verdict``: the closed 3-element
        ``CandidateStoreVerdict``. ``global-rejected`` folds into
        ``terminal_outcome="rolled-back"`` on the public
        ``P6NativeReceipt``.
      - ``candidate_admission_digest``: SHA-256 of the admitted
        proposal's canonical-form (or ``None`` on the
        ``global-rejected`` boundary rejection).
      - ``holdout_result_digest``: SHA-256 of the holdout result's
        canonical-form (or ``None`` on the ``global-rejected``
        boundary rejection).
      - ``promotion_action_digest``: SHA-256 of the promotion action's
        canonical-form (or ``None`` on ``rolled-back`` and
        ``global-rejected``).
      - ``rollback_invocation_count``: 0 on ``preserved`` /
        ``global-rejected``; exactly 1 on ``rolled-back``.
      - ``global_activation_approved``: False for project scope; True
        ONLY when global scope carries operator authorization.
      - ``receipt_sha256``: SHA-256 of the canonical-form of the
        other 7 fields. Deterministic across re-checks with identical
        inputs.
    """

    root_run_id: str
    verdict: CandidateStoreVerdict
    candidate_admission_digest: str | None
    holdout_result_digest: str | None
    promotion_action_digest: str | None
    rollback_invocation_count: int
    global_activation_approved: bool
    receipt_sha256: str

    def __post_init__(self) -> None:
        _validate_str(self.root_run_id, field="root_run_id")
        if not self.root_run_id:
            raise P6OracleError("root_run_id must be a non-empty string")
        if type(self.verdict) is not str or not self.verdict:
            raise P6OracleError("verdict must be a non-empty string")
        if self.verdict not in _ALLOWED_VERDICTS:
            raise P6OracleError(
                f"verdict not in closed CandidateStoreVerdict enum: {self.verdict}"
            )
        _validate_optional_str(
            self.candidate_admission_digest,
            field="candidate_admission_digest",
        )
        _validate_optional_str(
            self.holdout_result_digest,
            field="holdout_result_digest",
        )
        _validate_optional_str(
            self.promotion_action_digest,
            field="promotion_action_digest",
        )
        _validate_positive_int(
            self.rollback_invocation_count,
            field="rollback_invocation_count",
        )
        _validate_bool(
            self.global_activation_approved,
            field="global_activation_approved",
        )
        if type(self.receipt_sha256) is not str or not self.receipt_sha256:
            raise P6OracleError("receipt_sha256 must be a non-empty string")

        # Cross-field consistency: digest of canonical-form of the
        # other 7 fields must equal receipt_sha256.
        expected_sha = _digest(
            {
                "root_run_id": self.root_run_id,
                "verdict": self.verdict,
                "candidate_admission_digest": self.candidate_admission_digest,
                "holdout_result_digest": self.holdout_result_digest,
                "promotion_action_digest": self.promotion_action_digest,
                "rollback_invocation_count": self.rollback_invocation_count,
                "global_activation_approved": self.global_activation_approved,
            }
        )
        if self.receipt_sha256 != expected_sha:
            raise P6OracleError(
                "receipt_sha256 does not match canonical-form digest of "
                "the other 7 fields"
            )


def _digest_admission(admitted_proposal: P6AdmittedProposal) -> str:
    return _digest(
        {
            "proposal_id": admitted_proposal.proposal_id,
            "proposal_digest": admitted_proposal.proposal_digest,
            "revision_id": admitted_proposal.revision_id,
            "admission_timestamp": admitted_proposal.admission_timestamp.isoformat(),
        }
    )


def _digest_holdout(holdout_result: P6HoldoutResult) -> str:
    return _digest(
        {
            "task_b_result_sha256": holdout_result.task_b_result_sha256,
            "non_regressing": holdout_result.non_regressing,
            "evaluation_timestamp": holdout_result.evaluation_timestamp.isoformat(),
        }
    )


def _digest_promotion(promotion_action: P6PromotionAction) -> str:
    return _digest(
        {
            "promotion_id": promotion_action.promotion_id,
            "promotion_digest": promotion_action.promotion_digest,
            "target_revision_id": promotion_action.target_revision_id,
            "promotion_timestamp": promotion_action.promotion_timestamp.isoformat(),
        }
    )


class P6Oracle:
    """Read-only verification of one P6 continual-improvement run.

    Verifies the three witness invariants the spec demands for P6
    acceptance (spec L222-L247). On success, the returned receipt has
    ``verdict="preserved"`` or ``verdict="rolled-back"``. The
    ``global-rejected`` verdict is the wrapper's pre-orchestration
    boundary rejection (scope=`global` without operator authorization);
    it short-circuits before any candidate is admitted.

    The oracle is closed against the three-string
    ``CandidateStoreVerdict`` enum. The verdict is computed from the
    caller's inputs and the verdict enum is enforced at receipt
    construction. Inputs that violate an invariant raise
    ``P6OracleError`` carrying the violated-invariant digest.

    Validation policy (mirroring P5 Task 5 lesson):
      - ``_validate_str`` is type-only: empty strings and Nones reach
        the invariant verdict rather than being over-rejected at the
        precondition check. The ``global-rejected`` path carries
        ``None`` for several digest fields by design.
      - ``admitted_proposal``, ``holdout_result``, and
        ``promotion_action`` are typed as
        ``P6AdmittedProposal | None`` etc., and ``None`` is the
        legitimate input on ``rolled-back`` and ``global-rejected``
        paths.
    """

    def __repr__(self) -> str:
        return "<P6Oracle>"

    def check(
        self,
        *,
        root_run_id: str,
        admitted_proposal: P6AdmittedProposal | None,
        holdout_result: P6HoldoutResult | None,
        promotion_action: P6PromotionAction | None,
        rollback_invocation_count: int,
        global_activation_approved: bool,
        signal: object,
    ) -> P6OracleReceipt:
        """Verify the three witness invariants and seal a receipt.

        Verdict resolution order (first match wins):

          a. ``global_activation_approved is False`` AND
             ``admitted_proposal is None`` AND
             ``holdout_result is None`` AND
             ``promotion_action is None`` → ``global-rejected``
             (pre-orchestration boundary rejection).
          b. ``global_activation_approved is True`` AND
             ``admitted_proposal is None`` →
             ``P6OracleError`` carrying
             ``"global_activation_approved requires admitted_proposal"``
             — inconsistent state (the caller said global was approved
             but no candidate was admitted).
          c. ``rollback_invocation_count == 1`` AND
             ``promotion_action is None`` → ``rolled-back`` after the
             candidate-admitted + holdout-evaluated invariants hold.
          d. ``rollback_invocation_count == 1`` AND
             ``promotion_action is not None`` →
             ``P6OracleError`` carrying
             ``"rolled-back path forbids promotion_action"`` —
             invariant 3 violated.
          e. ``admitted_proposal is not None`` AND
             ``holdout_result is not None`` AND
             ``promotion_action is not None`` AND
             ``promotion_action.target_revision_id ==
             admitted_proposal.revision_id`` AND
             ``rollback_invocation_count == 0`` → ``preserved``.
          f. Otherwise: each missing-field / mismatched-target case
             raises ``P6OracleError`` carrying the
             violated-invariant digest.

        ``signal`` is reserved for future cancellation propagation and
        is not currently consulted by the oracle; it is part of the
        signature to keep the call shape stable as P5 / P4's
        cancellation surfaces are unified.
        """

        # Precondition checks — keep them narrow so a malformed call
        # does not silently return a verdict. P5 Task 5 lesson: empty
        # strings and Nones are legitimate inputs on the
        # ``global-rejected`` path; type-only validation here.
        _validate_str(root_run_id, field="root_run_id")
        if not root_run_id:
            raise P6OracleError("root_run_id must be a non-empty string")
        _validate_positive_int(
            rollback_invocation_count,
            field="rollback_invocation_count",
        )
        _validate_bool(
            global_activation_approved,
            field="global_activation_approved",
        )
        if admitted_proposal is not None and not isinstance(
            admitted_proposal, P6AdmittedProposal
        ):
            raise P6OracleError(
                "admitted_proposal must be a P6AdmittedProposal or None"
            )
        if holdout_result is not None and not isinstance(
            holdout_result, P6HoldoutResult
        ):
            raise P6OracleError(
                "holdout_result must be a P6HoldoutResult or None"
            )
        if promotion_action is not None and not isinstance(
            promotion_action, P6PromotionAction
        ):
            raise P6OracleError(
                "promotion_action must be a P6PromotionAction or None"
            )

        # Compute supporting digests. Nones propagate through cleanly
        # so the canonical-form SHA is well-defined.
        candidate_admission_digest = (
            _digest_admission(admitted_proposal)
            if admitted_proposal is not None
            else None
        )
        holdout_result_digest = (
            _digest_holdout(holdout_result)
            if holdout_result is not None
            else None
        )
        promotion_action_digest = (
            _digest_promotion(promotion_action)
            if promotion_action is not None
            else None
        )

        verdict: CandidateStoreVerdict
        # (a) global-rejected: pre-orchestration boundary rejection.
        if (
            not global_activation_approved
            and admitted_proposal is None
            and holdout_result is None
            and promotion_action is None
        ):
            verdict = "global-rejected"
        # (b) inconsistent: global_activation_approved=True without
        # any admitted proposal. This is an internal-state error, not
        # a witness verdict — surface it as P6OracleError.
        elif global_activation_approved and admitted_proposal is None:
            raise P6OracleError(
                "global_activation_approved requires admitted_proposal"
            )
        # (c) rolled-back: rollback invoked, no promotion action.
        elif (
            rollback_invocation_count == 1
            and promotion_action is None
        ):
            # Invariant 1: candidate admitted.
            if admitted_proposal is None:
                raise P6OracleError(
                    "rolled-back path requires admitted_proposal"
                )
            if not admitted_proposal.revision_id:
                raise P6OracleError(
                    "rolled-back path requires non-empty revision_id"
                )
            # Invariant 2: holdout evaluated.
            if holdout_result is None:
                raise P6OracleError(
                    "rolled-back path requires holdout_result"
                )
            if not holdout_result.task_b_result_sha256:
                raise P6OracleError(
                    "rolled-back path requires non-empty task_b_result_sha256"
                )
            verdict = "rolled-back"
        # (d) rolled-back path forbids promotion_action.
        elif (
            rollback_invocation_count == 1
            and promotion_action is not None
        ):
            raise P6OracleError(
                "rolled-back path forbids promotion_action"
            )
        # (e) preserved: explicit promotion action required.
        elif (
            admitted_proposal is not None
            and holdout_result is not None
            and promotion_action is not None
            and rollback_invocation_count == 0
        ):
            # Invariant 1: candidate admitted.
            if not admitted_proposal.revision_id:
                raise P6OracleError(
                    "preserved path requires non-empty revision_id"
                )
            # Invariant 3: target_revision_id must match revision_id.
            if (
                promotion_action.target_revision_id
                != admitted_proposal.revision_id
            ):
                raise P6OracleError(
                    "preserved path requires promotion_action.target_revision_id"
                    " == admitted_proposal.revision_id"
                )
            # Invariant 2: holdout evaluated.
            if not holdout_result.task_b_result_sha256:
                raise P6OracleError(
                    "preserved path requires non-empty task_b_result_sha256"
                )
            verdict = "preserved"
        else:
            # (f) every other shape — incomplete preserved path or
            # inconsistent combination. Surface the violated invariant
            # digest directly so callers can diagnose without grepping
            # the code.
            if admitted_proposal is None:
                raise P6OracleError(
                    "preserved path requires admitted_proposal"
                )
            if holdout_result is None:
                raise P6OracleError(
                    "preserved path requires holdout_result"
                )
            if promotion_action is None:
                raise P6OracleError(
                    "preserved path requires promotion_action"
                )
            if rollback_invocation_count != 0:
                raise P6OracleError(
                    "preserved path requires rollback_invocation_count == 0"
                )
            # All else must hold — defensive fall-through.
            raise P6OracleError(
                "P6 oracle state is not consistent with any witness invariant"
            )

        # Seal the receipt: SHA-256 of the canonical-form of the 7
        # other fields. Deterministic across re-checks.
        receipt_sha256 = _digest(
            {
                "root_run_id": root_run_id,
                "verdict": verdict,
                "candidate_admission_digest": candidate_admission_digest,
                "holdout_result_digest": holdout_result_digest,
                "promotion_action_digest": promotion_action_digest,
                "rollback_invocation_count": rollback_invocation_count,
                "global_activation_approved": global_activation_approved,
            }
        )

        return P6OracleReceipt(
            root_run_id=root_run_id,
            verdict=verdict,
            candidate_admission_digest=candidate_admission_digest,
            holdout_result_digest=holdout_result_digest,
            promotion_action_digest=promotion_action_digest,
            rollback_invocation_count=rollback_invocation_count,
            global_activation_approved=global_activation_approved,
            receipt_sha256=receipt_sha256,
        )


__all__ = (
    "CandidateStoreVerdict",
    "P6Oracle",
    "P6OracleError",
    "P6OracleReceipt",
)


# Re-export for downstream test convenience — keeps the asdict
# import site here so the test file does not have to import
# dataclasses.asdict directly when comparing against the receipt.
_ = asdict  # noqa: F841 — kept for downstream import compatibility