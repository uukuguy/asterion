"""Sealed lifecycle facade for literal Prime restricted-worker scenarios."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from hashlib import sha256
from typing import Callable, Protocol

from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import (
    RestrictedWorkerAttestation,
    RestrictedWorkerCleanupReceipt,
    RestrictedWorkerError,
    RestrictedWorkerExecutionReceipt,
    RestrictedWorkerLease,
    RestrictedWorkerRequest,
)


@dataclass(frozen=True)
class RestrictedScenarioAdapter:
    scenario_id: str
    role_id: str
    workload_digest: str
    entrypoint: str
    seccomp: str
    max_runtime_seconds: int
    max_output_bytes: int
    parse_completion: Callable[[bytes], bool]


@dataclass(frozen=True, repr=False)
class RestrictedScenarioInspection:
    lease: RestrictedWorkerLease
    image_digest: str
    entrypoint: str
    seccomp: str
    env: tuple[str, ...]
    network_isolated: bool
    root_read_only: bool
    workspace_disposable: bool
    credentials_absent: bool
    kernel_credential_absent: bool
    source_read_only: bool
    resource_limited: bool


class RestrictedScenarioEngine(Protocol):
    async def launch(self, **kwargs: object) -> RestrictedWorkerLease: ...
    async def completion_bytes(self, lease: RestrictedWorkerLease) -> bytes: ...
    async def inspect(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedScenarioInspection: ...
    async def remove(self, lease: RestrictedWorkerLease) -> None: ...


@dataclass
class _State:
    request: RestrictedWorkerRequest
    lease: RestrictedWorkerLease
    execution: RestrictedWorkerExecutionReceipt | None = None
    attestation: RestrictedWorkerAttestation | None = None


class RestrictedScenarioWorker:
    def __init__(
        self,
        *,
        image_digest: str,
        engine: RestrictedScenarioEngine,
        adapter: RestrictedScenarioAdapter,
    ) -> None:
        if (
            type(image_digest) is not str
            or not image_digest.startswith("sha256:")
            or type(adapter) is not RestrictedScenarioAdapter
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._image, self._engine, self._adapter = image_digest, engine, adapter
        self._states: dict[str, _State] = {}
        self._tombstones: dict[str, RestrictedWorkerLease] = {}

    def request_for(self, request: RestrictedWorkerRequest) -> RestrictedWorkerRequest:
        if (
            type(request) is not RestrictedWorkerRequest
            or request.role_id != self._adapter.role_id
            or request.image_digest != self._image
            or request.workload_digest != self._adapter.workload_digest
            or request.max_runtime_seconds > self._adapter.max_runtime_seconds
            or request.max_output_bytes > self._adapter.max_output_bytes
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

    def _state(self, lease: RestrictedWorkerLease) -> _State:
        state = (
            self._states.get(lease.worker_id)
            if type(lease) is RestrictedWorkerLease
            else None
        )
        if state is None or state.lease != lease:
            raise RestrictedWorkerError("restricted worker value is invalid")
        return state

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
            try:
                valid = self._adapter.parse_completion(raw)
            except BaseException:
                valid = False
            if valid is not True:
                raise RestrictedWorkerError("restricted worker value is invalid")
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
        if state.attestation is None:
            try:
                observed = await self._engine.inspect(lease)
            except asyncio.CancelledError:
                raise
            except BaseException:
                raise RestrictedWorkerError(
                    "restricted worker value is invalid"
                ) from None
            if (
                type(observed) is not RestrictedScenarioInspection
                or observed.lease != lease
                or observed.image_digest != self._image
                or observed.entrypoint != self._adapter.entrypoint
                or observed.seccomp != self._adapter.seccomp
                or observed.env != ()
                or not all(
                    (
                        observed.network_isolated,
                        observed.root_read_only,
                        observed.workspace_disposable,
                        observed.credentials_absent,
                        observed.kernel_credential_absent,
                        observed.source_read_only,
                        observed.resource_limited,
                    )
                )
            ):
                raise RestrictedWorkerError("restricted worker value is invalid")
            state.attestation = RestrictedWorkerAttestation(
                lease.worker_id,
                lease.role_id,
                lease.run_id,
                lease.challenge_digest,
                lease.workload_digest,
                self._image,
                True,
                True,
                True,
                True,
                True,
                True,
                True,
            )
        return state.attestation

    async def cleanup_receipt(
        self, lease: RestrictedWorkerLease
    ) -> RestrictedWorkerCleanupReceipt:
        if (
            type(lease) is not RestrictedWorkerLease
            or self._tombstones.get(lease.worker_id) != lease
        ):
            raise RestrictedWorkerError("restricted worker value is invalid")
        del self._tombstones[lease.worker_id]
        return RestrictedWorkerCleanupReceipt(
            lease.worker_id,
            lease.role_id,
            lease.run_id,
            lease.challenge_digest,
            lease.workload_digest,
            True,
        )


class _Context(AbstractAsyncContextManager[RestrictedWorkerLease]):
    def __init__(
        self,
        worker: RestrictedScenarioWorker,
        request: RestrictedWorkerRequest,
        signal: CancellationSignal | None,
    ) -> None:
        self._worker, self._request, self._signal, self._lease = (
            worker,
            request,
            signal,
            None,
        )

    async def __aenter__(self) -> RestrictedWorkerLease:
        if self._signal is not None and self._signal.cancelled:
            raise asyncio.CancelledError
        try:
            lease = await self._worker._engine.launch(
                role_id=self._worker._adapter.role_id,
                image_digest=self._worker._image,
                workload_digest=self._worker._adapter.workload_digest,
                env=(),
                entrypoint=self._worker._adapter.entrypoint,
                seccomp=self._worker._adapter.seccomp,
                signal=self._signal,
            )
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        if (
            type(lease) is not RestrictedWorkerLease
            or lease.role_id != self._request.role_id
            or lease.run_id != self._request.run_id
            or lease.challenge_digest != self._request.challenge_digest
            or lease.workload_digest != self._request.workload_digest
            or lease.worker_id in self._worker._states
        ):
            try:
                await self._worker._engine.remove(lease)
            except BaseException:
                pass
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._lease = lease
        self._worker._states[lease.worker_id] = _State(self._request, lease)
        return lease

    async def __aexit__(self, *args: object) -> None:
        if self._lease is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        state = self._worker._state(self._lease)
        try:
            await self._worker._engine.remove(self._lease)
        except asyncio.CancelledError:
            raise
        except BaseException:
            raise RestrictedWorkerError("restricted worker value is invalid") from None
        del self._worker._states[self._lease.worker_id]
        if state.execution is None:
            raise RestrictedWorkerError("restricted worker value is invalid")
        self._worker._tombstones[self._lease.worker_id] = self._lease
