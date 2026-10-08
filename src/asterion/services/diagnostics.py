"""Operator-injected, bounded private failure diagnostics.

Public-safe records contain identities only as digests and typed metadata.
Failure bodies enter only the separately injected, bounded private sink.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from collections.abc import Mapping
from typing import Protocol
from uuid import uuid4


_SAFE_PROVIDER_CODES = frozenset({
    "authentication_error", "permission_error", "invalid_request_error",
    "rate_limit_error", "overloaded_error", "server_error", "context_length_exceeded",
})
PRIVATE_FAILURE_EVENT_BYTES = 8 * 1024
PRIVATE_FAILURE_TOTAL_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class FailureMetadata:
    stage: str = "pi.prompt"
    event_type: str = "message_end"
    stop_reason: str | None = None
    http_status: int | None = None
    provider_code: str = "unknown"
    diagnostic_id: str | None = None
    native_retry_count: int = 0
    native_retry_exhausted: bool = False

    def __post_init__(self) -> None:
        if (self.stage != "pi.prompt" or self.event_type not in {"message_end", "auto_retry_end"}
                or self.stop_reason not in {None, "error", "aborted"}
                or (self.http_status is not None and (type(self.http_status) is not int or not 100 <= self.http_status <= 599))
                or self.provider_code not in _SAFE_PROVIDER_CODES | {"unknown"}
                or (self.diagnostic_id is not None and (type(self.diagnostic_id) is not str
                    or len(self.diagnostic_id) != 32 or any(c not in "0123456789abcdef" for c in self.diagnostic_id)))
                or type(self.native_retry_count) is not int or not 0 <= self.native_retry_count <= 65536
                or type(self.native_retry_exhausted) is not bool):
            raise ValueError("failure metadata is invalid")

    @property
    def permanent_rejection(self) -> bool:
        return self.http_status in {400, 401, 403, 404, 422} or self.provider_code in {
            "authentication_error", "permission_error", "invalid_request_error",
            "context_length_exceeded",
        }


@dataclass(frozen=True, slots=True, repr=False)
class PrivateFailureDiagnostic:
    metadata: FailureMetadata
    error_bytes: bytes
    observed_bytes: int
    retained_bytes: int
    truncated: bool

    def __repr__(self) -> str:
        return "<PrivateFailureDiagnostic redacted>"


class PrivateFailureSink(Protocol):
    def record(self, diagnostic: PrivateFailureDiagnostic) -> None: ...


def extract_failure_metadata(message: Mapping[str, object], *, event_type: str) -> FailureMetadata:
    """Use typed provider fields only; prose is never an HTTP witness."""
    error = message.get("error")
    sources = (message, error) if isinstance(error, Mapping) else (message,)
    status = None
    code = "unknown"
    for source in sources:
        for key in ("status", "statusCode", "httpStatus"):
            value = source.get(key)
            if type(value) is int and 100 <= value <= 599:
                status = value
                break
        value = source.get("code")
        if type(value) is str and value in _SAFE_PROVIDER_CODES:
            code = value
    stop = message.get("stopReason")
    return FailureMetadata(event_type=event_type, stop_reason=stop if type(stop) is str and stop in {"error", "aborted"} else None,
                           http_status=status, provider_code=code)


def capture_private_failure(sink: PrivateFailureSink | None, metadata: FailureMetadata,
                            message: Mapping[str, object], *, remaining_bytes: int) -> tuple[FailureMetadata, int]:
    if sink is None or remaining_bytes <= 0:
        return metadata, 0
    fields = {}
    for key in ("errorMessage", "finalError", "error"):
        value = message.get(key)
        if type(value) is str:
            fields[key] = value
        elif isinstance(value, Mapping):
            fields[key] = {name: item for name, item in value.items()
                           if name in {"message", "status", "statusCode", "httpStatus", "code"}
                           and type(item) in {str, int}}
    encoded = json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    limit = min(PRIVATE_FAILURE_EVENT_BYTES, remaining_bytes)
    retained = encoded[:limit]
    tagged = replace(metadata, diagnostic_id=uuid4().hex)
    try:
        sink.record(PrivateFailureDiagnostic(tagged, retained, len(encoded), len(retained), len(encoded) > len(retained)))
    except Exception:
        return metadata, 0
    return tagged, len(retained)


@dataclass(frozen=True, slots=True)
class FailureDiagnostic:
    diagnostic_id: str
    stage: str
    exception_type: str
    subject_sha256: str
    capability_sha256: str | None
    failure_code: str | None
    failure_metadata: FailureMetadata | None = None


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
    metadata = failure_metadata(error)
    diagnostic_id = (metadata.diagnostic_id if metadata is not None else None) or uuid4().hex
    failure_code = _failure_code(error)
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
        failure_code=failure_code,
        failure_metadata=metadata,
    )
    try:
        sink.record(record)
    except Exception:
        return None
    return diagnostic_id


def failure_metadata(error: BaseException) -> FailureMetadata | None:
    """Recover only the exact typed, safe metadata from a wrapped failure."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        metadata = getattr(current, "failure_metadata", None)
        if type(metadata) is FailureMetadata:
            return metadata
        current = current.__cause__
    return None


def _failure_code(error: Exception) -> str | None:
    """Classify known protocol failures without retaining their messages."""

    if failure_metadata(error) is not None:
        return "pi-provider-execution"
    native_message = getattr(error, "failure_code", None)
    native_codes = {
        "Asterion-prime native event is invalid": "prime-native-event",
        "Asterion-prime model callback limit exceeded": "prime-model-callback-limit",
        "Asterion-prime tool callback limit exceeded": "prime-tool-callback-limit",
        "Asterion-prime tool call is invalid": "prime-tool-call",
        "Asterion-prime tool result is invalid": "prime-tool-result",
        "Asterion-prime emitted duplicate terminal event": "prime-duplicate-terminal",
        "Asterion-prime native event type is invalid": "prime-event-type",
        "Asterion-prime message update is malformed": "prime-message-update",
        "Asterion-prime usage event is malformed": "prime-usage",
        "Asterion-prime tool call is malformed": "prime-tool-call-malformed",
        "Asterion-prime tool result is malformed": "prime-tool-result-malformed",
    }
    if type(native_message) is str:
        return native_codes.get(native_message, "prime-native-callback")
    if type(error).__name__ == "_CallbackRejected":
        return "prime-native-callback"
    if type(error).__name__ != "ProtocolError":
        return None
    message = str(error)
    known = {
        "Pi runtime provider execution failed": "pi-provider-execution",
        "Pi runtime process ended before completion": "pi-process-ended",
        "Pi runtime emitted invalid JSONL": "pi-invalid-jsonl",
        "Pi runtime emitted an invalid JSONL object": "pi-invalid-jsonl-object",
        "Pi runtime output limit exceeded": "pi-output-limit",
        "Pi runtime turn limit exceeded": "pi-turn-limit",
        "Pi runtime request deadline expired": "pi-deadline",
        "Asterion-prime transport protocol failed": "prime-transport-protocol",
        "Asterion-prime native result is malformed": "prime-native-result",
        "Asterion-prime native terminal is invalid": "prime-native-terminal",
        "Asterion-prime continuation is invalid": "prime-continuation",
    }
    return known.get(message, "protocol-error")


__all__ = (
    "DiagnosticSink",
    "FailureMetadata",
    "PrivateFailureDiagnostic",
    "PrivateFailureSink",
    "capture_private_failure",
    "extract_failure_metadata",
    "failure_metadata",
    "FailureDiagnostic",
    "MemoryDiagnosticSink",
    "capture_failure",
)
