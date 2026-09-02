"""Host-private, bounded mediation for a Prime worker model session.

Trusted computing base: the host creates ``_HostModelCoordinator``, retains it
for revocation, and calls ``_activate`` only after worker admission.  It owns
the provider, launcher barrier, and channel-mint closure.  A worker receives
only ``PrimeModelChannel``.  Leading underscores communicate this internal
host boundary; Python object introspection is not an access-control claim.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Awaitable, Callable, Literal

from asterion.applications.prime_agent.operator.launcher_barrier import PrimeLauncherBarrier
from asterion.services.bounded_model_session import BoundedModelSessionLease, BoundedModelSessionRequest
from asterion.services.restricted_worker import RestrictedWorkerLease


Provider = Callable[[bytes], Awaitable[bytes]]
__all__ = ["PrimeModelBrokerError", "PrimeModelBrokerUsage", "PrimeModelBrokerReceipt", "PrimeModelChannel", "Provider"]


class PrimeModelBrokerError(ValueError):
    """A body-free failure at the host mediation boundary."""


@dataclass(frozen=True, repr=False)
class PrimeModelBrokerUsage:
    session_id: str
    run_id: str
    worker_id: str
    challenge_digest: str
    request_count: int
    input_bytes: int
    output_bytes: int

    def __repr__(self) -> str:
        return "PrimeModelBrokerUsage(redacted)"


@dataclass(frozen=True, repr=False)
class PrimeModelBrokerReceipt(PrimeModelBrokerUsage):
    status: Literal["revoked"]

    def __repr__(self) -> str:
        return "PrimeModelBrokerReceipt(redacted)"


class PrimeModelChannel:
    """The sole worker-facing capability; frames never enter public receipts."""

    __slots__ = ("_coordinator",)

    def __init__(self, coordinator: _HostModelCoordinator) -> None:
        self._coordinator = coordinator

    def __repr__(self) -> str:
        return "PrimeModelChannel(redacted)"

    async def request(self, body: bytes) -> bytes:
        return await self._coordinator._request(body)


class _HostModelCoordinator:
    """Host TCB: exact identity, barrier release, provider task, and cleanup."""

    __slots__ = (
        "_lease", "_session", "_worker", "_barrier", "_provider", "_deadline", "_grace",
        "_lock", "_activated", "_revoked", "_cleanup_uncertain", "_requests", "_input_bytes",
        "_output_bytes", "_inflight_task",
    )

    def __init__(
        self, *, lease: BoundedModelSessionLease, session: BoundedModelSessionRequest,
        worker: RestrictedWorkerLease, barrier: PrimeLauncherBarrier, provider: Provider,
        session_id: str, worker_id: str, run_id: str, challenge_digest: str, cleanup_grace_seconds: float,
    ) -> None:
        if (
            type(lease) is not BoundedModelSessionLease
            or type(session) is not BoundedModelSessionRequest
            or type(worker) is not RestrictedWorkerLease
            or type(barrier) is not PrimeLauncherBarrier
            or not callable(provider)
            or lease.run_id != session.run_id or worker.run_id != session.run_id
            or lease.session_id != session_id or worker.worker_id != worker_id
            or session.run_id != run_id or worker.challenge_digest != challenge_digest
            or type(cleanup_grace_seconds) not in (int, float) or cleanup_grace_seconds <= 0
        ):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        self._lease, self._session, self._worker = lease, session, worker
        self._barrier, self._provider = barrier, provider
        self._deadline = time.monotonic() + session.deadline_seconds
        self._grace = float(cleanup_grace_seconds)
        self._lock = asyncio.Lock()
        self._activated = self._revoked = self._cleanup_uncertain = False
        self._requests = self._input_bytes = self._output_bytes = 0
        self._inflight_task: asyncio.Task[bytes] | None = None

    def __repr__(self) -> str:
        return "_HostModelCoordinator(redacted)"

    def _activate(self) -> PrimeModelChannel:
        """Mint the channel inside the actual one-shot barrier release action."""
        if self._activated or self._revoked or self._cleanup_uncertain:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        channel: PrimeModelChannel | None = None

        def mint() -> None:
            nonlocal channel
            channel = PrimeModelChannel(self)

        try:
            self._barrier.release(self._worker, mint)
        except Exception:
            raise PrimeModelBrokerError("prime model broker is unavailable") from None
        if channel is None:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        self._activated = True
        return channel

    def usage(self) -> PrimeModelBrokerUsage:
        return PrimeModelBrokerUsage(self._lease.session_id, self._session.run_id, self._worker.worker_id,
            self._worker.challenge_digest, self._requests, self._input_bytes, self._output_bytes)

    async def revoke(self) -> PrimeModelBrokerReceipt:
        async with self._lock:
            self._revoked = True
            if self._cleanup_uncertain:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            task = self._inflight_task
        if task is not None and not await self._cancel_with_grace(task):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        if self._cleanup_uncertain:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        usage = self.usage()
        return PrimeModelBrokerReceipt(usage.session_id, usage.run_id, usage.worker_id,
            usage.challenge_digest, usage.request_count, usage.input_bytes, usage.output_bytes, "revoked")

    async def _request(self, body: bytes) -> bytes:
        if type(body) is not bytes:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        async with self._lock:
            if (not self._activated or self._revoked or self._cleanup_uncertain
                    or self._inflight_task is not None or time.monotonic() >= self._deadline
                    or self._requests >= self._session.max_requests
                    or self._input_bytes + len(body) > self._session.max_input_bytes):
                raise PrimeModelBrokerError("prime model broker is unavailable")
            self._requests += 1
            self._input_bytes += len(body)
            task = asyncio.create_task(self._invoke_provider(body))
            self._inflight_task = task
            task.add_done_callback(self._observe_terminal_task)
            remaining = self._deadline - time.monotonic()
        try:
            if remaining <= 0:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            done, _ = await asyncio.wait((task,), timeout=remaining)
            if not done:
                if not await self._cancel_with_grace(task):
                    raise PrimeModelBrokerError("prime model broker is unavailable")
                raise PrimeModelBrokerError("prime model broker is unavailable")
            if task.cancelled():
                raise PrimeModelBrokerError("prime model broker is unavailable")
            try:
                result = task.result()
            except asyncio.CancelledError:
                raise PrimeModelBrokerError("prime model broker is unavailable") from None
            except Exception:
                raise PrimeModelBrokerError("prime model broker is unavailable") from None
            async with self._lock:
                self._output_bytes += len(result)
                if self._revoked or self._output_bytes > self._session.max_output_bytes:
                    raise PrimeModelBrokerError("prime model broker is unavailable")
            return result
        except asyncio.CancelledError:
            async with self._lock:
                self._revoked = True
            await self._cancel_with_grace(task)
            raise

    async def _invoke_provider(self, body: bytes) -> bytes:
        """Keep synchronous provider invocation inside the tracked task."""
        result = await self._provider(body)
        if type(result) is not bytes:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        return result

    async def _cancel_with_grace(self, task: asyncio.Task[bytes]) -> bool:
        if not task.done():
            task.cancel()
            done, _ = await asyncio.wait((task,), timeout=self._grace)
            if not done:
                async with self._lock:
                    self._cleanup_uncertain = True
                    self._revoked = True
                return False
        return True

    def _observe_terminal_task(self, task: asyncio.Task[bytes]) -> None:
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass
        if self._inflight_task is task:
            self._inflight_task = None


def _new_host_coordinator(**kwargs: object) -> _HostModelCoordinator:
    """Host integration factory; deliberately excluded from the worker API."""
    try:
        return _HostModelCoordinator(**kwargs)  # type: ignore[arg-type]
    except (PrimeModelBrokerError, TypeError):
        raise PrimeModelBrokerError("prime model broker is unavailable") from None
