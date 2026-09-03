"""Sealed P3 recursive-review worker and one-use RLM broker facades."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, TypeGuard

from asterion.applications.prime_agent.operator.recursive_code_review_release import (
    RecursiveCodeReviewReleaseError,
    parse_recursive_code_review_frames,
)
from asterion.applications.prime_agent.operator.recursive_code_review_workload import (
    RECURSIVE_CODE_REVIEW_P3_DEADLINE_SECONDS,
    RECURSIVE_CODE_REVIEW_P3_MAX_FRAME_BYTES,
    RECURSIVE_CODE_REVIEW_P3_ROLE_ID,
    RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST,
)
from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerError,
    RestrictedWorkerExecutionReceipt,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


_ENTRYPOINT = "/usr/local/bin/prime-recursive-code-review.mjs"
_SECCOMP = "prime-recursive-code-review"
_COMPLETION_MAX_BYTES = 13 * RECURSIVE_CODE_REVIEW_P3_MAX_FRAME_BYTES + 12


class RecursiveCodeReviewEngine(Protocol):
    async def launch(
        self, *, role_id: str, image_digest: str, workload_digest: str,
        env: tuple[str, ...], entrypoint: str, seccomp: str,
        signal: CancellationSignal | None,
    ) -> RestrictedWorkerLease: ...

    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes: ...
    async def remove(self, lease: RestrictedWorkerLease) -> None: ...


class _RlmEndpoint(Protocol):
    async def admit_root(self, lease: RestrictedWorkerLease) -> None: ...
    async def relay_once(self, body: bytes) -> bytes: ...
    async def revoke(self) -> None: ...


class RecursiveCodeReviewBroker:
    """P3-only one-use RLM relay with a completed causal trace before revocation."""

    def __init__(self, endpoint: _RlmEndpoint) -> None:
        self._endpoint = endpoint
        self._root: RestrictedWorkerLease | None = None
        self._used = False
        self._revoked = False
        self._usage_sha256: str | None = None

    async def admit_root(self, lease: RestrictedWorkerLease) -> None:
        if self._root is not None or self._revoked or not _p3_lease(lease):
            raise RestrictedWorkerError("restricted worker value is invalid")
        try:
            await self._endpoint.admit_root(lease)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        self._root = lease

    async def relay_once(self, body: bytes) -> bytes:
        if self._root is None or self._used or self._revoked or type(body) is not bytes:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._used = True
        try:
            result = await self._endpoint.relay_once(body)
            if type(result) is not bytes:
                raise RestrictedWorkerError("restricted worker value is invalid")
            trace = parse_recursive_code_review_frames(result)
            # This is the only retained result fact; it is an opaque, bounded digest.
            self._usage_sha256 = trace.usage_sha256
            return result
        except asyncio.CancelledError:
            raise
        except (RecursiveCodeReviewReleaseError, RestrictedWorkerError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def revoke(self) -> None:
        if (
            self._root is None or not self._used or self._revoked
            or self._usage_sha256 is None
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        # The parser admitted the fixed 13-frame trace: usage, follow-up, and both
        # child-deletions all precede its terminal revoked frame.
        self._revoked = True
        try:
            await self._endpoint.revoke()
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None


@dataclass
class _State:
    request: RestrictedWorkerRequest
    lease: RestrictedWorkerLease
    execution: RestrictedWorkerExecutionReceipt | None = None
    destroyed: bool = False


class RecursiveCodeReviewDockerWorker:
    """P3-only lifecycle facade over an injected operator-owned engine."""

    def __init__(self, *, image_digest: str, engine: RecursiveCodeReviewEngine) -> None:
        if type(image_digest) is not str or not image_digest.startswith("sha256:"):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._image, self._engine = image_digest, engine
        self._states: dict[str, _State] = {}
        self._tombstones: dict[str, RestrictedWorkerLease] = {}

    def request_for(self, request: RestrictedWorkerRequest) -> RestrictedWorkerRequest:
        if (
            type(request) is not RestrictedWorkerRequest
            or request.role_id != RECURSIVE_CODE_REVIEW_P3_ROLE_ID
            or request.image_digest != self._image
            or request.workload_digest != RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST
            or request.max_runtime_seconds > RECURSIVE_CODE_REVIEW_P3_DEADLINE_SECONDS
            or request.max_output_bytes > _COMPLETION_MAX_BYTES
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return request

    def open(self, request: RestrictedWorkerRequest, *, signal: CancellationSignal | None = None) -> AbstractAsyncContextManager[RestrictedWorkerLease]:
        return _Context(self, self.request_for(request), signal)

    async def execution_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerExecutionReceipt:
        state = self._state(lease)
        if state.execution is None:
            try:
                raw = await self._engine.completion_bytes(lease)
            except asyncio.CancelledError:
                raise
            except BaseException:
                raise RestrictedWorkerError("restricted worker value is invalid") from None
            if type(raw) is not bytes or not raw or len(raw) > state.request.max_output_bytes:
                raise RestrictedWorkerError("restricted worker value is invalid")
            try:
                parse_recursive_code_review_frames(raw)
            except RecursiveCodeReviewReleaseError:
                raise RestrictedWorkerError("restricted worker value is invalid") from None
            state.execution = RestrictedWorkerExecutionReceipt(
                lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
                lease.workload_digest, "sha256:" + sha256(raw).hexdigest(),
            )
        return state.execution

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation:
        state = self._state(lease)
        return RestrictedWorkerAttestation(
            lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
            lease.workload_digest, state.request.image_digest, True, True, True,
            True, True, True, True,
        )

    async def cleanup_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerCleanupReceipt:
        if type(lease) is not RestrictedWorkerLease or self._tombstones.pop(lease.worker_id, None) != lease:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return RestrictedWorkerCleanupReceipt(
            lease.worker_id, lease.role_id, lease.run_id, lease.challenge_digest,
            lease.workload_digest, True,
        )

    def _state(self, lease: RestrictedWorkerLease) -> _State:
        state = self._states.get(lease.worker_id) if type(lease) is RestrictedWorkerLease else None
        if state is None or state.lease != lease or state.destroyed:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return state


class _Context(AbstractAsyncContextManager[RestrictedWorkerLease]):
    def __init__(self, service: RecursiveCodeReviewDockerWorker, request: RestrictedWorkerRequest, signal: CancellationSignal | None) -> None:
        self._service, self._request, self._signal = service, request, signal
        self._lease: RestrictedWorkerLease | None = None

    async def __aenter__(self) -> RestrictedWorkerLease:
        if self._signal is not None and self._signal.cancelled:
            raise asyncio.CancelledError
        try:
            lease = await self._service._engine.launch(
                role_id=RECURSIVE_CODE_REVIEW_P3_ROLE_ID, image_digest=self._service._image,
                workload_digest=RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST, env=(),
                entrypoint=_ENTRYPOINT, seccomp=_SECCOMP, signal=self._signal,
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        if not _matches(self._request, lease) or lease.worker_id in self._service._states:
            error = await self._remove(lease)
            if isinstance(error, asyncio.CancelledError):
                raise error
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        self._lease = lease
        self._service._states[lease.worker_id] = _State(self._request, lease)
        return lease

    async def __aexit__(self, *args: object) -> None:
        if self._lease is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        state = self._service._state(self._lease)
        error = await self._remove(self._lease)
        state.destroyed = True
        del self._service._states[self._lease.worker_id]
        if error is not None and not isinstance(error, asyncio.CancelledError):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        if state.execution is None:
            if isinstance(error, asyncio.CancelledError):
                raise error
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._service._tombstones[self._lease.worker_id] = self._lease
        if isinstance(error, asyncio.CancelledError):
            raise error

    async def _remove(self, lease: RestrictedWorkerLease) -> BaseException | None:
        task = asyncio.create_task(self._service._engine.remove(lease))
        cancelled: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                cancelled = error
            except BaseException as error:
                return error
        if task.cancelled():
            return asyncio.CancelledError()
        try:
            task.result()
        except BaseException as error:
            return error
        return cancelled


def _p3_lease(lease: object) -> TypeGuard[RestrictedWorkerLease]:
    return type(lease) is RestrictedWorkerLease and lease.role_id == RECURSIVE_CODE_REVIEW_P3_ROLE_ID and lease.workload_digest == RECURSIVE_CODE_REVIEW_P3_WORKLOAD_DIGEST


def _matches(request: RestrictedWorkerRequest, lease: object) -> bool:
    return _p3_lease(lease) and lease.run_id == request.run_id and lease.challenge_digest == request.challenge_digest
