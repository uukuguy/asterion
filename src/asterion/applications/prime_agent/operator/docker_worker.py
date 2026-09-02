"""Closed Docker-engine adapter for the one Prime coding-worker role.

This module deliberately contains no Docker client integration.  An operator
injects the narrow engine transport after establishing its own engine policy.
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Literal, Protocol

from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerError,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
    verify_restricted_worker_receipts,
)


_ROLE_ID = "prime.ipython-coding"
_NON_ROOT_ID = 65534


@dataclass(frozen=True)
class _DockerWorkerRole:
    """Code-owned policy for the sole Docker-backed Prime worker role."""

    image_digest: str
    max_runtime_seconds: int = 300
    max_output_bytes: int = 65536
    launcher_id: Literal["prime-ipython-coding"] = "prime-ipython-coding"
    user_id: int = _NON_ROOT_ID
    group_id: int = _NON_ROOT_ID
    role_id: Literal["prime.ipython-coding"] = _ROLE_ID


@dataclass(frozen=True)
class _DockerWorkerSpecification:
    """The complete, non-generic engine create input."""

    role_id: Literal["prime.ipython-coding"]
    image_digest: str
    run_id: str
    challenge_digest: str
    max_runtime_seconds: int
    max_output_bytes: int
    launcher_id: Literal["prime-ipython-coding"]
    user_id: int
    group_id: int


class DockerEngineTransport(Protocol):
    """Operator-supplied engine operations for an already-fixed worker spec."""

    def open(
        self,
        specification: _DockerWorkerSpecification,
        *,
        signal: CancellationSignal | None = None,
    ) -> AbstractAsyncContextManager[RestrictedWorkerLease]: ...

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation: ...

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt: ...


class DockerRestrictedWorkerService:
    """Admits only the fixed Prime role to an injected engine transport."""

    def __init__(self, *, image_digest: str, transport: DockerEngineTransport) -> None:
        try:
            self._role = _DockerWorkerRole(image_digest=image_digest)
            # Reuse the closed shared contract to reject a tag-like image value.
            RestrictedWorkerRequest(
                _ROLE_ID, image_digest, "role-check", "sha256:" + "0" * 64, 1, 1
            )
        except RestrictedWorkerError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        self._transport = transport
        self._requests: dict[str, RestrictedWorkerRequest] = {}

    def request_for(
        self, request: RestrictedWorkerRequest
    ) -> _DockerWorkerSpecification:
        """Return the only engine specification this service can create."""
        if (
            type(request) is not RestrictedWorkerRequest
            or request.role_id != self._role.role_id
            or request.image_digest != self._role.image_digest
            or request.max_runtime_seconds > self._role.max_runtime_seconds
            or request.max_output_bytes > self._role.max_output_bytes
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return _DockerWorkerSpecification(
            role_id=self._role.role_id,
            image_digest=self._role.image_digest,
            run_id=request.run_id,
            challenge_digest=request.challenge_digest,
            max_runtime_seconds=request.max_runtime_seconds,
            max_output_bytes=request.max_output_bytes,
            launcher_id=self._role.launcher_id,
            user_id=self._role.user_id,
            group_id=self._role.group_id,
        )

    def open(
        self,
        request: RestrictedWorkerRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AbstractAsyncContextManager[RestrictedWorkerLease]:
        specification = self.request_for(request)
        return _DockerWorkerLeaseContext(self, request, specification, signal)

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation:
        request = self._request_for_lease(lease)
        try:
            attestation = await self._transport.attest(lease)
            verify_restricted_worker_receipts(
                request,
                lease,
                attestation,
                RestrictedWorkerCleanupReceipt(
                    lease.worker_id, lease.run_id, lease.challenge_digest, True
                ),
            )
        except RestrictedWorkerError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        return attestation

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt:
        request = self._request_for_lease(lease)
        try:
            receipt = await self._transport.cleanup_receipt(lease)
            verify_restricted_worker_receipts(
                request,
                lease,
                RestrictedWorkerAttestation(
                    lease.worker_id,
                    lease.run_id,
                    lease.challenge_digest,
                    request.image_digest,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                    True,
                ),
                receipt,
            )
        except RestrictedWorkerError:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        return receipt

    def _admit_lease(
        self, request: RestrictedWorkerRequest, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerLease:
        if (
            type(lease) is not RestrictedWorkerLease
            or lease.run_id != request.run_id
            or lease.challenge_digest != request.challenge_digest
            or lease.worker_id in self._requests
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._requests[lease.worker_id] = request
        return lease

    def _request_for_lease(self, lease: RestrictedWorkerLease) -> RestrictedWorkerRequest:
        if type(lease) is not RestrictedWorkerLease:
            raise RestrictedWorkerError("restricted worker value is invalid")
        request = self._requests.get(lease.worker_id)
        if (
            request is None
            or request.run_id != lease.run_id
            or request.challenge_digest != lease.challenge_digest
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return request


class _DockerWorkerLeaseContext(AbstractAsyncContextManager[RestrictedWorkerLease]):
    def __init__(
        self,
        service: DockerRestrictedWorkerService,
        request: RestrictedWorkerRequest,
        specification: _DockerWorkerSpecification,
        signal: CancellationSignal | None,
    ) -> None:
        self._service = service
        self._request = request
        self._context = service._transport.open(specification, signal=signal)

    async def __aenter__(self) -> RestrictedWorkerLease:
        return self._service._admit_lease(self._request, await self._context.__aenter__())

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return await self._context.__aexit__(exc_type, exc_value, traceback)
