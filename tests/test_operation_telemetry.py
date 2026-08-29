from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from asterion.operation.protocol import EFFECT_COUNTERS, OperationReceipt, OperationTransaction
from asterion.operation.services import OperationReconciliationContext
from asterion.operation.telemetry import (
    TelemetryOperationError,
    TelemetryOperationService,
    TelemetryObservation,
    UsageSnapshot,
    validate_telemetry_usage_request,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "operation" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _telemetry_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "source_id": "application",
        "event_name": "usage.reported",
        "event_count": 1,
        "result_sha256": "b" * 64,
        "usage": {
            "aggregate_tokens": 12,
            "application_tokens": 12,
            "child_tokens": 0,
            "controller_tokens": 0,
            "cost_micros": 7,
        },
    }
    request.update(overrides)
    return request


def _telemetry_transaction(
    operation_id: str,
    *,
    feature_id: str = "operation.telemetry-usage",
    request_kind: str = "operation.telemetry-usage-request",
    purpose: str = "operation.telemetry-usage",
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


class _Sink:
    def __init__(self, *, error: BaseException | None = None, result: object = None) -> None:
        self.error = error
        self.result = result
        self.calls: list[TelemetryObservation] = []

    async def record(self, observation: TelemetryObservation) -> None:
        self.calls.append(observation)
        if self.error is not None:
            raise self.error
        return self.result  # type: ignore[reportReturnType]


class _MutatingSink:
    def __init__(self) -> None:
        self.calls: list[TelemetryObservation] = []

    async def record(self, observation: TelemetryObservation) -> None:
        self.calls.append(observation)
        object.__setattr__(observation, "source_id", "child")
        object.__setattr__(observation, "event_name", "message.available")
        object.__setattr__(observation, "event_count", 9_007_199_254_740_991)
        object.__setattr__(observation, "usage", UsageSnapshot(0, 0, 0, 0, 0))
        object.__setattr__(observation, "result_sha256", "c" * 64)
        object.__setattr__(observation, "delivery_status", "observation-failed")


class _CancellingSink:
    def __init__(self) -> None:
        self.calls: list[TelemetryObservation] = []

    async def record(self, observation: TelemetryObservation) -> None:
        self.calls.append(observation)
        raise asyncio.CancelledError("SENTINEL_CANCEL")


def _telemetry_service(*, sink: _Sink | None = None) -> tuple[TelemetryOperationService, _Sink]:
    injected = sink or _Sink()
    return TelemetryOperationService(sink=injected), injected


class TestTelemetryUsageRequest(unittest.TestCase):
    def test_request_is_closed_immutable_and_binds_source_attribution(self) -> None:
        request = validate_telemetry_usage_request(
            _fixture("valid-telemetry-usage-request.json")
        )
        self.assertEqual(
            set(request), {"source_id", "event_name", "event_count", "result_sha256", "usage"}
        )
        self.assertEqual(request["usage"]["aggregate_tokens"], 12)  # type: ignore[index]
        with self.assertRaises(TypeError):
            request["source_id"] = "child"  # type: ignore[index]
        with self.assertRaises(TelemetryOperationError) as raised:
            validate_telemetry_usage_request(
                _fixture("invalid-telemetry-usage-request-body.json")
            )
        self.assertNotIn("SENTINEL_BODY", str(raised.exception))

    def test_usage_rejects_boolean_negative_unsafe_and_cross_source_attribution(self) -> None:
        usage = _telemetry_request()["usage"]
        assert isinstance(usage, dict)
        bad_requests = (
            _telemetry_request(event_count=True),
            _telemetry_request(event_count=-1),
            _telemetry_request(event_count=9_007_199_254_740_992),
            _telemetry_request(usage={**usage, "application_tokens": True}),
            _telemetry_request(usage={**usage, "cost_micros": -1}),
            _telemetry_request(usage={**usage, "aggregate_tokens": 11}),
            _telemetry_request(usage={**usage, "child_tokens": 1}),
            _telemetry_request(source_id="unknown"),
            _telemetry_request(event_name="message.available"),
            _telemetry_request(result_sha256="B" * 64),
        )
        for request in bad_requests:
            with self.subTest(request=request):
                with self.assertRaises(TelemetryOperationError):
                    validate_telemetry_usage_request(request)


class TestTelemetryOperationService(unittest.IsolatedAsyncioTestCase):
    async def test_exact_transaction_binding_precedes_the_only_sink_call(self) -> None:
        invalid_transactions = {
            "feature": _telemetry_transaction("telemetry-feature", feature_id="operation.auth"),
            "kind": _telemetry_transaction("telemetry-kind", request_kind="operation.auth-request"),
            "purpose": _telemetry_transaction("telemetry-purpose", purpose="operation.auth"),
            "media": _telemetry_transaction("telemetry-media", media_type="text/plain"),
            "bytes": _telemetry_transaction("telemetry-bytes", byte_count=4097),
        }
        for name, transaction in invalid_transactions.items():
            with self.subTest(name=name):
                service, sink = _telemetry_service()
                with self.assertRaises(TelemetryOperationError):
                    await service.execute(transaction, _telemetry_request())
                self.assertEqual((sink.calls, service.effects.injected_sink_calls), ([], 0))

    async def test_observation_is_immutable_metadata_only_and_sink_is_called_once(self) -> None:
        service, sink = _telemetry_service()
        receipt = await service.execute(
            _telemetry_transaction("telemetry-1"), _telemetry_request()
        )

        self.assertIsInstance(receipt, OperationReceipt)
        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "telemetry-observed"))
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})
        self.assertEqual((len(sink.calls), service.effects.injected_sink_calls), (1, 1))
        observation = sink.calls[0]
        self.assertEqual(
            set(observation.to_mapping()),
            {"source_id", "event_name", "event_count", "usage", "result_sha256", "delivery_status"},
        )
        self.assertEqual(observation.delivery_status, "observation-recorded")
        self.assertEqual(observation.usage, UsageSnapshot(12, 12, 0, 0, 7))
        with self.assertRaises((AttributeError, TypeError)):
            observation.usage.aggregate_tokens = 13  # type: ignore[misc]
        with self.assertRaises(TypeError):
            observation.to_mapping()["source_id"] = "child"  # type: ignore[index]
        public = repr((receipt, observation.to_mapping()))
        for forbidden in ("body", "SENTINEL", "credential", "token-value"):
            self.assertNotIn(forbidden, public)

    async def test_sink_failure_is_observed_but_does_not_rewrite_completed_usage(self) -> None:
        service, sink = _telemetry_service(sink=_Sink(error=RuntimeError("SENTINEL_TOKEN")))

        receipt = await service.execute(
            _telemetry_transaction("telemetry-failure"), _telemetry_request()
        )

        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "telemetry-observation-failed"))
        self.assertEqual(receipt.effect_counts["external_telemetry_deliveries"], 0)
        self.assertEqual((len(sink.calls), service.effects.injected_sink_calls), (1, 1))
        self.assertEqual(service.observations[-1].delivery_status, "observation-failed")
        self.assertNotIn("SENTINEL_TOKEN", repr((receipt, service.observations)))

    async def test_hostile_sink_mutation_cannot_change_the_stored_observation_or_receipt(self) -> None:
        sink = _MutatingSink()
        service = TelemetryOperationService(sink=sink)

        receipt = await service.execute(
            _telemetry_transaction("telemetry-mutation"), _telemetry_request()
        )

        self.assertEqual((receipt.status, receipt.reason_code), ("succeeded", "telemetry-observed"))
        self.assertEqual(receipt.effect_counts, {counter: 0 for counter in EFFECT_COUNTERS})
        self.assertEqual((len(sink.calls), service.effects.injected_sink_calls), (1, 1))
        self.assertEqual(
            service.observations[-1].to_mapping(),
            {
                "source_id": "application",
                "event_name": "usage.reported",
                "event_count": 1,
                "usage": {
                    "aggregate_tokens": 12,
                    "application_tokens": 12,
                    "child_tokens": 0,
                    "controller_tokens": 0,
                    "cost_micros": 7,
                },
                "result_sha256": "b" * 64,
                "delivery_status": "observation-recorded",
            },
        )

    async def test_cancellation_during_sink_propagates_without_a_false_terminal_observation(self) -> None:
        sink = _CancellingSink()
        service = TelemetryOperationService(sink=sink)

        with self.assertRaises(asyncio.CancelledError):
            await service.execute(
                _telemetry_transaction("telemetry-cancelling"), _telemetry_request()
            )

        self.assertEqual((len(sink.calls), service.effects.injected_sink_calls), (1, 1))
        self.assertEqual(service.observations, ())

    async def test_hostile_sink_result_or_exception_cannot_forge_success_or_leak(self) -> None:
        for name, sink in (
            ("result", _Sink(result={"delivery_status": "delivered", "body": "SENTINEL_BODY"})),
            ("exception", _Sink(error=RuntimeError("SENTINEL_BODY"))),
        ):
            with self.subTest(name=name):
                service, injected = _telemetry_service(sink=sink)
                receipt = await service.execute(
                    _telemetry_transaction(f"telemetry-hostile-{name}"), _telemetry_request()
                )
                expected_reason = (
                    "telemetry-observed" if name == "result" else "telemetry-observation-failed"
                )
                self.assertEqual(receipt.reason_code, expected_reason)
                self.assertEqual((len(injected.calls), service.effects.injected_sink_calls), (1, 1))
                self.assertNotEqual(service.observations[-1].delivery_status, "delivered")
                self.assertNotIn("SENTINEL_BODY", repr((receipt, service.observations)))

    async def test_cancel_and_reconcile_do_not_call_sink_and_validate_context(self) -> None:
        service, sink = _telemetry_service()
        transaction = _telemetry_transaction("telemetry-cancel")
        with self.assertRaises(TelemetryOperationError):
            await service.cancel(_telemetry_transaction("telemetry-wrong", feature_id="operation.auth"))
        with self.assertRaises(TelemetryOperationError):
            await service.reconcile(
                transaction,
                _telemetry_request(),
                OperationReconciliationContext("other-operation", 1, 1),
            )
        for attempt in (True, 0, 9_007_199_254_740_992):
            with self.subTest(attempt=attempt):
                with self.assertRaises(TelemetryOperationError):
                    await service.reconcile(
                        transaction,
                        _telemetry_request(),
                        OperationReconciliationContext("telemetry-cancel", 1, attempt),
                    )
        reconciliation = await service.reconcile(
            transaction,
            _telemetry_request(),
            OperationReconciliationContext("telemetry-cancel", 1, 9_007_199_254_740_991),
        )
        self.assertEqual(
            (reconciliation.status, reconciliation.reason_code),
            ("failed", "telemetry-reconciliation-unavailable"),
        )
        receipt = await service.cancel(transaction)
        self.assertEqual((receipt.status, receipt.reason_code), ("cancelled", "telemetry-cancelled"))
        self.assertEqual((sink.calls, service.effects.injected_sink_calls), ([], 0))


if __name__ == "__main__":
    unittest.main()
