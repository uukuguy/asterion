"""Authorization-gated reducer for real P3 recursive-review evidence."""

from __future__ import annotations

from dataclasses import dataclass

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel, PrimeEvidenceReceipt
from asterion.applications.prime_agent.recursive_workflow_receipt import (
    RecursiveWorkflowTrace,
    RecursiveWorkflowReceiptError,
    verify_real_recursive_workflow_trace,
)


class RecursiveCodeReviewLiveValidationError(ValueError):
    """Raised without exposing a live execution's private values."""


@dataclass(frozen=True, repr=False)
class RecursiveCodeReviewLiveAuthorization:
    """Operator-issued authority for one already-observed P3 execution."""

    platform_lock_sha256: str
    real_prime_rlm_ipython_attested: bool
    broker_quiescent: bool
    worker_destroyed: bool

    def __repr__(self) -> str:
        return "RecursiveCodeReviewLiveAuthorization(redacted)"


def validate_recursive_code_review_live_result(
    observation: object,
    authorization: object,
) -> PrimeEvidenceReceipt:
    """Issue bounded P3 evidence only from an explicitly authorized real trace.

    This reducer never starts a container, daemon, or model request.
    """

    if (
        type(observation) is not RecursiveWorkflowTrace
        or type(authorization) is not RecursiveCodeReviewLiveAuthorization
        or type(authorization.platform_lock_sha256) is not str
        or not authorization.platform_lock_sha256.startswith("sha256:")
        or authorization.real_prime_rlm_ipython_attested is not True
        or authorization.broker_quiescent is not True
        or authorization.worker_destroyed is not True
    ):
        raise RecursiveCodeReviewLiveValidationError("recursive review live evidence is invalid")
    try:
        return verify_real_recursive_workflow_trace(observation, PrimeEvidenceLevel.BOUNDED)
    except RecursiveWorkflowReceiptError:
        raise RecursiveCodeReviewLiveValidationError("recursive review live evidence is invalid") from None
