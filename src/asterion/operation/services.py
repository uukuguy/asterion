"""Narrow host-injected interfaces for durable operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from asterion.operation.protocol import (
    OperationReceipt,
    OperationRequestDescriptor,
    OperationTransaction,
)


class OperationPrivateRequestResolver(Protocol):
    def resolve(
        self,
        descriptor: OperationRequestDescriptor,
        *,
        purpose: str,
        max_bytes: int,
        deadline_ms: int,
        authority_revision: int,
        cancelled: bool,
    ) -> bytes: ...


class OperationPrivateRequestStore(Protocol):
    def put(self, transaction: OperationTransaction, typed_request: object) -> str: ...
    def get(self, transaction: OperationTransaction) -> object | None: ...
    def get_digest(self, transaction: OperationTransaction) -> str | None: ...


class OperationDispatcher(Protocol):
    @property
    def session_id(self) -> str: ...

    @property
    def generation(self) -> int: ...

    @property
    def authority_id(self) -> str: ...

    @property
    def authority_revision(self) -> int: ...

    async def execute(
        self, transaction: OperationTransaction
    ) -> OperationReceipt: ...

    async def cancel(
        self, operation_id: str, *, authority_revision: int
    ) -> OperationReceipt: ...

    async def reconcile(
        self, transaction: OperationTransaction
    ) -> OperationReceipt: ...


@dataclass(frozen=True)
class OperationHandoffProof:
    """Opaque, manager-durable proof emitted before an irreversible handoff."""

    digest: str


@dataclass(frozen=True)
class OperationReconciliationContext:
    operation_id: str
    authority_revision: int
    reconciliation_attempt: int
    handoff_proof_digest: str | None = None


class OperationService(Protocol):
    feature_id: str
    request_kind: str
    request_purpose: str
    max_request_bytes: int

    async def execute(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationReceipt: ...

    async def cancel(self, transaction: OperationTransaction) -> OperationReceipt: ...
    async def reconcile(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        context: OperationReconciliationContext,
    ) -> OperationReceipt: ...


class StagedOperationService:
    """Nominal opt-in for the manager-owned two-phase handoff path."""

    async def prepare_handoff(
        self, transaction: OperationTransaction, typed_request: object
    ) -> OperationHandoffProof | OperationReceipt: ...

    async def handoff_prepared(
        self,
        transaction: OperationTransaction,
        typed_request: object,
        proof: OperationHandoffProof,
    ) -> OperationReceipt: ...
