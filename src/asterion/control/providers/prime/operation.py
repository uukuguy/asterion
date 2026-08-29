"""Closed, redacted client for generic private Prime operation IPC."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Mapping

from asterion.control.authority import operation_transaction_digest
from asterion.control.providers.prime.process import PRIME_GATEWAY_IPC_PROTOCOL
from asterion.operation.protocol import (
    OperationReceipt,
    OperationTransaction,
    validate_operation_receipt,
)


class PrimeOperationError(RuntimeError):
    """Raised without revealing an operation request, secret, or sidecar detail."""

    def __init__(self) -> None:
        super().__init__("Prime operation failed")


class PrimeOperationClient:
    """Private-operation IPC adapter with exact local replay fences."""

    def __init__(self, process: object) -> None:
        try:
            request = object.__getattribute__(process, "request")
        except Exception:
            request = None
        if not callable(request):
            raise PrimeOperationError()
        self._process = process
        self._records: dict[str, tuple[str, OperationTransaction, OperationReceipt]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def execute(self, transaction: OperationTransaction) -> OperationReceipt:
        return await self._request_transaction("operation.execute", transaction)

    async def reconcile(self, transaction: OperationTransaction) -> OperationReceipt:
        return await self._request_transaction("operation.reconcile", transaction)

    async def cancel(self, operation_id: str, *, authority_revision: int) -> OperationReceipt:
        if (
            not isinstance(operation_id, str)
            or type(authority_revision) is not int
            or authority_revision < 1
        ):
            raise PrimeOperationError()
        lock = self._locks.setdefault(operation_id, asyncio.Lock())
        async with lock:
            record = self._records.get(operation_id)
            if record is None or record[2].authority_revision != authority_revision:
                raise PrimeOperationError()
            if record[2].status != "uncertain":
                return record[2]
            envelope = {
                "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
                "id": _request_id(operation_id),
                "type": "operation.cancel",
                "operation_id": operation_id,
                "authority_revision": authority_revision,
                "private": {},
            }
            receipt = await self._send_receipt(envelope, record[0], record[1])
            self._records[operation_id] = (record[0], record[1], receipt)
            return receipt

    async def _request_transaction(
        self, operation: str, transaction: OperationTransaction
    ) -> OperationReceipt:
        if type(transaction) is not OperationTransaction:
            raise PrimeOperationError()
        try:
            digest = operation_transaction_digest(transaction)
        except Exception:
            raise PrimeOperationError() from None
        lock = self._locks.setdefault(transaction.operation_id, asyncio.Lock())
        async with lock:
            existing = self._records.get(transaction.operation_id)
            if existing is not None:
                if existing[0] != digest:
                    raise PrimeOperationError()
                if operation == "operation.execute":
                    return existing[2]
                if existing[2].status != "uncertain":
                    return existing[2]
            elif operation == "operation.reconcile":
                raise PrimeOperationError()
            envelope = {
                "protocol": PRIME_GATEWAY_IPC_PROTOCOL,
                "id": _request_id(transaction.operation_id),
                "type": operation,
                "transaction": _json_safe(transaction.to_mapping()),
                "private": {},
            }
            receipt = await self._send_receipt(envelope, digest, transaction)
            self._records[transaction.operation_id] = (digest, transaction, receipt)
            return receipt

    async def _send_receipt(
        self,
        envelope: Mapping[str, object],
        digest: str,
        expected: OperationTransaction,
    ) -> OperationReceipt:
        try:
            request = object.__getattribute__(self._process, "request")
            response = await request(dict(envelope))
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PrimeOperationError() from None
        try:
            if (
                not isinstance(response, Mapping)
                or set(response) != {"protocol", "id", "type", "receipt"}
                or response["protocol"] != PRIME_GATEWAY_IPC_PROTOCOL
                or response["id"] != envelope["id"]
                or response["type"] != "operation.receipt"
                or not isinstance(response["receipt"], Mapping)
            ):
                raise PrimeOperationError()
            receipt = OperationReceipt.from_mapping(response["receipt"])
            _require_transaction_receipt(receipt, expected)
            if operation_transaction_digest(expected) != digest:
                raise PrimeOperationError()
            validate_operation_receipt(receipt.to_mapping())
            return receipt
        except (KeyError, TypeError, ValueError):
            raise PrimeOperationError() from None


def _require_transaction_receipt(receipt: OperationReceipt, transaction: OperationTransaction) -> None:
    if (
        receipt.operation_id != transaction.operation_id
        or receipt.request_ref != transaction.request.request_ref
        or receipt.request_sha256 != transaction.request.request_sha256
        or receipt.purpose != transaction.request.purpose
        or receipt.session_id != transaction.session_id
        or receipt.client_id != transaction.client_id
        or receipt.generation != transaction.generation
        or receipt.authority_revision != transaction.authority_revision
        or receipt.authority_id != transaction.authority_id
        or receipt.idempotency_key != transaction.idempotency_key
        or receipt.feature_id != transaction.feature_id
    ):
        raise PrimeOperationError()


def _request_id(operation_id: str) -> str:
    if not isinstance(operation_id, str) or not operation_id:
        raise PrimeOperationError()
    return f"operation-{hashlib.sha256(operation_id.encode('utf-8')).hexdigest()}"


def _json_safe(value: object) -> object:
    """Copy the closed protocol snapshot into JSON-serializable builtins."""

    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise PrimeOperationError()
            copied[key] = _json_safe(child)
        return copied
    if isinstance(value, (tuple, list)):
        return [_json_safe(child) for child in value]
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise PrimeOperationError()
