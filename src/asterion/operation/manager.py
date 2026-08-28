"""Host-owned, append-only operation dispatch and reconciliation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping

from asterion.control.authority import (
    AuthorityError,
    AuthorityLedger,
    OperationDecision,
    OperationSettlement,
    operation_transaction_digest,
)
from asterion.control.journal import (
    CanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
)
from asterion.operation.protocol import (
    EFFECT_COUNTERS,
    OperationProtocolError,
    OperationReceipt,
    OperationTransaction,
)
from asterion.operation.services import (
    OperationPrivateRequestResolver,
    OperationPrivateRequestStore,
    OperationReconciliationContext,
    OperationService,
)


class OperationManagerError(ValueError):
    """Raised without private request values when operation execution cannot proceed."""


class OperationManager:
    """One canonical authority-bound state machine; it owns no external capability."""

    def __init__(
        self,
        *,
        authority: AuthorityLedger,
        journal: CanonicalJournal,
        resolver: OperationPrivateRequestResolver,
        private_store: OperationPrivateRequestStore,
        services: Mapping[str, OperationService],
        now_ms: Callable[[], int],
        session_id: str,
        generation: int,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        if (
            not isinstance(authority, AuthorityLedger)
            or not callable(now_ms)
            or not isinstance(session_id, str)
            or type(generation) is not int
        ):
            raise OperationManagerError("operation manager construction is invalid")
        self._authority, self._journal, self._resolver, self._store = (
            authority,
            journal,
            resolver,
            private_store,
        )
        self._services, self._now_ms, self._session_id, self._generation = (
            dict(services),
            now_ms,
            session_id,
            generation,
        )
        self._cancelled = cancelled or (lambda: False)
        self._transactions: dict[str, OperationTransaction] = {}
        self._receipts: dict[str, OperationReceipt] = {}
        self._dispatched: set[str] = set()
        self._attempts: dict[str, int] = {}
        self.fail_after: str | None = None
        self._recover()

    async def execute(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        existing = self._transactions.get(transaction.operation_id)
        if existing is not None:
            if existing != transaction:
                raise OperationManagerError("operation transaction conflicts")
            receipt = self._receipts.get(transaction.operation_id)
            if receipt is not None:
                return receipt
            if transaction.operation_id in self._dispatched:
                return self._uncertain(transaction)
        else:
            self._append(JournalRecord.operation_transaction_accepted(transaction))
            self._transactions[transaction.operation_id] = transaction
        try:
            try:
                service = self._service(transaction)
            except OperationManagerError:
                return self._record_terminal(
                    self._receipt(transaction, "rejected", "request-not-supported"),
                    reserve=False,
                )
            decision = self._authority.evaluate_operation(
                transaction, now_ms=self._now_ms()
            )
            self._append(JournalRecord.operation_admitted(decision))
            if decision.status != "admitted":
                return self._record_terminal(
                    self._receipt(transaction, "rejected", decision.reason),
                    reserve=False,
                )
            self._append(JournalRecord.operation_reserved(decision))
            self._authority.reserve_operation(decision)
            try:
                typed = self._resolve(transaction, service)
            except OperationManagerError:
                return self._record_terminal(
                    self._receipt(transaction, "failed", "private-request-unavailable"),
                    reserve=True,
                )
            self._append(JournalRecord.operation_dispatch_started(transaction))
            self._dispatched.add(transaction.operation_id)
            if self.fail_after == "operation.dispatch.started":
                return self._uncertain(transaction)
            self._append(JournalRecord.operation_handoff_fenced(transaction))
            if self.fail_after == "operation.handoff.fenced":
                return self._uncertain(transaction)
            receipt = await service.execute(transaction, typed)
            return self._record_terminal(receipt, reserve=True)
        except OperationManagerError:
            raise
        except (
            AuthorityError,
            JournalConflictError,
            OperationProtocolError,
            ValueError,
        ):
            raise OperationManagerError("operation execution is unavailable") from None
        except Exception:
            return self._uncertain(transaction)

    async def cancel(
        self, operation_id: str, *, authority_revision: int
    ) -> OperationReceipt:
        transaction = self._transactions.get(operation_id)
        if transaction is None or authority_revision != transaction.authority_revision:
            raise OperationManagerError("operation cancellation is invalid")
        existing = self._receipts.get(operation_id)
        if existing is not None:
            return existing
        if operation_id not in self._dispatched:
            return self._record_terminal(
                self._receipt(transaction, "cancelled", "cancelled-before-dispatch"),
                reserve=operation_id in self._authority.reserved_operation_ids,
            )
        try:
            return self._record_terminal(
                await self._service(transaction).cancel(transaction),
                reserve=operation_id in self._authority.reserved_operation_ids,
            )
        except OperationManagerError:
            raise
        except Exception:
            return self._uncertain(transaction)

    async def reconcile(self, transaction: OperationTransaction) -> OperationReceipt:
        self._validate_transaction(transaction)
        if self._transactions.get(transaction.operation_id) != transaction:
            raise OperationManagerError("operation reconciliation conflicts")
        existing = self._receipts.get(transaction.operation_id)
        if existing is not None and existing.status != "uncertain":
            return existing
        if existing is None or existing.status != "uncertain":
            raise OperationManagerError("operation reconciliation is unavailable")
        if transaction.operation_id not in self._dispatched:
            raise OperationManagerError("operation reconciliation is unavailable")
        service = self._service(transaction)
        attempt = self._attempts.get(transaction.operation_id, 0) + 1
        self._append(
            JournalRecord.operation_reconciliation_recorded(
                operation_id=transaction.operation_id, attempt=attempt
            )
        )
        self._attempts[transaction.operation_id] = attempt
        try:
            typed = self._stored_or_resolve(transaction, service)
            result = await service.reconcile(
                transaction,
                typed,
                OperationReconciliationContext(
                    transaction.operation_id, transaction.authority_revision, attempt
                ),
            )
            return self._record_terminal(result, reserve=True)
        except OperationManagerError as error:
            if str(error) == "operation private request is unavailable":
                return self._uncertain(transaction)
            raise
        except Exception:
            return self._uncertain(transaction)

    def _recover(self) -> None:
        try:
            decisions: dict[str, OperationDecision] = {}
            for entry in self._journal.replay(JournalCursor(0)):
                record = entry.record
                if record.kind == "operation.transaction.accepted":
                    transaction_value = record.payload["transaction"]
                    if not isinstance(transaction_value, Mapping):
                        raise ValueError
                    transaction = OperationTransaction.from_mapping(transaction_value)
                    prior = self._transactions.get(transaction.operation_id)
                    if prior is not None and prior != transaction:
                        raise OperationManagerError("operation recovery conflicts")
                    self._transactions[transaction.operation_id] = transaction
                elif record.kind == "operation.admitted":
                    decision = OperationDecision(**record.payload)  # type: ignore[arg-type]
                    transaction = self._transactions.get(decision.operation_id)
                    if (
                        transaction is None
                        or decision.transaction_digest
                        != operation_transaction_digest(transaction)
                    ):
                        raise ValueError
                    decisions[decision.operation_id] = decision
                elif record.kind == "operation.reserved":
                    operation_id = str(record.payload["operation_id"])
                    decision = decisions.get(operation_id)
                    if (
                        decision is None
                        or record.payload["transaction_digest"]
                        != decision.transaction_digest
                    ):
                        raise ValueError
                    self._authority.reserve_operation(decision)
                elif record.kind in {
                    "operation.dispatch.started",
                    "operation.handoff.fenced",
                }:
                    self._dispatched.add(str(record.payload["operation_id"]))
                elif record.kind == "operation.receipted":
                    receipt_value = record.payload["receipt"]
                    if not isinstance(receipt_value, Mapping):
                        raise ValueError
                    receipt = OperationReceipt.from_mapping(receipt_value)
                    prior = self._receipts.get(receipt.operation_id)
                    if (
                        prior is not None
                        and prior.status != "uncertain"
                        and prior != receipt
                    ):
                        raise OperationManagerError("operation recovery conflicts")
                    self._receipts[receipt.operation_id] = receipt
                    if receipt.status != "uncertain":
                        self._authority.settle_operation(
                            receipt.operation_id,
                            OperationSettlement(
                                receipt.operation_id,
                                receipt.receipt_id,
                                _receipt_digest(receipt),
                            ),
                        )
                elif record.kind == "operation.reconciliation.recorded":
                    operation_id, attempt = (
                        str(record.payload["operation_id"]),
                        int(record.payload["attempt"]),
                    )
                    self._attempts[operation_id] = max(
                        self._attempts.get(operation_id, 0), attempt
                    )
            for operation_id in sorted(self._dispatched - set(self._receipts)):
                transaction = self._transactions.get(operation_id)
                if transaction is None:
                    raise ValueError
                self._uncertain(transaction)
        except (JournalConflictError, OperationProtocolError, TypeError, ValueError):
            raise OperationManagerError("operation recovery is invalid") from None

    def _validate_transaction(self, transaction: object) -> None:
        if (
            not isinstance(transaction, OperationTransaction)
            or transaction.session_id != self._session_id
            or transaction.generation != self._generation
            or transaction.authority_id != self._authority.envelope.authority_id
            or transaction.authority_revision != self._authority.envelope.revision
            or transaction.request.session_id != self._session_id
            or transaction.request.generation != self._generation
            or transaction.request.authority_revision
            != self._authority.envelope.revision
        ):
            raise OperationManagerError("operation transaction is invalid")

    def _service(self, transaction: OperationTransaction) -> OperationService:
        service = self._services.get(transaction.feature_id)
        request = transaction.request
        if (
            service is None
            or getattr(service, "feature_id", None) != transaction.feature_id
            or getattr(service, "request_kind", None) != request.request_kind
            or getattr(service, "request_purpose", None) != request.purpose
            or request.media_type != "application/json"
            or type(getattr(service, "max_request_bytes", None)) is not int
            or service.max_request_bytes < request.byte_count
        ):
            raise OperationManagerError("operation service binding is invalid")
        return service

    def _resolve(
        self, transaction: OperationTransaction, service: OperationService
    ) -> object:
        request = transaction.request
        if self._cancelled():
            raise OperationManagerError("operation cancelled")
        try:
            body = self._resolver.resolve(
                request,
                purpose=request.purpose,
                max_bytes=service.max_request_bytes,
                deadline_ms=self._authority.envelope.max_action_deadline_ms,
                authority_revision=transaction.authority_revision,
                cancelled=False,
            )
            if (
                not isinstance(body, bytes)
                or len(body) != request.byte_count
                or hashlib.sha256(body).hexdigest() != request.request_sha256
                or self._cancelled()
            ):
                raise ValueError
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError
            typed = dict(value)
            digest = self._store.put(transaction, typed)
            if not isinstance(digest, str) or len(digest) != 64:
                raise ValueError
            return typed
        except Exception:
            raise OperationManagerError(
                "operation private request is unavailable"
            ) from None

    def _stored_or_resolve(
        self, transaction: OperationTransaction, service: OperationService
    ) -> object:
        value = self._store.get(transaction)
        if value is not None:
            return value
        expected = self._store.get_digest(transaction)
        value = self._resolve(transaction, service)
        digest = self._store.get_digest(transaction)
        if expected is not None and expected != digest:
            raise OperationManagerError("operation private request conflicts")
        return value

    def _record_terminal(
        self, receipt: OperationReceipt, *, reserve: bool
    ) -> OperationReceipt:
        transaction = self._transactions.get(receipt.operation_id)
        if transaction is None or not self._same_receipt_identity(transaction, receipt):
            raise OperationManagerError("operation receipt identity is invalid")
        existing = self._receipts.get(receipt.operation_id)
        if existing is not None:
            if existing.status != "uncertain" or receipt.status == "uncertain":
                if existing != receipt:
                    raise OperationManagerError("operation receipt conflicts")
                return existing
        self._append(JournalRecord.operation_receipted(receipt))
        self._receipts[receipt.operation_id] = receipt
        if reserve and receipt.status != "uncertain":
            self._authority.settle_operation(
                receipt.operation_id,
                OperationSettlement(
                    receipt.operation_id, receipt.receipt_id, _receipt_digest(receipt)
                ),
            )
        return receipt

    def _uncertain(self, transaction: OperationTransaction) -> OperationReceipt:
        current = self._receipts.get(transaction.operation_id)
        if current is not None:
            return current
        return self._record_terminal(
            self._receipt(transaction, "uncertain", "transport-uncertain"),
            reserve=False,
        )

    def _append(self, record: JournalRecord) -> None:
        self._journal.append(self._journal.position, record)

    @staticmethod
    def _same_receipt_identity(
        transaction: OperationTransaction, receipt: OperationReceipt
    ) -> bool:
        return (
            receipt.operation_id == transaction.operation_id
            and receipt.request_ref == transaction.request.request_ref
            and receipt.request_sha256 == transaction.request.request_sha256
            and receipt.purpose == transaction.request.purpose
            and receipt.session_id == transaction.session_id
            and receipt.client_id == transaction.client_id
            and receipt.generation == transaction.generation
            and receipt.authority_revision == transaction.authority_revision
            and receipt.authority_id == transaction.authority_id
            and receipt.idempotency_key == transaction.idempotency_key
            and receipt.feature_id == transaction.feature_id
        )

    @staticmethod
    def _receipt(
        transaction: OperationTransaction, status: str, reason: str
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
                "reason_code": reason,
                "receipt_ref": f"operation-receipt-{transaction.operation_id}",
                "reconciliation_ref": None,
                "effect_counts": {key: 0 for key in EFFECT_COUNTERS},
                "completed_at": transaction.requested_at,
            }
        )


def _receipt_digest(receipt: OperationReceipt) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(receipt.to_mapping()),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value
