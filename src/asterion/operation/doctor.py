"""Closed, read-only doctor diagnostics with public-safe reports."""

from __future__ import annotations

import asyncio
import hashlib
import inspect as inspection
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from types import FunctionType
from typing import Protocol

from asterion.control.protocol import IDENTIFIER
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    MAX_SAFE_INTEGER,
    OperationProtocolError,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import OperationReconciliationContext


DOCTOR_REQUEST_KIND = "operation.doctor-request"
DOCTOR_REQUEST_PURPOSE = "operation.doctor"
DOCTOR_MAX_REQUEST_BYTES = 4096
_REQUEST_FIELDS = frozenset()
_DIAGNOSTIC_STATUSES = frozenset({"pass", "warn", "fail"})
_FORBIDDEN_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "body",
        "credential",
        "destination",
        "path",
        "prompt",
        "refresh_token",
        "text",
        "token",
    }
)
_FORBIDDEN_PROBE_MEMBERS = frozenset(
    {"fix", "write", "refresh", "install", "restart", "provider", "network"}
)
_EXCEPTION_DIGEST = hashlib.sha256(b"doctor-probe-exception").hexdigest()
_INVALID_RESULT_DIGEST = hashlib.sha256(b"doctor-probe-invalid-result").hexdigest()
_MISSING = object()


class DoctorOperationError(OperationProtocolError):
    """Raised without retaining probe implementation details or private evidence."""


class DoctorProbe(Protocol):
    """A read-only probe: the operation invokes exactly this inspection method."""

    check_id: str

    def inspect(self) -> DiagnosticResult: ...


@dataclass(frozen=True, repr=False)
class DiagnosticResult:
    """One body-free diagnostic outcome; evidence is retained only as a digest."""

    check_id: str
    status: str
    code: str
    evidence_sha256: str

    @classmethod
    def passed(cls, check_id: str, code: str, evidence: object) -> DiagnosticResult:
        return cls(check_id, "pass", code, _digest_evidence(evidence))

    @classmethod
    def warning(cls, check_id: str, code: str, evidence: object) -> DiagnosticResult:
        return cls(check_id, "warn", code, _digest_evidence(evidence))

    @classmethod
    def failed(cls, check_id: str, code: str, evidence: object) -> DiagnosticResult:
        return cls(check_id, "fail", code, _digest_evidence(evidence))

    def __repr__(self) -> str:
        return "DiagnosticResult(<redacted>)"


@dataclass(frozen=True, repr=False)
class DoctorReport:
    """Immutable sorted public report; it communicates diagnosis, never repair."""

    results: tuple[DiagnosticResult, ...]

    def __repr__(self) -> str:
        return "DoctorReport(<redacted>)"


def validate_doctor_request(value: object) -> Mapping[str, object]:
    """Validate a closed canonical request before accessing any injected probe."""

    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise DoctorOperationError("doctor request is invalid")
    _reject_forbidden_keys(value)
    if set(value) != _REQUEST_FIELDS:
        raise DoctorOperationError("doctor request fields are invalid")
    return MappingProxyType({})


def reduce_diagnostics(results: tuple[DiagnosticResult, ...]) -> DoctorReport:
    """Copy and validate a complete deterministic reduction without probe authority."""

    if type(results) is not tuple or not results:
        raise DoctorOperationError("doctor diagnostic results are invalid")
    copied = tuple(_copy_result(result) for result in results)
    ordered = tuple(sorted(copied, key=lambda result: result.check_id))
    if len({result.check_id for result in copied}) != len(copied):
        raise DoctorOperationError("doctor diagnostic results are not canonical")
    return DoctorReport(ordered)


class DoctorOperationService:
    """Run an exact selection of injected inspect-only probes and store a safe report."""

    feature_id = "operation.doctor"
    request_kind = DOCTOR_REQUEST_KIND
    request_purpose = DOCTOR_REQUEST_PURPOSE
    max_request_bytes = DOCTOR_MAX_REQUEST_BYTES

    def __init__(self, *, probes: Sequence[DoctorProbe]) -> None:
        if not isinstance(probes, Sequence) or isinstance(probes, (str, bytes, bytearray)):
            raise DoctorOperationError("doctor probes are invalid")
        captured: list[tuple[str, DoctorProbe]] = []
        for probe in probes:
            try:
                check_id = inspection.getattr_static(probe, "check_id", _MISSING)
                inspect_method = inspection.getattr_static(probe, "inspect", _MISSING)
                dynamic_lookup = (
                    inspection.getattr_static(probe, "__getattr__", _MISSING)
                    is not _MISSING
                )
                forbidden = any(
                    inspection.getattr_static(probe, member, _MISSING) is not _MISSING
                    for member in _FORBIDDEN_PROBE_MEMBERS
                )
            except Exception:
                raise DoctorOperationError("doctor probe is invalid") from None
            if (
                type(probe).__getattribute__ is not object.__getattribute__
                or dynamic_lookup
                or not _is_identifier(check_id)
                or type(inspect_method) is not FunctionType
                or forbidden
            ):
                raise DoctorOperationError("doctor probe is invalid")
            captured.append((check_id, probe))
        captured.sort(key=lambda pair: pair[0])
        if not captured or len({check_id for check_id, _ in captured}) != len(captured):
            raise DoctorOperationError("doctor probes are ambiguous")
        self._probes = tuple(captured)
        self._reports: tuple[DoctorReport, ...] = ()

    @property
    def reports(self) -> tuple[DoctorReport, ...]:
        return tuple(_copy_report(report) for report in self._reports)

    async def execute(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationReceipt:
        self._validate_transaction(transaction)
        validate_doctor_request(typed_request)
        results = tuple(self._inspect(check_id, probe) for check_id, probe in self._probes)
        report = reduce_diagnostics(results)
        self._reports += (_copy_report(report),)
        return _receipt(transaction, "succeeded", "doctor-report-ready")

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        return _receipt(transaction, "cancelled", "doctor-cancelled")

    async def reconcile(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        context: OperationReconciliationContext,
    ) -> OperationReceipt:
        self._validate_transaction(transaction)
        if (
            not isinstance(context, OperationReconciliationContext)
            or context.operation_id != transaction.operation_id
            or context.authority_revision != transaction.authority_revision
            or type(context.reconciliation_attempt) is not int
            or context.reconciliation_attempt < 1
            or context.reconciliation_attempt > MAX_SAFE_INTEGER
        ):
            raise DoctorOperationError("doctor reconciliation is invalid")
        del typed_request
        return _receipt(transaction, "failed", "doctor-reconciliation-unavailable")

    @staticmethod
    def _validate_transaction(transaction: object) -> None:
        if not isinstance(transaction, OperationTransaction):
            raise DoctorOperationError("doctor transaction is invalid")
        try:
            transaction.to_mapping()
        except Exception:
            raise DoctorOperationError("doctor transaction is invalid") from None
        if (
            transaction.feature_id != "operation.doctor"
            or transaction.request.request_kind != DOCTOR_REQUEST_KIND
            or transaction.request.purpose != DOCTOR_REQUEST_PURPOSE
            or transaction.request.media_type != "application/json"
            or transaction.request.byte_count > DOCTOR_MAX_REQUEST_BYTES
        ):
            raise DoctorOperationError("doctor transaction is invalid")

    @staticmethod
    def _inspect(check_id: str, probe: DoctorProbe) -> DiagnosticResult:
        try:
            result = probe.inspect()
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            raise
        except Exception:
            return DiagnosticResult(check_id, "fail", "probe-exception", _EXCEPTION_DIGEST)
        try:
            copied = _copy_result(result)
        except DoctorOperationError:
            return DiagnosticResult(check_id, "fail", "probe-invalid-result", _INVALID_RESULT_DIGEST)
        if copied.check_id != check_id:
            return DiagnosticResult(check_id, "fail", "probe-invalid-result", _INVALID_RESULT_DIGEST)
        return copied


def _copy_report(report: DoctorReport) -> DoctorReport:
    if type(report) is not DoctorReport or type(report.results) is not tuple:
        raise DoctorOperationError("doctor report is invalid")
    return DoctorReport(tuple(_copy_result(result) for result in report.results))


def _copy_result(result: object) -> DiagnosticResult:
    if type(result) is not DiagnosticResult:
        raise DoctorOperationError("doctor diagnostic result is invalid")
    if (
        not _is_identifier(result.check_id)
        or not _is_identifier(result.code)
        or result.status not in _DIAGNOSTIC_STATUSES
        or not _is_digest(result.evidence_sha256)
    ):
        raise DoctorOperationError("doctor diagnostic result is invalid")
    return DiagnosticResult(
        result.check_id, result.status, result.code, result.evidence_sha256
    )


def _receipt(
    transaction: OperationTransaction, status: str, reason_code: str
) -> OperationReceipt:
    return OperationReceipt.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "receipt_id": f"receipt-{transaction.operation_id}",
            "operation_id": transaction.operation_id,
            "request_ref": transaction.request.request_ref,
            "request_sha256": transaction.request.request_sha256,
            "purpose": transaction.request.purpose,
            "session_id": transaction.session_id,
            "client_id": transaction.client_id,
            "generation": transaction.generation,
            "authority_revision": transaction.authority_revision,
            "authority_id": transaction.authority_id,
            "idempotency_key": transaction.idempotency_key,
            "feature_id": transaction.feature_id,
            "status": status,
            "reason_code": reason_code,
            "receipt_ref": f"doctor-report-{transaction.operation_id}",
            "reconciliation_ref": None,
            "effect_counts": {counter: 0 for counter in EFFECT_COUNTERS},
            "completed_at": transaction.requested_at,
        }
    )


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key in _FORBIDDEN_KEYS:
                raise DoctorOperationError("doctor request contains a forbidden field")
            _reject_forbidden_keys(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_forbidden_keys(child)


def _digest_evidence(evidence: object) -> str:
    if not isinstance(evidence, str):
        raise DoctorOperationError("doctor evidence is invalid")
    return hashlib.sha256(evidence.encode("utf-8", "surrogatepass")).hexdigest()


def _is_identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
