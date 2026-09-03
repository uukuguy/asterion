"""Provider-free orchestration for the sealed Prime P2 acceptance boundary.

This coordinator deliberately accepts injected host services only.  It neither
discovers a Docker engine nor configures a model provider.  The emitted receipt
is derived after the broker is revoked and the worker has been destroyed.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from asterion.applications.prime_agent.evidence import PrimeEvidenceReceipt
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerReceipt
from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
)
from asterion.applications.prime_agent.programmatic_long_context_bounded_receipt import (
    ProgrammaticLongContextBoundedObservation,
    ProgrammaticLongContextBoundedReceiptError,
    verify_programmatic_long_context_bounded_receipt,
)
from asterion.applications.prime_agent.restricted_worker import PrimeRestrictedWorkerProfile
from asterion.applications.prime_agent.worker_gate import (
    PrimeWorkerBoundaryError,
    verify_prime_worker_boundary,
)
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerExecutionReceipt,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


class ProgrammaticLongContextAcceptanceError(ValueError):
    """Raised without exposing worker, broker, or model-private values."""


class _Worker(Protocol):
    def open(
        self, request: RestrictedWorkerRequest, **kwargs: object
    ) -> AbstractAsyncContextManager[RestrictedWorkerLease]: ...

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation: ...

    async def execution_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerExecutionReceipt: ...

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt: ...


class _Broker(Protocol):
    async def admit(self, attestation: RestrictedWorkerAttestation) -> None: ...

    async def release(self) -> bytes: ...

    async def revoke(self) -> PrimeModelBrokerReceipt: ...


@dataclass(frozen=True, repr=False)
class ProgrammaticLongContextAcceptanceFacts:
    """Private completion facts normalized by the sealed worker implementation."""

    built_in_tools: tuple[str, ...]
    active_tool_names: tuple[str, ...]
    corpus_sha256: str
    program_sha256: str
    response_sha256: str
    aggregate_sha256: str
    oracle_sha256: str
    ipython_cell_executed: bool
    oracle_passed: bool

    def __repr__(self) -> str:
        return "ProgrammaticLongContextAcceptanceFacts(redacted)"


async def accept_programmatic_long_context(
    *,
    worker: _Worker,
    profile: PrimeRestrictedWorkerProfile,
    request: RestrictedWorkerRequest,
    broker: _Broker,
    facts: ProgrammaticLongContextAcceptanceFacts,
) -> PrimeEvidenceReceipt:
    """Run the sole P2 acceptance order and reduce its sealed evidence."""

    if (
        type(profile) is not PrimeRestrictedWorkerProfile
        or type(request) is not RestrictedWorkerRequest
        or type(facts) is not ProgrammaticLongContextAcceptanceFacts
        or request.role_id != PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID
        or request.workload_digest != PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST
        or request.image_digest != profile.image_digest
        or request.max_runtime_seconds != profile.max_runtime_seconds
        or request.max_output_bytes != profile.max_output_bytes
        or not all(callable(getattr(worker, name, None)) for name in ("open", "attest", "execution_receipt", "cleanup_receipt"))
        or not all(callable(getattr(broker, name, None)) for name in ("admit", "release", "revoke"))
    ):
        raise ProgrammaticLongContextAcceptanceError("programmatic long-context acceptance is invalid")

    admitted = False
    try:
        async with worker.open(request) as lease:
            attestation = await worker.attest(lease)
            await broker.admit(attestation)
            admitted = True
            response = await broker.release()
            if type(response) is not bytes or not response or (
                "sha256:" + sha256(response).hexdigest() != facts.response_sha256
            ):
                raise ProgrammaticLongContextAcceptanceError(
                    "programmatic long-context acceptance is invalid"
                )
            execution = await worker.execution_receipt(lease)
            broker_receipt = await broker.revoke()
            admitted = False
        cleanup = await worker.cleanup_receipt(lease)
        boundary = verify_prime_worker_boundary(
            PROGRAMMATIC_LONG_CONTEXT_P2_SCENARIO_ID,
            profile,
            request,
            lease,
            attestation,
            execution,
            cleanup,
        )
        return verify_programmatic_long_context_bounded_receipt(
            ProgrammaticLongContextBoundedObservation(
                facts.built_in_tools,
                facts.active_tool_names,
                facts.corpus_sha256,
                facts.program_sha256,
                facts.response_sha256,
                facts.aggregate_sha256,
                facts.oracle_sha256,
                facts.ipython_cell_executed,
                facts.oracle_passed,
                broker_receipt,
                boundary,
            )
        )
    except (
        ProgrammaticLongContextAcceptanceError,
        ProgrammaticLongContextBoundedReceiptError,
        PrimeWorkerBoundaryError,
        TypeError,
        ValueError,
    ):
        raise ProgrammaticLongContextAcceptanceError(
            "programmatic long-context acceptance is invalid"
        ) from None
    finally:
        if admitted:
            try:
                await broker.revoke()
            except BaseException:
                pass
