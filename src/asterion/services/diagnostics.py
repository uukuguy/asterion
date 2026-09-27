"""Operator-injected, bounded private failure diagnostics.

Records contain identities only as digests. Exception messages and application
inputs must never be passed to this surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import uuid4


PRIVATE_FAILURE_CODES = frozenset(
    {
        "event_malformed",
        "model_callback_limit",
        "tool_callback_limit",
        "tool_call_invalid",
        "tool_result_invalid",
        "duplicate_terminal",
        "event_type_invalid",
        "message_update_malformed",
        "usage_malformed",
        "tool_call_malformed",
        "tool_result_malformed",
        "transport_protocol",
        "native_result_malformed",
        "native_terminal_invalid",
        "continuation_invalid",
    }
)


def bounded_failure_code(value: object) -> str | None:
    """Return one approved scalar code without preserving arbitrary text."""

    return value if type(value) is str and value in PRIVATE_FAILURE_CODES else None


@dataclass(frozen=True, slots=True)
class FailureDiagnostic:
    diagnostic_id: str
    stage: str
    exception_type: str
    subject_sha256: str
    capability_sha256: str | None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if bounded_failure_code(self.failure_code) != self.failure_code:
            raise ValueError("failure diagnostic code is invalid")


class DiagnosticSink(Protocol):
    def record(self, diagnostic: FailureDiagnostic) -> None: ...


class MemoryDiagnosticSink:
    """Process-local sink for an operator's private diagnostic store."""

    def __init__(self) -> None:
        self._records: dict[str, FailureDiagnostic] = {}

    def record(self, diagnostic: FailureDiagnostic) -> None:
        if not isinstance(diagnostic, FailureDiagnostic):
            raise TypeError("failure diagnostic is invalid")
        self._records[diagnostic.diagnostic_id] = diagnostic

    def get(self, diagnostic_id: str) -> FailureDiagnostic:
        return self._records[diagnostic_id]


def capture_failure(
    sink: DiagnosticSink | None,
    *,
    stage: str,
    error: Exception,
    subject_id: str,
    capability_ref: str | None = None,
    failure_code: object = None,
) -> str | None:
    """Return a correlation ID only when the optional sink accepted a record."""

    if sink is None:
        return None
    diagnostic_id = uuid4().hex
    record = FailureDiagnostic(
        diagnostic_id=diagnostic_id,
        stage=stage,
        exception_type=type(error).__name__[:80],
        subject_sha256=sha256(subject_id.encode("utf-8")).hexdigest(),
        capability_sha256=(
            None
            if capability_ref is None
            else sha256(capability_ref.encode("utf-8")).hexdigest()
        ),
        failure_code=bounded_failure_code(failure_code),
    )
    try:
        sink.record(record)
    except Exception:
        return None
    return diagnostic_id


__all__ = (
    "DiagnosticSink",
    "FailureDiagnostic",
    "MemoryDiagnosticSink",
    "PRIVATE_FAILURE_CODES",
    "bounded_failure_code",
    "capture_failure",
)
