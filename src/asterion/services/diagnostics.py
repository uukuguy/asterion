"""Operator-injected, bounded private failure diagnostics.

Records contain identities only as digests. Exception messages and application
inputs must never be passed to this surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class FailureDiagnostic:
    diagnostic_id: str
    stage: str
    exception_type: str
    subject_sha256: str
    capability_sha256: str | None


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
    "capture_failure",
)
