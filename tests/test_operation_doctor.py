from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from pathlib import Path

from asterion.operation.doctor import (
    DiagnosticResult,
    DoctorOperationError,
    DoctorOperationService,
    DoctorProbe,
    reduce_diagnostics,
    validate_doctor_request,
)
from asterion.operation.protocol import EFFECT_COUNTERS, OperationReceipt, OperationTransaction
from asterion.operation.services import OperationReconciliationContext


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "operation" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _doctor_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {}
    request.update(overrides)
    return request


def _doctor_transaction(
    operation_id: str,
    *,
    feature_id: str = "operation.doctor",
    request_kind: str = "operation.doctor-request",
    purpose: str = "operation.doctor",
    media_type: str = "application/json",
    byte_count: int = 512,
) -> OperationTransaction:
    return OperationTransaction.from_mapping(
        {
            "protocol": "asterion.operation/v1",
            "operation_id": operation_id,
            "request": {
                "protocol": "asterion.operation/v1",
                "request_kind": request_kind,
                "request_ref": f"request-{operation_id}",
                "request_sha256": "a" * 64,
                "media_type": media_type,
                "byte_count": byte_count,
                "purpose": purpose,
                "client_id": "client-1",
                "session_id": "session-1",
                "generation": 1,
                "authority_revision": 1,
            },
            "session_id": "session-1",
            "client_id": "client-1",
            "generation": 1,
            "authority_revision": 1,
            "authority_id": "authority-1",
            "idempotency_key": f"key-{operation_id}",
            "feature_id": feature_id,
            "requested_at": "2026-08-28T15:00:00Z",
        }
    )


class _Probe:
    def __init__(self, check_id: str, result: DiagnosticResult) -> None:
        self.check_id = check_id
        self.result = result
        self.calls = 0
        self.mutation_calls = 0

    def inspect(self) -> DiagnosticResult:
        self.calls += 1
        return self.result


class _ExceptionProbe:
    check_id = "storage.private"

    def inspect(self) -> DiagnosticResult:
        raise RuntimeError("SENTINEL_BODY")


class _CancellingProbe:
    check_id = "storage.private"

    def inspect(self) -> DiagnosticResult:
        raise asyncio.CancelledError("SENTINEL_CANCEL")


class _MutatingProbe:
    check_id = "storage.private"

    def __init__(self) -> None:
        self.calls = 0

    def inspect(self) -> DiagnosticResult:
        self.calls += 1
        result = DiagnosticResult.passed("storage.private", "ready", "private body")
        object.__setattr__(result, "check_id", "forged.check")
        object.__setattr__(result, "status", "fail")
        object.__setattr__(result, "code", "forged")
        object.__setattr__(result, "evidence_sha256", "f" * 64)
        return result


class _ForbiddenPropertyProbe:
    check_id = "storage.private"

    def __init__(self) -> None:
        self.member_calls = 0

    def inspect(self) -> DiagnosticResult:
        return DiagnosticResult.passed("storage.private", "ready", "storage")

    @property
    def network(self) -> None:
        self.member_calls += 1
        return None

    @property
    def write(self) -> None:
        self.member_calls += 1
        return None

    @property
    def fix(self) -> None:
        self.member_calls += 1
        return None


class _DynamicLookupProbe:
    check_id = "storage.private"

    def __init__(self) -> None:
        self.lookup_calls = 0

    def inspect(self) -> DiagnosticResult:
        return DiagnosticResult.passed("storage.private", "ready", "storage")

    def __getattr__(self, name: str) -> None:
        self.lookup_calls += 1
        return None


class _DescriptorProbe:
    def __init__(self) -> None:
        self.descriptor_calls = 0

    @property
    def check_id(self) -> str:
        self.descriptor_calls += 1
        return "storage.private"

    @property
    def inspect(self) -> object:
        self.descriptor_calls += 1
        return lambda: DiagnosticResult.passed("storage.private", "ready", "storage")


def _doctor_service(
    *, probes: tuple[DoctorProbe, ...] | None = None
) -> tuple[DoctorOperationService, tuple[DoctorProbe, ...]]:
    injected = probes or (
        _Probe("clock.monotonic", DiagnosticResult.passed("clock.monotonic", "ready", "clock")),
        _Probe("storage.private", DiagnosticResult.passed("storage.private", "ready", "storage")),
    )
    return DoctorOperationService(probes=injected), injected


class TestDoctorRequest(unittest.TestCase):
    def test_request_is_closed_immutable_and_canonical(self) -> None:
        request = validate_doctor_request(_fixture("valid-doctor-request.json"))
        self.assertEqual(request, {})
        with self.assertRaises(TypeError):
            request["fix"] = "repair"  # type: ignore[index]
        with self.assertRaises(DoctorOperationError) as raised:
            validate_doctor_request(_fixture("invalid-doctor-request-fix.json"))
        self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    def test_request_rejects_every_probe_selector_or_repair_field(self) -> None:
        for value in (
            _doctor_request(check_ids=["storage.private", "clock.monotonic"]),
            _doctor_request(check_ids=["storage.private", "storage.private"]),
            _doctor_request(check_ids=["Storage.private"]),
            _doctor_request(check_ids=[True]),
            _doctor_request(check_ids=[]),
            _doctor_request(fix="repair"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(DoctorOperationError):
                    validate_doctor_request(value)


class TestDoctorReduction(unittest.TestCase):
    def test_reduction_sorts_stable_results_and_uses_exact_evidence_digests(self) -> None:
        report = reduce_diagnostics(
            (
                DiagnosticResult.failed("storage.private", "not-ready", "private body"),
                DiagnosticResult.warning("clock.monotonic", "degraded", "clock body"),
            )
        )
        self.assertEqual(
            tuple((result.check_id, result.status, result.code) for result in report.results),
            (("clock.monotonic", "warn", "degraded"), ("storage.private", "fail", "not-ready")),
        )
        self.assertEqual(
            report.results[1].evidence_sha256,
            hashlib.sha256(b"private body").hexdigest(),
        )
        self.assertNotIn("private body", repr(report))

    def test_reduction_rejects_duplicate_noncanonical_and_forged_results(self) -> None:
        invalid = (
            (
                DiagnosticResult.passed("storage.private", "ready", "one"),
                DiagnosticResult.passed("storage.private", "ready", "two"),
            ),
            (DiagnosticResult.passed("Storage.private", "ready", "one"),),
            (DiagnosticResult.passed("storage.private", "Ready", "one"),),
        )
        for results in invalid:
            with self.subTest(results=results):
                with self.assertRaises(DoctorOperationError):
                    reduce_diagnostics(results)


class TestDoctorOperationService(unittest.IsolatedAsyncioTestCase):
    async def test_constructor_rejects_dynamic_and_descriptor_probe_members_without_touching_them(self) -> None:
        probes = (_ForbiddenPropertyProbe(), _DynamicLookupProbe(), _DescriptorProbe())
        for probe in probes:
            with self.subTest(probe=type(probe).__name__):
                with self.assertRaises(DoctorOperationError):
                    DoctorOperationService(probes=(probe,))  # type: ignore[arg-type]
        self.assertEqual(probes[0].member_calls, 0)
        self.assertEqual(probes[1].lookup_calls, 0)
        self.assertEqual(probes[2].descriptor_calls, 0)

    async def test_exact_transaction_binding_precedes_all_probe_calls(self) -> None:
        invalid_transactions = {
            "feature": _doctor_transaction("doctor-feature", feature_id="operation.auth"),
            "kind": _doctor_transaction("doctor-kind", request_kind="operation.auth-request"),
            "purpose": _doctor_transaction("doctor-purpose", purpose="operation.auth"),
            "media": _doctor_transaction("doctor-media", media_type="text/plain"),
            "bytes": _doctor_transaction("doctor-bytes", byte_count=4097),
        }
        for name, transaction in invalid_transactions.items():
            with self.subTest(name=name):
                service, probes = _doctor_service()
                with self.assertRaises(DoctorOperationError):
                    await service.execute(transaction, _doctor_request())
                self.assertEqual([probe.calls for probe in probes], [0, 0])  # type: ignore[attr-defined]

    async def test_doctor_reports_failed_probe_without_fix_or_private_value(self) -> None:
        probe = _Probe(
            "storage.private",
            DiagnosticResult.failed("storage.private", "not-ready", "SENTINEL_BODY"),
        )
        service, _ = _doctor_service(probes=(probe,))
        receipt = await service.execute(
            _doctor_transaction("doctor-1"), _doctor_request()
        )
        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "doctor-report-ready"))
        self.assertEqual(probe.mutation_calls, 0)
        self.assertEqual(probe.calls, 1)
        self.assertNotIn("SENTINEL_BODY", repr((receipt, service.reports)))

    async def test_probe_exception_is_one_redacted_failed_result_but_cancellation_propagates(self) -> None:
        service, _ = _doctor_service(probes=(_ExceptionProbe(),))
        receipt = await service.execute(
            _doctor_transaction("doctor-exception"), _doctor_request()
        )
        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "doctor-report-ready"))
        self.assertEqual(
            tuple((result.check_id, result.status, result.code) for result in service.reports[-1].results),
            (("storage.private", "fail", "probe-exception"),),
        )
        self.assertNotIn("SENTINEL_BODY", repr(service.reports))

        cancelling, _ = _doctor_service(probes=(_CancellingProbe(),))
        with self.assertRaises(asyncio.CancelledError):
            await cancelling.execute(
                _doctor_transaction("doctor-cancelled"), _doctor_request()
            )
        self.assertEqual(cancelling.reports, ())

    async def test_hostile_probe_cannot_mutate_stored_report_or_forge_a_check_id(self) -> None:
        probe = _MutatingProbe()
        service, _ = _doctor_service(probes=(probe,))
        receipt = await service.execute(
            _doctor_transaction("doctor-mutation"), _doctor_request()
        )
        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "doctor-report-ready"))
        self.assertEqual(
            tuple((result.check_id, result.status, result.code) for result in service.reports[-1].results),
            (("storage.private", "fail", "probe-invalid-result"),),
        )
        self.assertNotIn("forged.check", repr(service.reports))

    async def test_cancel_and_reconcile_are_read_only_and_validate_context(self) -> None:
        service, probes = _doctor_service()
        transaction = _doctor_transaction("doctor-cancel")
        with self.assertRaises(DoctorOperationError):
            await service.cancel(_doctor_transaction("wrong", feature_id="operation.auth"))
        with self.assertRaises(DoctorOperationError):
            await service.reconcile(
                transaction,
                _doctor_request(),
                OperationReconciliationContext("other-operation", 1, 1),
            )
        receipt = await service.cancel(transaction)
        self.assertEqual((receipt.status, receipt.reason_code), ("cancelled", "doctor-cancelled"))
        reconciliation = await service.reconcile(
            transaction,
            _doctor_request(),
            OperationReconciliationContext("doctor-cancel", 1, 1),
        )
        self.assertEqual(
            (reconciliation.status, reconciliation.reason_code),
            ("failed", "doctor-reconciliation-unavailable"),
        )
        self.assertEqual([probe.calls for probe in probes], [0, 0])  # type: ignore[attr-defined]
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})
        self.assertIsInstance(receipt, OperationReceipt)


if __name__ == "__main__":
    unittest.main()
