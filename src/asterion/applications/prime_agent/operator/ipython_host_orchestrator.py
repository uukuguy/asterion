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
from typing import Protocol, cast, runtime_checkable

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerWorkerModelResponse,
    DockerWorkerWorkspaceSnapshot,
)
from asterion.applications.prime_agent.operator.ipython_host_supervisor import (
    IpythonHostCompletion,
    IpythonHostExpectedIdentity,
    IpythonHostSupervisor,
    IpythonHostSupervisorError,
)
from asterion.applications.prime_agent.operator.model_broker import PrimeModelBrokerUsage
from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import RestrictedWorkerLease


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

__all__ = (
    "IpythonHostOrchestrationError",
    "run_ipython_host_orchestration",
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


@runtime_checkable
class _IpythonHostAdapter(Protocol):
    """Private host operations; implementations must not expose worker output."""

    async def snapshot(self, lease: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot: ...

    async def brokered_cell(self, lease: RestrictedWorkerLease) -> _IpythonBrokeredCell: ...

    async def revoke_broker(self, lease: RestrictedWorkerLease) -> None: ...

    async def force_remove(self, lease: RestrictedWorkerLease) -> None: ...

    async def assert_absent(self, lease: RestrictedWorkerLease) -> None: ...


async def run_ipython_host_orchestration(
    identity: IpythonHostExpectedIdentity,
    lease: RestrictedWorkerLease,
    adapter: _IpythonHostAdapter,
    *,
    signal: CancellationSignal | None = None,
) -> IpythonHostCompletion:
    """Mint P1 completion only from the closed, host-observed causal chain."""
    if (
        type(identity) is not IpythonHostExpectedIdentity
        or type(lease) is not RestrictedWorkerLease
        or not isinstance(adapter, _IpythonHostAdapter)
        or identity.workload_digest != lease.workload_digest
    ):
        _reject()

    supervisor: IpythonHostSupervisor | None = None
    broker_revoked = False
    try:
        supervisor = IpythonHostSupervisor(identity)
        _check_cancel(signal, supervisor)
        initial = await adapter.snapshot(lease)
        _record_initial(supervisor, initial)
        _check_cancel(signal, supervisor)

        observed = await adapter.brokered_cell(lease)
        _record_brokered_cell(supervisor, identity, lease, observed)
        _check_cancel(signal, supervisor)

        post = await adapter.snapshot(lease)
        _record_post(supervisor, post)
        _check_cancel(signal, supervisor)

        await adapter.revoke_broker(lease)
        broker_revoked = True
        supervisor.record_broker_revoked(supervisor._attest_broker_revocation())  # noqa: SLF001
        _check_cancel(signal, supervisor)
    except asyncio.CancelledError:
        if supervisor is not None:
            _cancel(supervisor)
        raise
    except Exception:
        if supervisor is not None:
            _cancel(supervisor)
        raise IpythonHostOrchestrationError("ipython host orchestration is unavailable") from None
    finally:
        cleanup_error = await _cleanup(adapter, lease, broker_revoked)

    if cleanup_error is not None:
        if isinstance(cleanup_error, asyncio.CancelledError):
            raise cleanup_error
        raise IpythonHostOrchestrationError("ipython host orchestration is unavailable") from None
    try:
        assert supervisor is not None
        supervisor.record_cleanup(supervisor._attest_cleanup_and_absence())  # noqa: SLF001
        _check_cancel(signal, supervisor)
        # This is intentionally after broker quiescence and verified absence.
        final = supervisor._attest_final_oracle(post.source)  # noqa: SLF001
        return supervisor.complete(final)
    except asyncio.CancelledError:
        _cancel(supervisor)
        raise
    except (IpythonHostSupervisorError, Exception):
        _cancel(supervisor)
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
        or usage.request_count != 1
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


async def _cleanup(
    adapter: _IpythonHostAdapter, lease: RestrictedWorkerLease, broker_revoked: bool
) -> BaseException | None:
    async def run() -> None:
        revocation_error: BaseException | None = None
        if not broker_revoked:
            try:
                await adapter.revoke_broker(lease)
            except BaseException as error:
                revocation_error = error
        await adapter.force_remove(lease)
        await adapter.assert_absent(lease)
        if revocation_error is not None:
            raise revocation_error

    task = asyncio.create_task(run())
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            cancellation = error
        except BaseException:
            break
    if task.cancelled():
        return asyncio.CancelledError()
    error = task.exception() if task.done() else None
    return error if error is not None else cancellation


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
