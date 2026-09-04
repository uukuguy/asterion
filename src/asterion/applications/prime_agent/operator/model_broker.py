"""Host-private framed mediation for a bounded Prime model session.

The host TCB owns the coordinator, provider, launcher barrier, and host side
of an in-process transport.  The worker receives only a framed channel with a
fixed identity and worker endpoint.  This is test transport for eventual IPC,
not a claim that Python prevents arbitrary hostile host introspection.
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
__all__ = ["PrimeModelBrokerError", "PrimeModelBrokerUsage", "PrimeModelBrokerReceipt", "PrimeModelBrokerTokenUsage", "PrimeModelChannel", "Provider"]


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
class PrimeModelBrokerTokenUsage:
    """Body-free provider accounting admitted into a terminal broker receipt."""

    input_tokens: int
    output_tokens: int
    cost_microunits: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.cost_microunits,
            )
        ):
            raise PrimeModelBrokerError("prime model broker is unavailable")

    def __repr__(self) -> str:
        return "PrimeModelBrokerTokenUsage(redacted)"


@dataclass(frozen=True, repr=False)
class PrimeModelBrokerReceipt(PrimeModelBrokerUsage):
    status: Literal["revoked"]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_microunits: int = 0
    quiesced: Literal[True] = True

    def __repr__(self) -> str:
        return "PrimeModelBrokerReceipt(redacted)"


@dataclass(frozen=True)
class _FrameIdentity:
    session_id: str
    run_id: str
    worker_id: str
    challenge_digest: str


class _Frame:
    __slots__ = ("identity", "body", "reply", "cancelled")

    def __init__(self, identity: _FrameIdentity, body: bytes, reply: asyncio.Future[bytes]) -> None:
        self.identity, self.body, self.reply = identity, body, reply
        self.cancelled = asyncio.Event()


class _TransportState:
    __slots__ = ("frames", "closed")

    def __init__(self) -> None:
        self.frames: asyncio.Queue[_Frame | None] = asyncio.Queue()
        self.closed = False


class _WorkerEndpoint:
    """Worker half: request/response frames only, with no host object route."""

    __slots__ = ("_state",)

    def __init__(self, state: _TransportState) -> None:
        self._state = state

    async def exchange(self, frame: _Frame) -> bytes:
        if self._state.closed:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        await self._state.frames.put(frame)
        try:
            return await frame.reply
        except asyncio.CancelledError:
            frame.cancelled.set()
            raise


class _HostEndpoint:
    __slots__ = ("_state",)

    def __init__(self, state: _TransportState) -> None:
        self._state = state

    async def next_frame(self) -> _Frame | None:
        return await self._state.frames.get()

    def close(self) -> None:
        if not self._state.closed:
            self._state.closed = True
            self._state.frames.put_nowait(None)


class PrimeModelChannel:
    """Worker-facing framed endpoint; bodies never appear in receipts."""

    __slots__ = ("_transport", "_identity")

    def __init__(self, transport: _WorkerEndpoint, identity: _FrameIdentity) -> None:
        self._transport, self._identity = transport, identity

    def __repr__(self) -> str:
        return "PrimeModelChannel(redacted)"

    async def request(self, body: bytes) -> bytes:
        if type(body) is not bytes:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        reply: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        return await self._transport.exchange(_Frame(self._identity, body, reply))


_HOST_BROKER_ARTIFACT_SEAL = object()


@dataclass(frozen=True, repr=False)
class _PrimeBrokerHostArtifacts:
    """One activated broker/channel pair, minted only by its coordinator."""

    coordinator: object
    worker: RestrictedWorkerLease
    channel: PrimeModelChannel
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _HOST_BROKER_ARTIFACT_SEAL:
            raise PrimeModelBrokerError("prime model broker is unavailable")

    def __repr__(self) -> str:
        return "_PrimeBrokerHostArtifacts(redacted)"


class _HostModelCoordinator:
    """Host TCB: validates frames and owns lifecycle/provider execution."""

    __slots__ = (
        "_lease", "_session", "_worker", "_barrier", "_provider", "_deadline", "_grace", "_host",
        "_lock", "_activated", "_revoked", "_cleanup_uncertain", "_requests", "_input_bytes",
        "_output_bytes", "_inflight_task", "_server_task", "_identity", "_terminal_usage",
    )

    def __init__(self, *, lease: BoundedModelSessionLease, session: BoundedModelSessionRequest,
        worker: RestrictedWorkerLease, barrier: PrimeLauncherBarrier, provider: Provider, session_id: str,
        worker_id: str, run_id: str, challenge_digest: str, cleanup_grace_seconds: float,
        terminal_usage: Callable[[], PrimeModelBrokerTokenUsage] | None = None) -> None:
        if (type(lease) is not BoundedModelSessionLease or type(session) is not BoundedModelSessionRequest
                or type(worker) is not RestrictedWorkerLease or type(barrier) is not PrimeLauncherBarrier
                or not callable(provider) or lease.run_id != session.run_id or worker.run_id != session.run_id
                or lease.session_id != session_id or worker.worker_id != worker_id or session.run_id != run_id
                or worker.challenge_digest != challenge_digest or type(cleanup_grace_seconds) not in (int, float)
                or cleanup_grace_seconds <= 0 or terminal_usage is not None and not callable(terminal_usage)):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        self._lease, self._session, self._worker = lease, session, worker
        self._barrier, self._provider = barrier, provider
        self._deadline, self._grace = time.monotonic() + session.deadline_seconds, float(cleanup_grace_seconds)
        state = _TransportState()
        self._host = _HostEndpoint(state)
        self._identity = _FrameIdentity(session_id, run_id, worker_id, challenge_digest)
        self._terminal_usage = terminal_usage
        self._lock = asyncio.Lock()
        self._activated = self._revoked = self._cleanup_uncertain = False
        self._requests = self._input_bytes = self._output_bytes = 0
        self._inflight_task: asyncio.Task[bytes] | None = None
        self._server_task: asyncio.Task[None] | None = None

    def __repr__(self) -> str:
        return "_HostModelCoordinator(redacted)"

    def _activate(self) -> PrimeModelChannel:
        if self._activated or self._revoked or self._cleanup_uncertain:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        channel: PrimeModelChannel | None = None

        def mint() -> None:
            nonlocal channel
            state = self._host._state  # noqa: SLF001 - paired endpoints share only transport state
            channel = PrimeModelChannel(_WorkerEndpoint(state), self._identity)

        try:
            self._barrier.release(self._worker, mint)
        except Exception:
            raise PrimeModelBrokerError("prime model broker is unavailable") from None
        if channel is None:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        self._activated = True
        self._server_task = asyncio.create_task(self._serve())
        return channel

    def usage(self) -> PrimeModelBrokerUsage:
        return PrimeModelBrokerUsage(self._lease.session_id, self._session.run_id, self._worker.worker_id,
            self._worker.challenge_digest, self._requests, self._input_bytes, self._output_bytes)

    def _host_artifacts(self, worker: RestrictedWorkerLease) -> _PrimeBrokerHostArtifacts:
        """Activate exactly once and seal the channel to the admitted worker."""
        if type(worker) is not RestrictedWorkerLease or worker is not self._worker:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        return _PrimeBrokerHostArtifacts(self, worker, self._activate(), _HOST_BROKER_ARTIFACT_SEAL)

    def _host_validate_artifacts(self, artifacts: object) -> _PrimeBrokerHostArtifacts:
        if (
            type(artifacts) is not _PrimeBrokerHostArtifacts
            or artifacts._seal is not _HOST_BROKER_ARTIFACT_SEAL
            or artifacts.coordinator is not self
            or artifacts.worker is not self._worker
            or type(artifacts.channel) is not PrimeModelChannel
        ):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        return artifacts

    async def revoke(self) -> PrimeModelBrokerReceipt:
        async with self._lock:
            self._revoked = True
            self._host.close()
            if self._cleanup_uncertain:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            task = self._inflight_task
        if task is not None and not await self._cancel_with_grace(task):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        if not await self._await_server_quiescence():
            async with self._lock:
                self._cleanup_uncertain = True
            raise PrimeModelBrokerError("prime model broker is unavailable")
        token_usage = (
            PrimeModelBrokerTokenUsage(0, 0, 0)
            if self._terminal_usage is None
            else self._terminal_usage()
        )
        if (
            type(token_usage) is not PrimeModelBrokerTokenUsage
            or token_usage.input_tokens > self._session.max_input_tokens
            or token_usage.output_tokens > self._session.max_output_tokens
            or token_usage.cost_microunits > self._session.max_cost_microunits
        ):
            raise PrimeModelBrokerError("prime model broker is unavailable")
        usage = self.usage()
        return PrimeModelBrokerReceipt(usage.session_id, usage.run_id, usage.worker_id,
            usage.challenge_digest, usage.request_count, usage.input_bytes, usage.output_bytes,
            "revoked", token_usage.input_tokens, token_usage.output_tokens,
            token_usage.cost_microunits, True)

    async def _await_server_quiescence(self) -> bool:
        task = self._server_task
        if task is None:
            return True
        done, _ = await asyncio.wait((task,), timeout=self._grace)
        if not done:
            task.cancel()
            done, _ = await asyncio.wait((task,), timeout=self._grace)
        if not done:
            return False
        try:
            task.result()
        except asyncio.CancelledError:
            return True
        except Exception:
            return False
        return True

    async def _serve(self) -> None:
        while True:
            frame = await self._host.next_frame()
            if frame is None:
                return
            await self._handle(frame)

    async def _handle(self, frame: _Frame) -> None:
        try:
            if type(frame) is not _Frame or frame.identity != self._identity or type(frame.body) is not bytes:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            async with self._lock:
                if (self._revoked or self._cleanup_uncertain or self._inflight_task is not None
                        or time.monotonic() >= self._deadline or self._requests >= self._session.max_requests
                        or self._input_bytes + len(frame.body) > self._session.max_input_bytes):
                    raise PrimeModelBrokerError("prime model broker is unavailable")
                self._requests += 1
                self._input_bytes += len(frame.body)
                task = asyncio.create_task(self._invoke_provider(frame.body))
                self._inflight_task = task
                task.add_done_callback(self._observe_terminal_task)
                remaining = self._deadline - time.monotonic()
            cancelled_wait = asyncio.create_task(frame.cancelled.wait())
            try:
                done, _ = await asyncio.wait((task, cancelled_wait), timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED)
                if not done or cancelled_wait in done:
                    async with self._lock:
                        self._revoked = True
                        self._host.close()
                    await self._cancel_with_grace(task)
                    raise PrimeModelBrokerError("prime model broker is unavailable")
                if task.cancelled():
                    raise PrimeModelBrokerError("prime model broker is unavailable")
                try:
                    result = task.result()
                except (asyncio.CancelledError, Exception):
                    raise PrimeModelBrokerError("prime model broker is unavailable") from None
            finally:
                cancelled_wait.cancel()
            async with self._lock:
                self._output_bytes += len(result)
                if self._revoked or self._output_bytes > self._session.max_output_bytes:
                    self._revoked = True
                    self._host.close()
                    raise PrimeModelBrokerError("prime model broker is unavailable")
            self._reply(frame, result)
        except PrimeModelBrokerError as error:
            self._reply_error(frame, error)

    async def _invoke_provider(self, body: bytes) -> bytes:
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
                    self._cleanup_uncertain = self._revoked = True
                    self._host.close()
                return False
        return True

    def _observe_terminal_task(self, task: asyncio.Task[bytes]) -> None:
        try:
            task.result()
        except (asyncio.CancelledError, Exception):
            pass
        if self._inflight_task is task:
            self._inflight_task = None

    @staticmethod
    def _reply(frame: _Frame, result: bytes) -> None:
        if not frame.reply.done():
            frame.reply.set_result(result)

    @staticmethod
    def _reply_error(frame: _Frame, error: PrimeModelBrokerError) -> None:
        if not frame.reply.done():
            frame.reply.set_exception(error)


def _new_host_coordinator(**kwargs: object) -> _HostModelCoordinator:
    """Host-only factory, excluded from the worker API."""
    try:
        return _HostModelCoordinator(**kwargs)  # type: ignore[arg-type]
    except (PrimeModelBrokerError, TypeError):
        raise PrimeModelBrokerError("prime model broker is unavailable") from None
