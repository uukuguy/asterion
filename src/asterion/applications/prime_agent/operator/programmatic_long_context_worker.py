"""Sealed P2 Docker-worker and host-broker facades.

This is intentionally separate from the P1 coding worker: no role, command,
environment, workload, or image selection crosses this boundary.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Protocol

from asterion.applications.prime_agent.operator.programmatic_long_context_workload import (
    PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID,
    PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
    ProgrammaticLongContextCompletion,
    ProgrammaticLongContextWorkloadError,
    canonical_programmatic_long_context_completion_bytes,
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

_ENTRYPOINT = "/usr/local/bin/prime-programmatic-long-context.mjs"
_SECCOMP = "prime-programmatic-long-context"


class ProgrammaticLongContextEngine(Protocol):
    async def launch(
        self,
        *,
        role_id: str,
        image_digest: str,
        workload_digest: str,
        env: tuple[str, ...],
        entrypoint: str,
        seccomp: str,
        signal: CancellationSignal | None,
    ) -> RestrictedWorkerLease: ...
    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes: ...
    async def remove(self, lease: RestrictedWorkerLease) -> None: ...


class ProgrammaticLongContextBroker(Protocol):
    async def request(self, body: bytes) -> bytes: ...
    async def revoke(self) -> None: ...


class ProgrammaticLongContextBrokerRelay:
    """One-use worker relay; closure means broker revocation has completed."""

    def __init__(self, broker: ProgrammaticLongContextBroker) -> None:
        self._broker, self._closed, self._consumed = broker, False, False

    async def request(self, body: bytes) -> bytes:
        if self._closed or self._consumed or type(body) is not bytes:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._consumed = True
        try:
            result = await self._broker.request(body)
            if type(result) is not bytes or self._closed:
                raise RestrictedWorkerError("restricted worker value is invalid")
            return result
        except asyncio.CancelledError:
            await self.close()
            raise
        except RestrictedWorkerError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._broker.revoke()
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None


@dataclass
class _State:
    request: RestrictedWorkerRequest
    lease: RestrictedWorkerLease
    execution: RestrictedWorkerExecutionReceipt | None = None
    destroyed: bool = False


class ProgrammaticLongContextDockerWorker:
    """P2-only lifecycle facade over an injected, operator-owned engine."""

    def __init__(
        self, *, image_digest: str, engine: ProgrammaticLongContextEngine
    ) -> None:
        if type(image_digest) is not str or not image_digest.startswith("sha256:"):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._image, self._engine, self._states = image_digest, engine, {}
        self._tombstones: dict[str, RestrictedWorkerLease] = {}

    def request_for(self, request: RestrictedWorkerRequest) -> RestrictedWorkerRequest:
        if (
            type(request) is not RestrictedWorkerRequest
            or request.role_id != PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID
            or request.image_digest != self._image
            or request.workload_digest != PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST
            or request.max_runtime_seconds > 300
            or request.max_output_bytes > 4096
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return request

    def open(
        self,
        request: RestrictedWorkerRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> AbstractAsyncContextManager[RestrictedWorkerLease]:
        return _Context(self, self.request_for(request), signal)

    async def execution_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerExecutionReceipt:
        state = self._state(lease)
        if state.execution is None:
            try:
                raw = await self._engine.completion_bytes(lease)
            except asyncio.CancelledError:
                raise
            except BaseException:
                raise RestrictedWorkerError(
                    "restricted worker value is invalid"
                ) from None
            if (
                type(raw) is not bytes
                or not raw
                or len(raw) > state.request.max_output_bytes
            ):
                raise RestrictedWorkerError("restricted worker value is invalid")
            self._canonical_completion(raw)
            state.execution = RestrictedWorkerExecutionReceipt(
                lease.worker_id,
                lease.role_id,
                lease.run_id,
                lease.challenge_digest,
                lease.workload_digest,
                "sha256:" + sha256(raw).hexdigest(),
            )
        return state.execution

    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation:
        state = self._state(lease)
        return RestrictedWorkerAttestation(
            lease.worker_id,
            lease.role_id,
            lease.run_id,
            lease.challenge_digest,
            lease.workload_digest,
            state.request.image_digest,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
        )

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt:
        if (
            type(lease) is not RestrictedWorkerLease
            or self._tombstones.pop(lease.worker_id, None) != lease
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return RestrictedWorkerCleanupReceipt(
            lease.worker_id,
            lease.role_id,
            lease.run_id,
            lease.challenge_digest,
            lease.workload_digest,
            True,
        )

    def _state(self, lease: RestrictedWorkerLease) -> _State:
        state = self._states.get(lease.worker_id)
        if (
            type(lease) is not RestrictedWorkerLease
            or state is None
            or state.lease != lease
            or state.destroyed
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        return state

    @staticmethod
    def _canonical_completion(raw: bytes) -> None:
        try:
            value = json.loads(raw.decode("utf-8"))
            if type(value) is not dict:
                raise ValueError
            completion = ProgrammaticLongContextCompletion(
                response_sha256=value["response_sha256"],
                program_sha256=value["program_sha256"],
                aggregate_sha256=value["aggregate_sha256"],
                active_tool_names=tuple(value["active_tool_names"]),
                ipython_cell_executed=value["ipython_cell_executed"],
                oracle_passed=value["oracle_passed"],
                session_disposed=value["session_disposed"],
            )
            if canonical_programmatic_long_context_completion_bytes(completion) != raw:
                raise ValueError
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ProgrammaticLongContextWorkloadError,
            ValueError,
        ):
            raise RestrictedWorkerError("restricted worker value is invalid") from None


class _Context(AbstractAsyncContextManager[RestrictedWorkerLease]):
    def __init__(
        self,
        service: ProgrammaticLongContextDockerWorker,
        request: RestrictedWorkerRequest,
        signal: CancellationSignal | None,
    ) -> None:
        self._service, self._request, self._signal, self._lease = (
            service,
            request,
            signal,
            None,
        )

    async def __aenter__(self) -> RestrictedWorkerLease:
        if self._signal is not None and self._signal.cancelled:
            raise asyncio.CancelledError
        try:
            lease = await self._service._engine.launch(
                role_id=PROGRAMMATIC_LONG_CONTEXT_P2_ROLE_ID,
                image_digest=self._service._image,
                workload_digest=PROGRAMMATIC_LONG_CONTEXT_P2_WORKLOAD_DIGEST,
                env=(),
                entrypoint=_ENTRYPOINT,
                seccomp=_SECCOMP,
                signal=self._signal,
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        valid = (
            type(lease) is not RestrictedWorkerLease
            or lease.role_id != self._request.role_id
            or lease.run_id != self._request.run_id
            or lease.challenge_digest != self._request.challenge_digest
            or lease.workload_digest != self._request.workload_digest
            or lease.worker_id in self._service._states
        )
        if valid:
            cleanup_error = await self._remove_after_rejection(lease)
            if isinstance(cleanup_error, asyncio.CancelledError):
                raise cleanup_error
            if cleanup_error is not None:
                raise RestrictedWorkerError(
                    "restricted worker value is invalid"
                ) from None
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._lease = lease
        self._service._states[lease.worker_id] = _State(self._request, lease)
        return lease

    async def __aexit__(self, *args: object) -> None:
        if self._lease is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        state = self._service._state(self._lease)
        cleanup_error = await self._remove_after_rejection(self._lease)
        if cleanup_error is not None and not isinstance(
            cleanup_error, asyncio.CancelledError
        ):
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        state.destroyed = True
        del self._service._states[self._lease.worker_id]
        if state.execution is None:
            if isinstance(cleanup_error, asyncio.CancelledError):
                raise cleanup_error
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._service._tombstones[self._lease.worker_id] = self._lease
        if isinstance(cleanup_error, asyncio.CancelledError):
            raise cleanup_error

    async def _remove_after_rejection(
        self, lease: RestrictedWorkerLease
    ) -> BaseException | None:
        task = asyncio.create_task(self._service._engine.remove(lease))
        cancellation: asyncio.CancelledError | None = None
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                cancellation = error
            except BaseException as error:
                return error
        if task.cancelled():
            return asyncio.CancelledError()
        try:
            task.result()
        except BaseException as error:
            return error
        return cancellation
