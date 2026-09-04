"""Concrete, private P1 issuer joining a live Docker worker to a live broker.

Nothing here is a public adapter: its only factory is deliberately private and
accepts the nominal operator implementations, then consumes only artifacts
sealed by those implementations.  In particular, a caller cannot supply a
snapshot, a model reply, a cleanup acknowledgement, or a broker receipt.
"""

from __future__ import annotations

from hashlib import sha256
from typing import NoReturn, cast

from asterion.applications.prime_agent.operator.docker_worker import (
    DockerRestrictedWorkerService,
    DockerWorkerModelResponse,
    _DockerWorkerHostArtifacts,
)
from asterion.applications.prime_agent.operator.ipython_host_orchestrator import (
    IpythonHostLiveRun,
    _IpythonBrokeredCell,
    _IpythonHostOperations,
    _LIVE_RUN_SEAL,
    _issue_ipython_host_live_run,
)
from asterion.applications.prime_agent.operator.ipython_host_supervisor import (
    IpythonHostExpectedIdentity,
)
from asterion.applications.prime_agent.operator.model_broker import (
    PrimeModelBrokerError,
    _HostModelCoordinator,
)
from asterion.runtime.host import CancellationSignal
from asterion.services.restricted_worker import RestrictedWorkerLease


__all__: tuple[()] = ()

# Application-owned instruction bytes.  They are never serialised into an
# assembly, receipt, exception, or worker-visible public surface.
_P1_MODEL_REQUEST = b"Use the ipython tool to make answer() return 42."


def _issue_docker_model_live_run(
    *,
    service: object,
    lease: object,
    identity: object,
    broker: object,
    signal: CancellationSignal | None = None,
) -> IpythonHostLiveRun:
    """Issue the sole P1 live run from live nominal Docker/broker artifacts."""
    if (
        type(service) is not DockerRestrictedWorkerService
        or type(lease) is not RestrictedWorkerLease
        or type(identity) is not IpythonHostExpectedIdentity
        or type(broker) is not _HostModelCoordinator
    ):
        _reject()
    worker = cast(DockerRestrictedWorkerService, service)
    typed_lease = cast(RestrictedWorkerLease, lease)
    typed_identity = cast(IpythonHostExpectedIdentity, identity)
    coordinator = cast(_HostModelCoordinator, broker)
    try:
        docker = worker._host_artifacts(typed_lease)  # noqa: SLF001 - concrete TCB join
        docker = worker._host_validate_artifacts(docker)  # noqa: SLF001
        _validate_docker_identity(docker, typed_identity, typed_lease)
        model = coordinator._host_artifacts(typed_lease)  # noqa: SLF001 - concrete TCB join
        model = coordinator._host_validate_artifacts(model)  # noqa: SLF001
    except BaseException:
        _reject()

    async def snapshot(observed_lease: RestrictedWorkerLease):
        _require_lease(observed_lease, typed_lease)
        return await worker._snapshot_solution(typed_lease)  # noqa: SLF001

    async def brokered_cell(observed_lease: RestrictedWorkerLease) -> _IpythonBrokeredCell:
        _require_lease(observed_lease, typed_lease)
        request = await worker._host_model_request(docker)  # noqa: SLF001
        if request.workload_digest != typed_lease.workload_digest:
            _reject()
        provider_bytes = await model.channel.request(_P1_MODEL_REQUEST)
        response = _response_from_provider(provider_bytes, typed_lease.workload_digest)
        # Receipt creation happens only after this exact launcher write succeeds.
        await worker._host_model_response(docker, response)  # noqa: SLF001
        usage = coordinator.usage()
        return _IpythonBrokeredCell(
            identity=typed_identity,
            response=response,
            sent_cell_digest="sha256:" + sha256(response.cell.encode("utf-8", "strict")).hexdigest(),
            model_receipt_digest="sha256:" + sha256(provider_bytes).hexdigest(),
            usage=usage,
        )

    async def revoke_broker(observed_lease: RestrictedWorkerLease):
        _require_lease(observed_lease, typed_lease)
        coordinator._host_validate_artifacts(model)  # noqa: SLF001
        receipt = await coordinator.revoke()
        if (
            receipt.run_id != typed_lease.run_id
            or receipt.worker_id != typed_lease.worker_id
            or receipt.challenge_digest != typed_lease.challenge_digest
        ):
            _reject()
        return receipt

    async def force_remove(observed_lease: RestrictedWorkerLease) -> None:
        _require_lease(observed_lease, typed_lease)
        await worker._host_force_remove(docker)  # noqa: SLF001

    async def assert_absent(observed_lease: RestrictedWorkerLease) -> None:
        _require_lease(observed_lease, typed_lease)
        await worker._host_assert_absent(docker)  # noqa: SLF001

    operations = _IpythonHostOperations(
        _seal=_LIVE_RUN_SEAL, snapshot=snapshot, brokered_cell=brokered_cell,
        revoke_broker=revoke_broker, force_remove=force_remove,
        assert_absent=assert_absent,
    )
    return _issue_ipython_host_live_run(
        identity=typed_identity, lease=typed_lease, operations=operations, signal=signal,
    )


def _validate_docker_identity(
    artifacts: _DockerWorkerHostArtifacts,
    identity: IpythonHostExpectedIdentity,
    lease: RestrictedWorkerLease,
) -> None:
    attestation = artifacts.attestation
    if (
        artifacts.lease is not lease
        or identity.image_digest != artifacts.image_digest
        or identity.workload_digest != lease.workload_digest
        or not artifacts.daemon_container_id
        or attestation.worker_id != lease.worker_id
        or attestation.role_id != lease.role_id
        or attestation.run_id != lease.run_id
        or attestation.challenge_digest != lease.challenge_digest
        or attestation.workload_digest != lease.workload_digest
        or attestation.image_digest != identity.image_digest
        or not all((attestation.network_isolated, attestation.root_read_only,
                    attestation.workspace_disposable, attestation.credentials_absent,
                    attestation.kernel_credential_absent, attestation.source_read_only,
                    attestation.resource_limited))
    ):
        _reject()


def _response_from_provider(provider_bytes: object, workload_digest: str) -> DockerWorkerModelResponse:
    if type(provider_bytes) is not bytes or not provider_bytes or len(provider_bytes) > 16 * 1024:
        _reject()
    try:
        cell = cast(bytes, provider_bytes).decode("utf-8", "strict")
    except UnicodeDecodeError:
        _reject()
    try:
        return DockerWorkerModelResponse(workload_digest, "ipython", cell)
    except BaseException:
        _reject()


def _require_lease(observed: object, expected: RestrictedWorkerLease) -> None:
    if observed is not expected:
        _reject()


def _reject() -> NoReturn:
    raise PrimeModelBrokerError("prime model broker is unavailable")
