"""Host-owned, append-only operation dispatch and reconciliation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

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


@dataclass
class _RecoveryPhase:
    """The legal durable prefix for one operation identity."""

    transaction: OperationTransaction | None = None
    decision: OperationDecision | None = None
    reserved: bool = False
    dispatched: bool = False
    handoff: bool = False
    receipt: OperationReceipt | None = None
    reconciliation_attempt: int = 0
    reconciled_after_uncertain: bool = False


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
            if self._cancelled():
                return self._record_terminal(
                    self._receipt(
                        transaction, "cancelled", "cancelled-before-dispatch"
                    ),
                    reserve=True,
                )
            try:
                typed = self._resolve(transaction, service)
            except OperationManagerError as error:
                if str(error) == "operation cancelled":
                    return self._record_terminal(
                        self._receipt(
                            transaction, "cancelled", "cancelled-before-dispatch"
                        ),
                        reserve=True,
                    )
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
            phases: dict[str, _RecoveryPhase] = {}
            for entry in self._journal.replay(JournalCursor(0)):
                record = entry.record
                if record.kind == "operation.transaction.accepted":
                    transaction_value = record.payload["transaction"]
                    if not isinstance(transaction_value, Mapping):
                        raise ValueError
                    transaction = OperationTransaction.from_mapping(transaction_value)
                    self._validate_transaction(transaction)
                    phase = phases.setdefault(transaction.operation_id, _RecoveryPhase())
                    if phase.transaction is not None:
                        raise ValueError
                    phase.transaction = transaction
                    self._transactions[transaction.operation_id] = transaction
                elif record.kind == "operation.admitted":
                    decision = OperationDecision(**record.payload)  # type: ignore[arg-type]
                    phase = phases.get(decision.operation_id)
                    if phase is None or phase.transaction is None:
                        raise ValueError
                    transaction = phase.transaction
                    if (
                        phase.decision is not None
                        or phase.receipt is not None
                        or decision.authority_id != transaction.authority_id
                        or decision.authority_revision != transaction.authority_revision
                        or decision.feature_id != transaction.feature_id
                        or decision.transaction_digest
                        != operation_transaction_digest(transaction)
                    ):
                        raise ValueError
                    phase.decision = decision
                elif record.kind == "operation.reserved":
                    operation_id = record.payload["operation_id"]
                    digest = record.payload["transaction_digest"]
                    if not isinstance(operation_id, str) or not isinstance(digest, str):
                        raise ValueError
                    phase = phases.get(operation_id)
                    if phase is None or phase.decision is None:
                        raise ValueError
                    decision = phase.decision
                    if (
                        decision.status != "admitted"
                        or phase.reserved
                        or phase.receipt is not None
                        or digest
                        != decision.transaction_digest
                    ):
                        raise ValueError
                    self._authority.reserve_operation(decision)
                    phase.reserved = True
                elif record.kind == "operation.dispatch.started":
                    phase = self._phase_for_digest(phases, record)
                    if (
                        phase.decision is None
                        or phase.decision.status != "admitted"
                        or not phase.reserved
                        or phase.dispatched
                        or phase.handoff
                        or phase.receipt is not None
                    ):
                        raise ValueError
                    phase.dispatched = True
                    assert phase.transaction is not None
                    self._dispatched.add(phase.transaction.operation_id)
                elif record.kind == "operation.handoff.fenced":
                    phase = self._phase_for_digest(phases, record)
                    if (
                        phase.decision is None
                        or phase.decision.status != "admitted"
                        or not phase.reserved
                        or not phase.dispatched
                        or phase.handoff
                        or phase.receipt is not None
                    ):
                        raise ValueError
                    phase.handoff = True
                elif record.kind == "operation.receipted":
                    receipt_value = record.payload["receipt"]
                    if not isinstance(receipt_value, Mapping):
                        raise ValueError
                    receipt = OperationReceipt.from_mapping(receipt_value)
                    phase = phases.get(receipt.operation_id)
                    if phase is None or phase.transaction is None:
                        raise ValueError
                    transaction = phase.transaction
                    if not self._same_receipt_identity(
                        transaction, receipt
                    ):
                        raise ValueError
                    self._record_recovered_receipt(phase, receipt)
                    self._receipts[receipt.operation_id] = receipt
                    if (
                        phase.decision is not None
                        and phase.decision.status == "admitted"
                        and phase.reserved
                        and receipt.status != "uncertain"
                    ):
                        self._authority.settle_operation(
                            receipt.operation_id,
                            OperationSettlement(
                                receipt.operation_id,
                                receipt.receipt_id,
                                _receipt_digest(receipt),
                            ),
                        )
                elif record.kind == "operation.reconciliation.recorded":
                    operation_id = record.payload["operation_id"]
                    attempt = record.payload["attempt"]
                    if not isinstance(operation_id, str) or type(attempt) is not int:
                        raise ValueError
                    phase = phases.get(operation_id)
                    if (
                        phase is None
                        or phase.transaction is None
                        or phase.decision is None
                        or phase.decision.status != "admitted"
                        or not phase.reserved
                        or not phase.dispatched
                        or phase.receipt is None
                        or phase.receipt.status != "uncertain"
                        or attempt != phase.reconciliation_attempt + 1
                    ):
                        raise ValueError
                    phase.reconciliation_attempt = attempt
                    phase.reconciled_after_uncertain = True
                    self._attempts[operation_id] = attempt
            for phase in phases.values():
                if phase.dispatched and phase.receipt is None:
                    if phase.transaction is None:
                        raise ValueError
                    self._uncertain(phase.transaction)
        except (
            AuthorityError,
            JournalConflictError,
            OperationManagerError,
            OperationProtocolError,
            TypeError,
            ValueError,
        ):
            raise OperationManagerError("operation recovery is invalid") from None

    @staticmethod
    def _phase_for_digest(
        phases: Mapping[str, _RecoveryPhase], record: JournalRecord
    ) -> _RecoveryPhase:
        operation_id = record.payload["operation_id"]
        digest = record.payload["transaction_digest"]
        if not isinstance(operation_id, str) or not isinstance(digest, str):
            raise ValueError
        phase = phases.get(operation_id)
        if (
            phase is None
            or phase.transaction is None
            or digest != operation_transaction_digest(phase.transaction)
        ):
            raise ValueError
        return phase

    @staticmethod
    def _record_recovered_receipt(
        phase: _RecoveryPhase, receipt: OperationReceipt
    ) -> None:
        """Validate a terminal record against the durable prefix without effects."""

        prior = phase.receipt
        decision = phase.decision
        if prior is not None:
            if (
                prior.status != "uncertain"
                or receipt.status == "uncertain"
                or not phase.reconciled_after_uncertain
                or receipt.status not in {"succeeded", "failed", "cancelled", "rejected"}
            ):
                raise ValueError
            phase.receipt = receipt
            return
        if decision is None:
            if (
                receipt.status != "rejected"
                or phase.reserved
                or phase.dispatched
                or phase.handoff
            ):
                raise ValueError
            phase.receipt = receipt
            return
        if decision.status == "rejected":
            if (
                receipt.status != "rejected"
                or phase.reserved
                or phase.dispatched
                or phase.handoff
            ):
                raise ValueError
            phase.receipt = receipt
            return
        if not phase.reserved:
            raise ValueError
        if receipt.status == "uncertain":
            if not phase.dispatched:
                raise ValueError
            phase.receipt = receipt
            return
        if phase.dispatched:
            if not phase.handoff:
                raise ValueError
        elif (
            receipt.status not in {"failed", "cancelled"}
            or receipt.reason_code
            not in {"private-request-unavailable", "cancelled-before-dispatch"}
        ):
            raise ValueError
        phase.receipt = receipt

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
            ):
                raise ValueError
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError
            typed = dict(value)
            digest = self._store.put(transaction, typed)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(value not in "0123456789abcdef" for value in digest)
                or digest != _typed_digest(typed)
            ):
                raise ValueError
            if self._cancelled():
                raise OperationManagerError("operation cancelled")
            return typed
        except OperationManagerError:
            raise
        except Exception:
            raise OperationManagerError(
                "operation private request is unavailable"
            ) from None

    def _stored_or_resolve(
        self, transaction: OperationTransaction, service: OperationService
    ) -> object:
        value = self._store.get(transaction)
        if value is not None:
            digest = self._store.get_digest(transaction)
            if digest != _typed_digest(value):
                raise OperationManagerError("operation private request conflicts")
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


def _typed_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_json_value(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
