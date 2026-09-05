"""Closed application-host bridge for the P1 trusted completion supervisor.

This is deliberately an adapter seam, not a worker protocol.  Worker frames,
stdout, stderr, exit status, and claimed completion records have no route into
the supervisor.  The injected adapter is host-owned and supplies only the
typed daemon snapshots and broker observation needed to create attestations.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Awaitable, Callable, cast

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerWorkerModelResponse,
    DockerWorkerWorkspaceSnapshot,
)
from asterion.applications.prime_agent.operator.ipython_host_supervisor import (
    IpythonHostExpectedIdentity,
    IpythonHostSupervisor,
    IpythonHostSupervisorError,
    IpythonHostTrace,
    _new_ipython_host_supervisor,
)
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerReceipt,
    PrimeModelBrokerUsage,
)
from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import RestrictedWorkerLease


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLEANUP_SECONDS = 30.0

__all__ = (
    "IpythonHostOrchestrationError",
    "IpythonHostLiveRun",
)


class IpythonHostOrchestrationError(ValueError):
    """Body-free failure at the trusted P1 application-host boundary."""


@dataclass(frozen=True, repr=False)
class _IpythonBrokeredCell:
    """Private host observation tying a broker reply to the sent IPython cell."""

    identity: IpythonHostExpectedIdentity
    response: DockerWorkerModelResponse
    sent_cell_digest: str
    model_receipt_digest: str
    usage: PrimeModelBrokerUsage

    def __repr__(self) -> str:
        return "_IpythonBrokeredCell(redacted)"


_LIVE_RUN_SEAL = object()


class _IpythonHostOperations:
    """TCB-owned operations, minted by the concrete application host only.

    This is deliberately a nominal object rather than a protocol: shape-compatible
    values (including fakes) cannot enter the public completion path.
    """

    __slots__ = ("snapshot", "brokered_cell", "revoke_broker", "force_remove", "assert_absent", "_sealed")

    def __init__(
        self,
        *,
        _seal: object,
        snapshot: Callable[[RestrictedWorkerLease], Awaitable[DockerWorkerWorkspaceSnapshot]],
        brokered_cell: Callable[[RestrictedWorkerLease], Awaitable[_IpythonBrokeredCell]],
        revoke_broker: Callable[[RestrictedWorkerLease], Awaitable[PrimeModelBrokerReceipt]],
        force_remove: Callable[[RestrictedWorkerLease], Awaitable[None]],
        assert_absent: Callable[[RestrictedWorkerLease], Awaitable[None]],
    ) -> None:
        if _seal is not _LIVE_RUN_SEAL:
            _reject()
        self.snapshot = snapshot
        self.brokered_cell = brokered_cell
        self.revoke_broker = revoke_broker
        self.force_remove = force_remove
        self.assert_absent = assert_absent
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("sealed host operations")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        del name
        raise AttributeError("sealed host operations")


class IpythonHostLiveRun:
    """Sealed concrete host context that can produce a validated trace only."""

    __slots__ = ("_identity", "_lease", "_operations", "_signal", "_sealed")

    def __init__(
        self,
        *,
        _seal: object = None,
        identity: object = None,
        lease: object = None,
        operations: object = None,
        signal: CancellationSignal | None = None,
    ) -> None:
        if (
            _seal is not _LIVE_RUN_SEAL
            or type(identity) is not IpythonHostExpectedIdentity
            or type(lease) is not RestrictedWorkerLease
            or type(operations) is not _IpythonHostOperations
            or identity.workload_digest != lease.workload_digest
        ):
            _reject()
        self._identity: IpythonHostExpectedIdentity = cast(IpythonHostExpectedIdentity, identity)
        self._lease: RestrictedWorkerLease = cast(RestrictedWorkerLease, lease)
        self._operations: _IpythonHostOperations = cast(_IpythonHostOperations, operations)
        self._signal = signal
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("sealed live run")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        del name
        raise AttributeError("sealed live run")

    async def trace(self) -> IpythonHostTrace:
        return await _trace_issued_live_run(self)


def _issue_ipython_host_live_run(
    *, identity: IpythonHostExpectedIdentity, lease: RestrictedWorkerLease,
    operations: _IpythonHostOperations, signal: CancellationSignal | None = None,
) -> IpythonHostLiveRun:
    """Private concrete-factory hook for the Docker/model application host."""
    return IpythonHostLiveRun(
        _seal=_LIVE_RUN_SEAL, identity=identity, lease=lease,
        operations=operations, signal=signal,
    )


async def _trace_issued_live_run(live_run: IpythonHostLiveRun) -> IpythonHostTrace:
    """Validate the closed host-observed causal chain and return its trace."""
    if (
        type(live_run) is not IpythonHostLiveRun
    ):
        _reject()

    identity, lease = live_run._identity, live_run._lease
    operations, signal = live_run._operations, live_run._signal
    supervisor: IpythonHostSupervisor | None = None
    post: DockerWorkerWorkspaceSnapshot | None = None
    broker_revoked = False
    body_error: BaseException | None = None
    try:
        supervisor = _new_ipython_host_supervisor(identity)
        _check_cancel(signal, supervisor)
        initial = await operations.snapshot(lease)
        _record_initial(supervisor, initial)
        _check_cancel(signal, supervisor)

        observed = await operations.brokered_cell(lease)
        _record_brokered_cell(supervisor, identity, lease, observed)
        _check_cancel(signal, supervisor)

        post = await operations.snapshot(lease)
        _record_post(supervisor, post)
        _check_cancel(signal, supervisor)

        revocation = await operations.revoke_broker(lease)
        broker_revoked = True
        _record_broker_revocation(supervisor, identity, lease, revocation)
        _check_cancel(signal, supervisor)
    except asyncio.CancelledError:
        if supervisor is not None:
            _cancel(supervisor)
        body_error = asyncio.CancelledError()
    except BaseException:
        if supervisor is not None:
            _cancel(supervisor)
        body_error = IpythonHostOrchestrationError(
            "ipython host orchestration is unavailable"
        )

    cleanup_error = await _cleanup(operations, lease, broker_revoked)

    if isinstance(cleanup_error, asyncio.CancelledError):
        raise asyncio.CancelledError() from None
    if isinstance(body_error, asyncio.CancelledError):
        raise asyncio.CancelledError() from None
    if cleanup_error is not None or body_error is not None:
        raise IpythonHostOrchestrationError("ipython host orchestration is unavailable") from None
    if supervisor is None or post is None:
        _reject()
    typed_supervisor = cast(IpythonHostSupervisor, supervisor)
    typed_post = cast(DockerWorkerWorkspaceSnapshot, post)
    try:
        typed_supervisor.record_cleanup(typed_supervisor._attest_cleanup_and_absence())  # noqa: SLF001
        _check_cancel(signal, typed_supervisor)
        # This is intentionally after broker quiescence and verified absence.
        final = typed_supervisor._attest_final_oracle(typed_post.source)  # noqa: SLF001
        return typed_supervisor.finalize_trace(final)
    except asyncio.CancelledError:
        _cancel(typed_supervisor)
        raise asyncio.CancelledError() from None
    except BaseException:
        _cancel(typed_supervisor)
        raise IpythonHostOrchestrationError("ipython host orchestration is unavailable") from None


def _record_initial(
    supervisor: IpythonHostSupervisor, snapshot: object
) -> None:
    if type(snapshot) is not DockerWorkerWorkspaceSnapshot:
        _reject()
    typed_snapshot = cast(DockerWorkerWorkspaceSnapshot, snapshot)
    supervisor.record_initial_snapshot(
        supervisor._attest_initial_snapshot(typed_snapshot.source, is_regular_file=True)  # noqa: SLF001
    )


def _record_brokered_cell(
    supervisor: IpythonHostSupervisor,
    identity: IpythonHostExpectedIdentity,
    lease: RestrictedWorkerLease,
    observed: object,
) -> None:
    if type(observed) is not _IpythonBrokeredCell:
        _reject()
    typed_observed = cast(_IpythonBrokeredCell, observed)
    response, usage = typed_observed.response, typed_observed.usage
    cell = response.cell.encode("utf-8", "strict") if type(response) is DockerWorkerModelResponse else b""
    if (
        type(typed_observed.identity) is not IpythonHostExpectedIdentity
        or typed_observed.identity != identity
        or type(response) is not DockerWorkerModelResponse
        or response.workload_digest != lease.workload_digest
        or response.tool != "ipython"
        or not _valid_digest(typed_observed.sent_cell_digest)
        or typed_observed.sent_cell_digest != "sha256:" + sha256(cell).hexdigest()
        or not _valid_digest(typed_observed.model_receipt_digest)
        or type(usage) is not PrimeModelBrokerUsage
        or usage.run_id != lease.run_id
        or usage.worker_id != lease.worker_id
        or usage.challenge_digest != lease.challenge_digest
        or type(usage.request_count) is not int
        or usage.request_count != identity.expected_provider_request_count
        or usage.input_bytes <= 0
        or usage.output_bytes <= 0
    ):
        _reject()
    supervisor.record_brokered_cell(
        supervisor._attest_brokered_cell(  # noqa: SLF001
            identity=identity,
            cell=cell,
            bounded_model_digest=typed_observed.model_receipt_digest,
            request_count=usage.request_count,
            input_bytes=usage.input_bytes,
            output_bytes=usage.output_bytes,
        )
    )


def _record_post(supervisor: IpythonHostSupervisor, snapshot: object) -> None:
    if type(snapshot) is not DockerWorkerWorkspaceSnapshot:
        _reject()
    typed_snapshot = cast(DockerWorkerWorkspaceSnapshot, snapshot)
    supervisor.record_post_snapshot(
        supervisor._attest_post_snapshot(typed_snapshot.source, is_regular_file=True)  # noqa: SLF001
    )


def _record_broker_revocation(
    supervisor: IpythonHostSupervisor,
    identity: IpythonHostExpectedIdentity,
    lease: RestrictedWorkerLease,
    receipt: object,
) -> None:
    if (
        type(receipt) is not PrimeModelBrokerReceipt
        or receipt.status != "revoked"
        or receipt.quiesced is not True
        or receipt.run_id != lease.run_id
        or receipt.worker_id != lease.worker_id
        or receipt.challenge_digest != lease.challenge_digest
        or type(receipt.request_count) is not int
        or receipt.request_count != identity.expected_provider_request_count
        or receipt.input_bytes <= 0
        or receipt.output_bytes <= 0
    ):
        _reject()
    typed_receipt = cast(PrimeModelBrokerReceipt, receipt)
    supervisor.record_broker_revoked(
        supervisor._attest_broker_revocation(  # noqa: SLF001
            session_id=typed_receipt.session_id, request_count=typed_receipt.request_count,
            input_bytes=typed_receipt.input_bytes, output_bytes=typed_receipt.output_bytes,
        )
    )


async def _cleanup(
    operations: _IpythonHostOperations, lease: RestrictedWorkerLease, broker_revoked: bool
) -> BaseException | None:
    async def run() -> None:
        revocation_error: BaseException | None = None
        if not broker_revoked:
            revocation_error = await _bounded_cleanup_step(operations.revoke_broker, lease)
        # Absence is independently attempted even when force removal fails.
        removal_error = await _bounded_cleanup_step(operations.force_remove, lease)
        absence_error = await _bounded_cleanup_step(operations.assert_absent, lease)
        if removal_error is not None:
            raise removal_error
        if absence_error is not None:
            raise absence_error
        if revocation_error is not None:
            raise revocation_error

    task = asyncio.create_task(run())
    cancellation = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancellation = True
        except BaseException:
            break
    if task.cancelled():
        return asyncio.CancelledError()
    error = task.exception() if task.done() else None
    if isinstance(error, asyncio.CancelledError) or cancellation:
        return asyncio.CancelledError()
    return error


async def _bounded_cleanup_step(
    operation: Callable[[RestrictedWorkerLease], Awaitable[object]], lease: RestrictedWorkerLease
) -> BaseException | None:
    """Bound each cleanup operation and give cancellation a finite reaping grace."""
    async def invoke() -> None:
        await operation(lease)

    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=_CLEANUP_SECONDS / 3)
    except TimeoutError:
        task.cancel()
        await _reap_cleanup_task(task)
        return IpythonHostOrchestrationError("ipython host orchestration is unavailable")
    except BaseException as error:
        return error
    return None


async def _reap_cleanup_task(task: asyncio.Task[None]) -> None:
    """Observe a canceled task briefly; detach it if it ignores cancellation."""
    try:
        await asyncio.wait_for(
            asyncio.shield(task), timeout=_CLEANUP_SECONDS / 3
        )
    except TimeoutError:
        task.add_done_callback(_observe_cleanup_task)
    except BaseException:
        pass


def _observe_cleanup_task(task: asyncio.Task[None]) -> None:
    """Consume a detached cleanup task outcome without exposing it publicly."""
    try:
        task.exception()
    except BaseException:
        pass


def _check_cancel(signal: CancellationSignal | None, supervisor: IpythonHostSupervisor) -> None:
    if signal is not None and signal.cancelled:
        _cancel(supervisor)
        raise asyncio.CancelledError


def _cancel(supervisor: IpythonHostSupervisor) -> None:
    try:
        supervisor.cancel()
    except IpythonHostSupervisorError:
        pass


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _reject() -> None:
    raise IpythonHostOrchestrationError("ipython host orchestration is unavailable")
