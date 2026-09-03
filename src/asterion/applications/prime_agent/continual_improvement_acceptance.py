"""Public projection identities for the fixed P6 acceptance product."""

from __future__ import annotations

from hashlib import sha256
import json
from collections.abc import Awaitable, Callable
from typing import cast

from asterion.control.harness import (
    HarnessCoordinator,
    HarnessRevision,
    HarnessScope,
    HarnessSnapshot,
)
from asterion.applications.prime_agent.continual_improvement_receipt import (
    ContinualImprovementTrace,
    validate_continual_improvement_trace,
)
from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
    validate_prime_evidence_receipt,
)


class ContinualImprovementAcceptanceError(ValueError):
    """Raised without disclosing Harness-private values."""


def _digest(value: object) -> str:
    return "sha256:" + sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def continual_improvement_snapshot_sha256(snapshot: object) -> str:
    """Return the canonical public projection digest for one Harness snapshot."""

    if type(snapshot) is not HarnessSnapshot:
        raise ContinualImprovementAcceptanceError("continual improvement acceptance is invalid")
    return _digest({
        "entries": [dict(entry.to_public_mapping()) for entry in snapshot.entries],
        "scope": dict(snapshot.scope.to_mapping()),
    })


def continual_improvement_scope_sha256(scope: object) -> str:
    """Return the canonical public identity for one Harness scope."""

    if type(scope) is not HarnessScope:
        raise ContinualImprovementAcceptanceError(
            "continual improvement acceptance is invalid"
        )
    return "sha256:" + scope.digest


def continual_improvement_revision_sha256(revision: object) -> str:
    """Return the canonical public projection digest for one Harness revision."""

    if type(revision) is not HarnessRevision:
        raise ContinualImprovementAcceptanceError("continual improvement acceptance is invalid")
    return _digest({
        "baseline_snapshot_id": revision.baseline_snapshot_id,
        "effect_digest": revision.effect_digest,
        "proposal_digest": revision.proposal_digest,
        "revision_id": revision.revision_id,
        "rollback_revision_id": revision.rollback_revision_id,
        "scope": dict(revision.scope.to_mapping()),
        "sequence": revision.sequence,
        "status": revision.status,
        "usage": dict(revision.usage),
    })


async def accept_continual_improvement(
    *, gate: object, trace: object, baseline_snapshot: object,
    candidate_snapshot: object, candidate_revision: object, disposed: object,
    reaped: object, coordinator: object | None = None,
) -> PrimeEvidenceReceipt:
    """Accept one complete preserved P6 fake chain as provider-free evidence."""

    try:
        if (
            type(trace) is not ContinualImprovementTrace
            or disposed is not True
            or reaped is not True
            or type(candidate_revision) is not HarnessRevision
        ):
            raise ValueError
        validate_continual_improvement_trace(trace)
        typed_candidate_revision = cast(HarnessRevision, candidate_revision)
        if (
            continual_improvement_snapshot_sha256(baseline_snapshot)
            != trace.baseline_snapshot_sha256
            or continual_improvement_snapshot_sha256(candidate_snapshot)
            != trace.candidate_snapshot_sha256
            or continual_improvement_revision_sha256(typed_candidate_revision)
            != trace.candidate_revision_sha256
            or type(baseline_snapshot) is not HarnessSnapshot
            or type(candidate_snapshot) is not HarnessSnapshot
            or continual_improvement_scope_sha256(baseline_snapshot.scope)
            != trace.scope_sha256
            or continual_improvement_scope_sha256(candidate_snapshot.scope)
            != trace.scope_sha256
            or continual_improvement_scope_sha256(typed_candidate_revision.scope)
            != trace.scope_sha256
            or baseline_snapshot.scope.kind != trace.scope_kind
            or candidate_snapshot.scope.kind != trace.scope_kind
            or typed_candidate_revision.scope.kind != trace.scope_kind
        ):
            raise ValueError
        evaluate = getattr(gate, "evaluate", None)
        if not callable(evaluate):
            raise ValueError
        passed, result_sha256 = await cast(
            Callable[[str], Awaitable[tuple[object, object]]], evaluate
        )(trace.candidate_snapshot_sha256)
        if (
            type(passed) is not bool
            or type(result_sha256) is not str
            or result_sha256 != trace.task_b_result_sha256
        ):
            raise ValueError
        if trace.outcome == "preserved":
            if passed is not True:
                raise ValueError
        elif trace.outcome == "rolled-back":
            if passed is not False or type(coordinator) is not HarnessCoordinator:
                raise ValueError
            rollback = coordinator.rollback(
                proposal_id=trace.rollback_proposal_id,
                authority_id=trace.rollback_authority_id,
                authority_revision=trace.rollback_authority_revision,
                target_revision_id=typed_candidate_revision.revision_id,
                rationale_ref="private:p6-rollback",
                rationale_digest=trace.rollback_rationale_sha256.removeprefix("sha256:"),
                expected_outcome_digest=trace.rollback_outcome_sha256.removeprefix("sha256:"),
            )
            if (
                rollback.status != "succeeded"
                or rollback.rollback_revision_id != typed_candidate_revision.revision_id
                or continual_improvement_snapshot_sha256(coordinator.snapshot())
                != trace.baseline_snapshot_sha256
            ):
                raise ValueError
        else:
            raise ValueError
        return validate_prime_evidence_receipt(PrimeEvidenceReceipt(
            "prime.continual-improvement/v1", PrimeEvidenceLevel.PROVIDER_FREE, "PASS"
        ))
    except Exception:
        raise ContinualImprovementAcceptanceError(
            "continual improvement acceptance is invalid"
        ) from None
