"""Provider-free P3 acceptance boundary; it cannot issue bounded evidence."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from asterion.applications.prime_agent.evidence import PrimeEvidenceLevel, PrimeEvidenceReceipt, validate_prime_evidence_receipt
from asterion.applications.prime_agent.operator.recursive_code_review_workload import (
    RECURSIVE_CODE_REVIEW_P3_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID,
    RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.restricted_worker import (
    PrimeRestrictedWorkerError,
    PrimeRestrictedWorkerProfile,
    validate_prime_restricted_worker,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerExecutionReceipt,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


class RecursiveCodeReviewAcceptanceError(ValueError):
    """Raised without exposing injected-service or review-private values."""


@dataclass(frozen=True, repr=False)
class RecursiveCodeReviewProviderFreeObservation:
    """A non-promotable fake-chain observation."""

    trace_format: str
    disposed: bool
    reaped: bool

    def __repr__(self) -> str:
        return "RecursiveCodeReviewProviderFreeObservation(redacted)"


class _Worker(Protocol):
    def open(self, request: RestrictedWorkerRequest) -> AbstractAsyncContextManager[RestrictedWorkerLease]: ...
    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation: ...
    async def execution_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerExecutionReceipt: ...
    async def cleanup_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerCleanupReceipt: ...


class _Broker(Protocol):
    async def admit_root(self, lease: RestrictedWorkerLease) -> None: ...
    async def relay_once(self, body: bytes) -> bytes: ...
    async def revoke(self) -> None: ...


async def accept_recursive_code_review(
    *, profile: object, request: object, worker: object, broker: object,
    observation: object,
) -> PrimeEvidenceReceipt:
    """Validate preflight and emit only a provider-free P3 diagnostic receipt."""

    if type(profile) is not PrimeRestrictedWorkerProfile or type(request) is not RestrictedWorkerRequest:
        raise RecursiveCodeReviewAcceptanceError("recursive review acceptance is invalid")
    try:
        validate_prime_restricted_worker(profile)
    except PrimeRestrictedWorkerError:
        raise RecursiveCodeReviewAcceptanceError("recursive review acceptance is invalid") from None
    if (
        request.role_id != RECURSIVE_CODE_REVIEW_P3_ROLE_ID
        or request.workload_digest != RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST
        or request.image_digest != profile.image_digest
        or request.max_runtime_seconds != profile.max_runtime_seconds
        or request.max_output_bytes != profile.max_output_bytes
        or type(observation) is not RecursiveCodeReviewProviderFreeObservation
        or observation.trace_format != "asterion.prime-recursive-code-review-fixture/v1"
        or observation.disposed is not True
        or observation.reaped is not True
    ):
        raise RecursiveCodeReviewAcceptanceError("recursive review acceptance is invalid")
    if not all(callable(getattr(worker, name, None)) for name in ("open", "attest", "execution_receipt", "cleanup_receipt")) or not all(callable(getattr(broker, name, None)) for name in ("admit_root", "relay_once", "revoke")):
        raise RecursiveCodeReviewAcceptanceError("recursive review acceptance is invalid")
    admitted = False
    lease: RestrictedWorkerLease | None = None
    try:
        typed_worker = worker  # runtime protocol checks above preserve the public boundary.
        typed_broker = broker
        async with typed_worker.open(request) as lease:  # type: ignore[union-attr]
            await typed_worker.attest(lease)  # type: ignore[union-attr]
            await typed_broker.admit_root(lease)  # type: ignore[union-attr]
            admitted = True
            released = await typed_broker.relay_once(b"p3-provider-free")  # type: ignore[union-attr]
            if type(released) is not bytes or not released:
                raise RecursiveCodeReviewAcceptanceError("recursive review acceptance is invalid")
            await typed_worker.execution_receipt(lease)  # type: ignore[union-attr]
            await typed_broker.revoke()  # type: ignore[union-attr]
            admitted = False
        await typed_worker.cleanup_receipt(lease)  # type: ignore[union-attr]
    except (RecursiveCodeReviewAcceptanceError, TypeError, ValueError):
        raise RecursiveCodeReviewAcceptanceError("recursive review acceptance is invalid") from None
    finally:
        if admitted:
            try:
                await typed_broker.revoke()  # type: ignore[union-attr]
            except BaseException:
                pass
    return validate_prime_evidence_receipt(PrimeEvidenceReceipt(
        scenario_id=RECURSIVE_CODE_REVIEW_P3_SCENARIO_ID,
        level=PrimeEvidenceLevel.PROVIDER_FREE,
        status="PASS",
    ))
