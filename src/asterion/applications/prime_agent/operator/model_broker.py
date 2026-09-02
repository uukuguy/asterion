"""Operator-owned, bounded mediation for one Prime worker model session.

Provider configuration is deliberately represented only by the injected callable.
The public values below contain accounting and identity, never model bodies or
provider configuration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Awaitable, Callable, Literal

from asterion.services.bounded_model_session import (
    BoundedModelSessionLease,
    BoundedModelSessionRequest,
)
from asterion.services.restricted_worker import RestrictedWorkerLease
from asterion.applications.prime_agent.operator.launcher_barrier import PrimeLauncherBarrier


Provider = Callable[[bytes], Awaitable[bytes]]


class PrimeModelBrokerError(ValueError):
    """Raised for a closed or invalid broker operation, without private detail."""


@dataclass(frozen=True, repr=False)
class PrimeModelBrokerUsage:
    """Body-free accounting for the bound, still-open session."""

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
    """Body-free terminal accounting receipt."""

    status: Literal["revoked"]

    def __repr__(self) -> str:
        return "PrimeModelBrokerReceipt(redacted)"


class PrimeModelChannel:
    """Private launcher-facing channel; its frames never become receipts."""

    __slots__ = ("_broker",)

    def __init__(self, broker: PrimeModelBroker) -> None:
        self._broker = broker

    def __repr__(self) -> str:
        return "PrimeModelChannel(redacted)"

    async def request(self, body: bytes) -> bytes:
        """Relay one private frame through the operator-owned provider callable."""
        return await self._broker._request(body)


class _LauncherReleaseProof:
    """An internal marker minted only by a released launcher barrier."""

    __slots__ = ("_worker",)

    def __init__(self, worker: RestrictedWorkerLease) -> None:
        self._worker = worker

    def __repr__(self) -> str:
        return "_LauncherReleaseProof(redacted)"


def _launcher_release_proof(
    barrier: PrimeLauncherBarrier, worker: RestrictedWorkerLease
) -> _LauncherReleaseProof:
    """Mint a private proof from inside the barrier's release action only."""
    if (
        type(barrier) is not PrimeLauncherBarrier
        or type(worker) is not RestrictedWorkerLease
        or barrier._released is not True  # noqa: SLF001 - deliberate private boundary coupling
        or barrier._worker_id != worker.worker_id  # noqa: SLF001
        or barrier._run_id != worker.run_id  # noqa: SLF001
        or barrier._challenge_digest != worker.challenge_digest  # noqa: SLF001
    ):
        raise PrimeModelBrokerError("prime model broker is unavailable")
    return _LauncherReleaseProof(worker)


class PrimeModelBroker:
    """Enforce finite session limits around an injected asynchronous provider."""

    __slots__ = (
        "_lease", "_session", "_worker", "_provider", "_deadline", "_monotonic",
        "_lock", "_quiescent", "_released", "_revoked", "_inflight", "_requests",
        "_input_bytes", "_output_bytes",
    )

    def __init__(
        self,
        *,
        lease: BoundedModelSessionLease,
        session: BoundedModelSessionRequest,
        worker: RestrictedWorkerLease,
        provider: Provider,
        session_id: str = "session-1",
        worker_id: str,
        run_id: str,
        challenge_digest: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            type(lease) is not BoundedModelSessionLease
            or type(session) is not BoundedModelSessionRequest
            or type(worker) is not RestrictedWorkerLease
            or not callable(provider)
            or not callable(monotonic)
            or lease.run_id != session.run_id
            or lease.session_id != session_id
            or worker.run_id != session.run_id
            or worker.worker_id != worker_id
            or session.run_id != run_id
            or worker.challenge_digest != challenge_digest
        ):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        now = monotonic()
        if type(now) not in (int, float):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        self._lease = lease
        self._session = session
        self._worker = worker
        self._provider = provider
        self._deadline = float(now) + session.deadline_seconds
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._quiescent = asyncio.Event()
        self._quiescent.set()
        self._released = False
        self._revoked = False
        self._inflight = False
        self._requests = 0
        self._input_bytes = 0
        self._output_bytes = 0

    def __repr__(self) -> str:
        return "PrimeModelBroker(redacted)"

    def _release_after_launcher(self, proof: _LauncherReleaseProof) -> PrimeModelChannel:
        """Open the sole private channel from a proof minted by barrier release."""
        if (
            type(proof) is not _LauncherReleaseProof
            or self._released
            or self._revoked
            or proof._worker != self._worker
        ):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        self._released = True
        return PrimeModelChannel(self)

    def usage(self) -> PrimeModelBrokerUsage:
        return PrimeModelBrokerUsage(
            self._lease.session_id, self._session.run_id, self._worker.worker_id,
            self._worker.challenge_digest, self._requests, self._input_bytes, self._output_bytes,
        )

    async def revoke(self) -> PrimeModelBrokerReceipt:
        """Close admission and wait for an admitted provider call to settle."""
        async with self._lock:
            self._revoked = True
            wait_for_quiescence = self._inflight
        if wait_for_quiescence:
            await self._quiescent.wait()
        usage = self.usage()
        return PrimeModelBrokerReceipt(
            usage.session_id, usage.run_id, usage.worker_id, usage.challenge_digest,
            usage.request_count, usage.input_bytes, usage.output_bytes, "revoked",
        )

    async def _request(self, body: bytes) -> bytes:
        if type(body) is not bytes:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        async with self._lock:
            if (
                not self._released
                or self._revoked
                or self._inflight
                or self._expired()
                or self._requests >= self._session.max_requests
                or self._input_bytes + len(body) > self._session.max_input_bytes
            ):
                raise PrimeModelBrokerError("prime model broker is unavailable")
            self._requests += 1
            self._input_bytes += len(body)
            self._inflight = True
            self._quiescent.clear()
        try:
            result = await self._provider(body)
            if type(result) is not bytes:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            async with self._lock:
                if self._output_bytes + len(result) > self._session.max_output_bytes:
                    raise PrimeModelBrokerError("prime model broker is unavailable")
                self._output_bytes += len(result)
            return result
        except PrimeModelBrokerError:
            raise
        except Exception:
            raise PrimeModelBrokerError("prime model broker is unavailable") from None
        finally:
            async with self._lock:
                self._inflight = False
                self._quiescent.set()

    def _expired(self) -> bool:
        return float(self._monotonic()) >= self._deadline
