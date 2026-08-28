from __future__ import annotations

import json
import unittest
from collections.abc import AsyncIterator, Mapping
from typing import cast

from asterion.control.providers.prime.client import (
    PrimeControlPlaneClient,
    PrimeSidecarTransport,
)
from asterion.control.providers.prime.operation import PrimeOperationClient, PrimeOperationError
from asterion.control.providers.prime.process import _encode_frame
from asterion.operation.protocol import OperationTransaction


def _transaction(operation_id: str = "operation-1", request_ref: str = "private-request-1") -> OperationTransaction:
    return OperationTransaction.from_mapping({
        "protocol": "asterion.operation/v1", "operation_id": operation_id,
        "request": {"protocol": "asterion.operation/v1", "request_kind": "doctor-request", "request_ref": request_ref, "request_sha256": "a" * 64, "media_type": "application/json", "byte_count": 2, "purpose": "operation.doctor.read", "client_id": "client-1", "session_id": "session-1", "generation": 1, "authority_revision": 1},
        "session_id": "session-1", "client_id": "client-1", "generation": 1,
        "authority_revision": 1, "authority_id": "authority-1", "idempotency_key": "idempotency-1", "feature_id": "operation.doctor", "requested_at": "2026-08-10T03:00:00Z",
    })


def _receipt(transaction: OperationTransaction, status: str = "succeeded") -> Mapping[str, object]:
    return {
        "protocol": "asterion.operation/v1", "receipt_id": f"receipt-{transaction.operation_id}", "operation_id": transaction.operation_id,
        "request_ref": transaction.request.request_ref, "request_sha256": transaction.request.request_sha256, "purpose": transaction.request.purpose,
        "session_id": transaction.session_id, "client_id": transaction.client_id, "generation": transaction.generation,
        "authority_revision": transaction.authority_revision, "authority_id": transaction.authority_id, "idempotency_key": transaction.idempotency_key,
        "feature_id": transaction.feature_id, "status": status, "reason_code": "operation-succeeded" if status == "succeeded" else "operation-uncertain",
        "receipt_ref": f"receipt-ref-{transaction.operation_id}", "reconciliation_ref": "reconcile-1" if status == "uncertain" else None,
        "effect_counts": {"credential_value_reads": 0, "provider_model_requests": 0, "network_operations": 0, "package_manager_operations": 0, "os_process_restart_operations": 0, "external_telemetry_deliveries": 0, "uploads": 0},
        "completed_at": "2026-08-10T03:00:01Z",
    }


class _Process:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []
        self.frames: list[bytes] = []

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        self.calls.append(envelope)
        self.frames.append(_encode_frame(envelope))
        transaction = envelope.get("transaction")
        if not isinstance(transaction, Mapping):
            raise RuntimeError("SENTINEL_SECRET")
        parsed = OperationTransaction.from_mapping(transaction)
        result = _receipt(parsed, "uncertain" if envelope["type"] == "operation.execute" and parsed.operation_id == "operation-uncertain" else "succeeded")
        return {"protocol": envelope["protocol"], "id": envelope["id"], "type": "operation.receipt", "receipt": result}


class _ObservationOnlyProcess:
    def __init__(self) -> None:
        self.event_requests: list[Mapping[str, object]] = []
        self.close_calls = 0

    def events(self, envelope: Mapping[str, object]) -> AsyncIterator[Mapping[str, object]]:
        self.event_requests.append(envelope)

        async def iterate() -> AsyncIterator[Mapping[str, object]]:
            if False:
                yield {}

        return iterate()

    async def close(self) -> None:
        self.close_calls += 1


class _Resolver:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        del reference, max_bytes
        return "private"


class TestPrimeOperationBridge(unittest.IsolatedAsyncioTestCase):
    async def test_control_client_defers_operation_binding_for_observation_only_sidecar(self) -> None:
        process = _ObservationOnlyProcess()
        client = PrimeControlPlaneClient(
            process=cast(PrimeSidecarTransport, process),
            private_content=_Resolver(),
        )

        self.assertEqual([item async for item in client.client_observations()], [])
        self.assertEqual(process.event_requests[0]["type"], "client_observations")
        await client.close()
        await client.close()
        self.assertEqual(process.close_calls, 1)
        with self.assertRaisesRegex(PrimeOperationError, "^Prime operation failed$") as raised:
            _ = client.operation_client
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_gateway_rejects_identity_conflict_without_reinvoking_private_operation(self) -> None:
        process = _Process()
        client = PrimeOperationClient(process)
        first = await client.execute(_transaction("operation-1"))
        with self.assertRaises(PrimeOperationError):
            await client.execute(_transaction("operation-1", "private-conflict"))
        self.assertEqual(first.status, "succeeded")
        self.assertEqual(len(process.calls), 1)
        wire = json.loads(process.frames[0])
        self.assertEqual(wire["transaction"], _transaction("operation-1").to_mapping())
        self.assertNotIn("SENTINEL_SECRET", process.frames[0].decode("utf-8"))

    async def test_gateway_reconciles_only_exact_uncertain_transaction(self) -> None:
        process = _Process()
        client = PrimeOperationClient(process)
        self.assertEqual((await client.execute(_transaction("operation-uncertain"))).status, "uncertain")
        receipt = await client.reconcile(_transaction("operation-uncertain"))
        self.assertEqual(receipt.status, "succeeded")
        reconcile_wire = json.loads(process.frames[-1])
        self.assertEqual(reconcile_wire["type"], "operation.reconcile")
        self.assertEqual(
            reconcile_wire["transaction"],
            _transaction("operation-uncertain").to_mapping(),
        )
        self.assertNotIn("SENTINEL_SECRET", process.frames[-1].decode("utf-8"))
        with self.assertRaises(PrimeOperationError):
            await client.reconcile(_transaction("operation-uncertain", "private-conflict"))
