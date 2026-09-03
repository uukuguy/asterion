"""Closed bounded evidence for Prime autonomous goal completion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re

from asterion.applications.prime_agent.evidence import (
    PrimeEvidenceLevel,
    PrimeEvidenceReceipt,
)
from asterion.control.providers.prime.parity_testing import (
    build_prime_long_running_bounded_observation,
)
from asterion.applications.prime_agent.operator.bounded_autonomy_workload import (
    P5_BOUNDED_AUTONOMY_ACTION_CEILING,
    P5_BOUNDED_AUTONOMY_MODEL_SHA256,
    P5_BOUNDED_AUTONOMY_ORACLE_SHA256,
    P5_BOUNDED_AUTONOMY_SCHEMA_SHA256,
    P5_BOUNDED_AUTONOMY_USAGE_CEILING,
    P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST,
)


class BoundedAutonomyReceiptError(ValueError):
    """Raised when a bounded autonomy receipt cannot support the claim."""


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_TRACE_FIELDS = frozenset({
    "workload_sha256", "initial_workspace_sha256", "repaired_workspace_sha256",
    "failure_feedback_sha256", "gate_result_sha256", "oracle_sha256", "model_sha256",
    "schema_sha256", "tool_names", "action_count", "usage_count", "gate_count",
    "feedback_count", "terminal", "first_gate_failed", "second_gate_passed",
    "workspace_changed_before_second_gate", "disposed", "reaped",
})


@dataclass(frozen=True, repr=False)
class BoundedAutonomyTrace:
    workload_sha256: str
    initial_workspace_sha256: str
    repaired_workspace_sha256: str
    failure_feedback_sha256: str
    gate_result_sha256: str
    oracle_sha256: str
    model_sha256: str
    schema_sha256: str
    tool_names: tuple[str]
    action_count: int
    usage_count: int
    gate_count: int
    feedback_count: int
    terminal: bool
    first_gate_failed: bool
    second_gate_passed: bool
    workspace_changed_before_second_gate: bool
    disposed: bool
    reaped: bool

    def __repr__(self) -> str:
        return "BoundedAutonomyTrace(redacted)"


def validate_bounded_autonomy_trace(trace: object) -> None:
    """Validate the fixed two-gate P5 causal trace without issuing evidence."""

    if (
        type(trace) is not BoundedAutonomyTrace
        or frozenset(vars(trace)) != _TRACE_FIELDS
        or any(type(getattr(trace, name)) is not str or _DIGEST.fullmatch(getattr(trace, name)) is None for name in (
            "workload_sha256", "initial_workspace_sha256", "repaired_workspace_sha256",
            "failure_feedback_sha256", "gate_result_sha256", "oracle_sha256", "model_sha256", "schema_sha256",
        ))
        or trace.workload_sha256 != P5_BOUNDED_AUTONOMY_WORKLOAD_DIGEST
        or trace.model_sha256 != P5_BOUNDED_AUTONOMY_MODEL_SHA256
        or trace.oracle_sha256 != P5_BOUNDED_AUTONOMY_ORACLE_SHA256
        or trace.schema_sha256 != P5_BOUNDED_AUTONOMY_SCHEMA_SHA256
        or trace.initial_workspace_sha256 == trace.repaired_workspace_sha256
        or type(trace.tool_names) is not tuple or len(trace.tool_names) != 1 or type(trace.tool_names[0]) is not str or trace.tool_names[0] != "ipython"
        or type(trace.action_count) is not int or not 0 < trace.action_count <= P5_BOUNDED_AUTONOMY_ACTION_CEILING
        or type(trace.usage_count) is not int or not 0 < trace.usage_count <= P5_BOUNDED_AUTONOMY_USAGE_CEILING
        or type(trace.gate_count) is not int or trace.gate_count != 2
        or type(trace.feedback_count) is not int or trace.feedback_count != 1
        or any(getattr(trace, name) is not True for name in ("terminal", "first_gate_failed", "second_gate_passed", "workspace_changed_before_second_gate", "disposed", "reaped"))
    ):
        raise BoundedAutonomyReceiptError("bounded autonomy trace is invalid")


@dataclass(frozen=True, repr=False)
class BoundedAutonomyObservation:
    """Private normalized facts without goal, model, or provider content."""

    goal_completed: bool
    host_quiescent: bool
    orphan_audit_clean: bool
    provider_operation_count: int
    model_credential_read_count: int
    source_receipt_digest: str

    def __repr__(self) -> str:
        return "BoundedAutonomyObservation(redacted)"


def bounded_autonomy_observation_from_receipt(
    receipt: object,
) -> BoundedAutonomyObservation:
    """Reduce one exact finite provider receipt to non-sensitive facts."""

    if not isinstance(receipt, Mapping):
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid")
    try:
        observation = build_prime_long_running_bounded_observation(receipt)
    except Exception:
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid") from None
    if (
        observation.provider_operations != 1
        or observation.model_credential_reads != 1
        or observation.status != "PASS"
    ):
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid")
    return BoundedAutonomyObservation(
        goal_completed=True,
        host_quiescent=True,
        orphan_audit_clean=True,
        provider_operation_count=1,
        model_credential_read_count=1,
        source_receipt_digest="sha256:" + hashlib.sha256(json.dumps(
            dict(receipt), ensure_ascii=True, separators=(",", ":"), sort_keys=True,
        ).encode()).hexdigest(),
    )


def verify_bounded_autonomy_receipt(
    observation: object,
    worker_receipt: object | None = None,
    requested_level: PrimeEvidenceLevel = PrimeEvidenceLevel.BOUNDED_SANDBOXED,
) -> PrimeEvidenceReceipt:
    """Emit the sole bounded-sandboxed receipt for Prime autonomy."""

    if (
        type(observation) is not BoundedAutonomyObservation
        or type(requested_level) is not PrimeEvidenceLevel
        or requested_level is not PrimeEvidenceLevel.BOUNDED_SANDBOXED
        or observation.goal_completed is not True
        or observation.host_quiescent is not True
        or observation.orphan_audit_clean is not True
        or observation.provider_operation_count != 1
        or observation.model_credential_read_count != 1
    ):
        raise BoundedAutonomyReceiptError("bounded autonomy receipt is invalid")
    raise BoundedAutonomyReceiptError("bounded autonomy receipt is unavailable")
