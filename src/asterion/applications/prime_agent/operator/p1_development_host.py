"""Local operator-only P1 development execution wiring.

This module is intentionally outside the promoted production-host authority.
It connects selected local Docker resources to one fixed P1 preset and emits
only a private host trace for unpromoted development evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from .p1_development_snapshot import (
    P1DevelopmentSnapshotTransport as DockerCliEngineTransport,
)
from .docker_worker import DockerRestrictedWorkerService, DockerWorkerModelRequest, DockerWorkerModelResponse, DockerWorkerWorkspaceSnapshot
from .image_input_lock import ImagePlatformDescriptor
from .ipython_host_orchestrator import _IpythonBrokeredCell, _IpythonHostOperations, _LIVE_RUN_SEAL, _issue_ipython_host_live_run
from .ipython_host_supervisor import IpythonHostExpectedIdentity, IpythonHostTrace
from .ipython_workload import PRIME_IPYTHON_CODING_WORKLOAD_DIGEST
from .launcher_barrier import PrimeLauncherBarrier
from .model_broker import PrimeModelBrokerError, PrimeModelBrokerReceipt, PrimeModelBrokerTokenUsage, PrimeModelBrokerUsage, _HostModelCoordinator, _new_host_coordinator
from .p1_development_gateway import PrimeP1DevelopmentGateway
from .p1_development_sdk_provider import create_prime_p1_development_sdk_provider
from asterion.runtime.host import CancellationSignal
from asterion.services.bounded_model_session import BoundedModelSessionLease, BoundedModelSessionRequest
from asterion.services.restricted_worker import RestrictedWorkerLease, RestrictedWorkerRequest


_CHALLENGE_DIGEST = "sha256:4e7037acb549f07b07fb29efc40b5016f779515d4a21e2539e3eb22059f9b77f"
_ASSEMBLY_ID = "prime.ipython-coding@1.0.0"
_PACKAGE_ID = "prime-agent@1.0.0"
_IMPLEMENTATION_ID = "prime.ipython-coding@1.0.0"
_ORACLE_DIGEST = "sha256:85ee4060b19a5ee375e4c6258f45b1df722f53efd8310f56603b31639fa3c4eb"
_STARTER_DIGEST = "sha256:4f8e0bca0f70582bad96caa292823ac29577633bebd9f76257617dc92ab6832f"
_SOURCE_DIGEST = "sha256:486a083f857430c7d6a452ebf881d1b8c46063c128b51162ffdebef0c1f71c7a"
_MODEL_EVIDENCE_DOMAIN = "asterion.prime.p1-a-development.host-model-evidence/v1"
_EXPECTED_PROVIDER_REQUEST_COUNT = 2


class PrimeP1DevelopmentHostError(ValueError):
    """Public-safe local development execution failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 development host is unavailable")


@dataclass(frozen=True, repr=False)
class PrimeP1DevelopmentEvidence:
    """Unpromoted local-development trace metadata without a P1 PASS claim."""

    trace: IpythonHostTrace
    scope: Literal["p1-a-development"] = "p1-a-development"
    promotion: Literal["unpromoted"] = "unpromoted"

    def __repr__(self) -> str:
        return "PrimeP1DevelopmentEvidence(redacted)"


async def run_prime_p1_development(
    *, docker_executable: str, socket_path: str, seccomp_profile_fd: int,
    platform: ImagePlatformDescriptor, image_digest: str,
    operator_config: Mapping[str, object], node_bin: str, entrypoint: str,
    prime_source_root: str, signal: CancellationSignal | None = None,
) -> PrimeP1DevelopmentEvidence:
    """Run the root development preset after the operator confirms daemon locality.

    The caller must already have verified that the daemon and this host share
    the same Linux guest; a socket path is not a locality check.
    """
    transport: DockerCliEngineTransport | None = None
    try:
        if not isinstance(operator_config, Mapping):
            raise ValueError
        transport = DockerCliEngineTransport(
            docker_executable=docker_executable, socket_path=socket_path,
            seccomp_profile_fd=seccomp_profile_fd, platform=platform,
            operator_confirmed_same_guest=True,
        )
        service = DockerRestrictedWorkerService(image_digest=image_digest, transport=transport)
        provider = create_prime_p1_development_sdk_provider(operator_config)
        suffix = uuid4().hex
        run_id = "prime-p1-development-" + suffix
        session_id = "prime-p1-development-session-" + suffix
        session = _model_session(run_id)
        request = RestrictedWorkerRequest(
            "prime.ipython-coding", image_digest, run_id, _CHALLENGE_DIGEST,
            PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, 300, 65536,
        )
        async with service.open(request, signal=signal) as lease:
            attestation = await service.attest(lease)
            barrier = PrimeLauncherBarrier(
                role_id=lease.role_id, run_id=lease.run_id,
                challenge_digest=lease.challenge_digest, workload_digest=lease.workload_digest,
            )
            barrier.admit(lease, attestation)
            worker_artifacts = service._host_artifacts(lease)
            retained_request = await service._host_model_request(worker_artifacts)
            if type(retained_request) is not DockerWorkerModelRequest or retained_request.workload_digest != lease.workload_digest:
                raise ValueError
            broker = _new_host_coordinator(
                lease=BoundedModelSessionLease(session_id, lease.run_id), session=session,
                worker=lease, barrier=barrier, provider=provider, session_id=session_id,
                worker_id=lease.worker_id, run_id=lease.run_id,
                challenge_digest=lease.challenge_digest, cleanup_grace_seconds=5.0,
                terminal_usage=provider.terminal_usage,
            )
            identity = _expected_identity(image_digest)
            live_run = _issue_ipython_host_live_run(
                identity=identity, lease=lease,
                operations=_development_operations(
                    service=service, lease=lease, worker_artifacts=worker_artifacts,
                    broker=broker, retained_request=retained_request, identity=identity,
                    session_id=session_id, terminal_usage=provider.terminal_usage,
                    node_bin=node_bin, entrypoint=entrypoint,
                    prime_source_root=prime_source_root,
                ),
                signal=signal,
            )
            return PrimeP1DevelopmentEvidence(await live_run.trace())
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise PrimeP1DevelopmentHostError() from None
    finally:
        if transport is not None:
            transport.close()


def _expected_identity(image_digest: str) -> IpythonHostExpectedIdentity:
    return IpythonHostExpectedIdentity(
        _ASSEMBLY_ID, _PACKAGE_ID, _IMPLEMENTATION_ID, image_digest,
        PRIME_IPYTHON_CODING_WORKLOAD_DIGEST, _ORACLE_DIGEST, _STARTER_DIGEST,
        _SOURCE_DIGEST, expected_provider_request_count=_EXPECTED_PROVIDER_REQUEST_COUNT,
    )


def _model_session(run_id: str) -> BoundedModelSessionRequest:
    return BoundedModelSessionRequest(
        run_id=run_id, max_requests=_EXPECTED_PROVIDER_REQUEST_COUNT, max_input_tokens=8192,
        max_output_tokens=1024, max_input_bytes=128 * 1024, max_output_bytes=64 * 1024,
        max_cost_microunits=10_000, deadline_seconds=60,
    )


def _development_operations(
    *, service: DockerRestrictedWorkerService, lease: RestrictedWorkerLease,
    worker_artifacts: object, broker: _HostModelCoordinator,
    retained_request: DockerWorkerModelRequest, identity: IpythonHostExpectedIdentity,
    session_id: str, terminal_usage: object, node_bin: str, entrypoint: str,
    prime_source_root: str,
) -> _IpythonHostOperations:
    consumed = False

    def require_lease(candidate: RestrictedWorkerLease) -> None:
        if candidate is not lease:
            raise PrimeModelBrokerError("prime model broker is unavailable")

    async def snapshot(candidate: RestrictedWorkerLease) -> DockerWorkerWorkspaceSnapshot:
        require_lease(candidate)
        return await service._snapshot_solution(lease)

    async def brokered_cell(candidate: RestrictedWorkerLease) -> _IpythonBrokeredCell:
        nonlocal consumed
        require_lease(candidate)
        if consumed:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        consumed = True
        artifacts = broker._host_artifacts(lease)
        channel = broker._host_validate_artifacts(artifacts).channel
        code_digest: str | None = None
        response: DockerWorkerModelResponse | None = None

        async def model_request(payload: object) -> dict[str, object]:
            body = _canonical_json_object_bytes(payload)
            result = await channel.request(body)
            return _strict_json_object(result)

        async def tool_request(payload: object) -> dict[str, object]:
            nonlocal code_digest, response
            if code_digest is not None or type(payload) is not dict or set(payload) != {"tool_call_id", "code"}:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            tool_call_id, code = payload["tool_call_id"], payload["code"]
            if type(tool_call_id) is not str or not tool_call_id or type(code) is not str or not code:
                raise PrimeModelBrokerError("prime model broker is unavailable")
            response = DockerWorkerModelResponse(lease.workload_digest, "ipython", code)
            await service._host_model_response(worker_artifacts, response)
            code_digest = "sha256:" + sha256(code.encode("utf-8", "strict")).hexdigest()
            return {
                "content": [{"type": "text", "text": "IPython cell completed"}],
                "details": {},
                "isError": False,
            }

        gateway = PrimeP1DevelopmentGateway(
            node_bin=node_bin, entrypoint=entrypoint, deadline_seconds=60,
            model_hook=model_request, tool_hook=tool_request,
        )
        opened = False
        try:
            await gateway.open(
                run_id=lease.run_id, session_id=session_id, generation=1,
                prime_source_root=prime_source_root, workspace=str(Path.cwd()),
            )
            opened = True
            result = await gateway.prompt(_P1_DEVELOPMENT_PROMPT)
            if type(result) is not dict or result.get("lifecycle") != "completed" or code_digest is None:
                raise PrimeModelBrokerError("prime model broker is unavailable")
        except BaseException:
            if opened:
                try:
                    await gateway.cancel()
                except BaseException:
                    pass
            if opened:
                try:
                    await gateway.close()
                except BaseException:
                    pass
            raise
        try:
            await gateway.close()
        except BaseException:
            raise PrimeModelBrokerError("prime model broker is unavailable") from None
        if code_digest is None:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        if response is None:
            raise PrimeModelBrokerError("prime model broker is unavailable")
        usage = broker.usage()
        return _IpythonBrokeredCell(
            identity=identity, response=response,
            sent_cell_digest=code_digest,
            # This is host-observed development evidence, never a production receipt.
            model_receipt_digest=_host_observed_model_evidence_digest(
                usage=usage, terminal_usage=terminal_usage, session_id=session_id,
                workload_digest=lease.workload_digest, cell_digest=code_digest,
            ),
            usage=usage,
        )

    async def revoke_broker(candidate: RestrictedWorkerLease) -> PrimeModelBrokerReceipt:
        require_lease(candidate)
        return await broker.revoke()

    async def force_remove(candidate: RestrictedWorkerLease) -> None:
        require_lease(candidate)
        await service._host_force_remove(worker_artifacts)

    async def assert_absent(candidate: RestrictedWorkerLease) -> None:
        require_lease(candidate)
        await service._host_assert_absent(worker_artifacts)

    return _IpythonHostOperations(
        _seal=_LIVE_RUN_SEAL, snapshot=snapshot, brokered_cell=brokered_cell,
        revoke_broker=revoke_broker, force_remove=force_remove, assert_absent=assert_absent,
    )


_P1_DEVELOPMENT_PROMPT = "Run the fixed IPython verification cell."


def _canonical_json_object_bytes(value: object) -> bytes:
    if type(value) is not dict:
        raise PrimeModelBrokerError("prime model broker is unavailable")
    try:
        return _canonical_json(value).encode("utf-8")
    except (TypeError, ValueError):
        raise PrimeModelBrokerError("prime model broker is unavailable") from None


def _strict_json_object(value: object) -> dict[str, object]:
    if type(value) is not bytes:
        raise PrimeModelBrokerError("prime model broker is unavailable")
    try:
        decoded = json.loads(value.decode("utf-8", "strict"))
        if type(decoded) is not dict or _canonical_json(decoded).encode("utf-8") != value:
            raise ValueError
        return decoded
    except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise PrimeModelBrokerError("prime model broker is unavailable") from None


def _canonical_json(value: object) -> str:
    if value is None or type(value) in (str, bool, int):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is list:
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if type(value) is dict and all(type(key) is str for key in value):
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _canonical_json(value[key])
            for key in sorted(value)
        ) + "}"
    raise ValueError


def _host_observed_model_evidence_digest(
    *, usage: PrimeModelBrokerUsage, terminal_usage: object, session_id: str,
    workload_digest: str, cell_digest: str,
) -> str:
    """Hash bounded host observations; this is not a production model receipt."""
    if type(usage) is not PrimeModelBrokerUsage or not callable(terminal_usage):
        raise PrimeModelBrokerError("prime model broker is unavailable")
    terminal = terminal_usage()
    if type(terminal) is not PrimeModelBrokerTokenUsage:
        raise PrimeModelBrokerError("prime model broker is unavailable")
    value = {
        "domain": _MODEL_EVIDENCE_DOMAIN,
        "session_id": session_id,
        "run_id": usage.run_id,
        "worker_id": usage.worker_id,
        "challenge_digest": usage.challenge_digest,
        "workload_digest": workload_digest,
        "cell_digest": cell_digest,
        "broker_usage": {
            "request_count": usage.request_count,
            "input_bytes": usage.input_bytes,
            "output_bytes": usage.output_bytes,
        },
        "provider_terminal_usage": {
            "input_tokens": terminal.input_tokens,
            "output_tokens": terminal.output_tokens,
            "cost_microunits": terminal.cost_microunits,
        },
    }
    return "sha256:" + sha256(
        json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = (
    "PrimeP1DevelopmentEvidence",
    "PrimeP1DevelopmentHostError",
    "run_prime_p1_development",
)
