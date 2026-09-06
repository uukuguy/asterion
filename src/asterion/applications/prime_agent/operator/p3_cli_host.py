"""Private P3 CLI host projection."""

from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from .p3_development_host import PrimeP3DevelopmentTrace
from .p3_development_host import run_prime_p3_development
from .p3_development_docker import PrimeP3DevelopmentDockerTransport
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationCancelled,
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryContext

_CAPABILITY = "prime.recursive-workflow-development"
_TAG = "asterion-p3-development:20260906"
_DIGEST = "sha256:a89a88151d870acffe0f52e2aa0bfc5d4be8f02d54c8482f92caff8013bc358e"
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")


def project_p3_development_trace(trace: object) -> dict[str, str]:
    if type(trace) is not PrimeP3DevelopmentTrace:
        raise ValueError("prime P3 development host is unavailable")
    return {
        "scope": trace.scope,
        "promotion": trace.promotion,
        "trace_sha256": trace.trace_sha256,
    }


@dataclass(frozen=True, repr=False)
class _Resources:
    transport: object
    config: dict[str, object]
    node: str
    entrypoint: str
    source: str
    seccomp_fd: int


class PrimeP3SmallVerificationService:
    def __init__(self, resources: _Resources) -> None:
        self._resources, self._active, self._consumed = resources, True, False

    async def verify(self, request: PrimeSmallVerificationRequest, *, signal: CancellationSignal | None = None) -> PrimeSmallVerificationResult:
        if not self._active or self._consumed or type(request) is not PrimeSmallVerificationRequest or request.preset != "fixed-small-verification" or _RUN_ID.fullmatch(request.run_id) is None:
            raise ValueError("prime P3 development host is unavailable")
        self._consumed = True
        if signal is not None and signal.cancelled:
            raise PrimeSmallVerificationCancelled()
        task = asyncio.create_task(run_prime_p3_development(image_digest=_DIGEST, transport=self._resources.transport, operator_config=self._resources.config, node_bin=self._resources.node, entrypoint=self._resources.entrypoint, prime_source_root=self._resources.source, run_id=request.run_id))
        try:
            while not task.done():
                if signal is not None and signal.cancelled:
                    task.cancel()
                    raise PrimeSmallVerificationCancelled()
                try:
                    await asyncio.wait_for(asyncio.shield(task), 0.05)
                except TimeoutError:
                    continue
            trace = task.result()
            return PrimeSmallVerificationResult(request.run_id, trace.trace_sha256, "p3-development")
        except PrimeSmallVerificationCancelled:
            task.cancel()
            await _shielded_wait(task)
            raise
        except asyncio.CancelledError:
            task.cancel()
            await _shielded_wait(task)
            raise
        except BaseException:
            task.cancel()
            await _shielded_wait(task)
            raise ValueError("prime P3 development host is unavailable") from None

    def close(self) -> None:
        self._active = False
        close = getattr(self._resources.transport, "close", None)
        if callable(close):
            try:
                close()
            except BaseException:
                pass
        try:
            os.close(self._resources.seccomp_fd)
        except OSError:
            pass


async def _shielded_wait(task: asyncio.Task[object]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    try:
        task.result()
    except BaseException:
        pass


def create_prime_p3_cli_factory(*, repo_root: Path) -> HostServiceFactoryBinding:
    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        if type(context) is not HostServiceFactoryContext or (context.provider_id, context.application_id, context.application_version, context.capability_id, dict(context.options)) != ("prime-agent", "prime.recursive-workflow", "1.0.0", _CAPABILITY, {}):
            raise ValueError("prime P3 development host is unavailable")
        service = PrimeP3SmallVerificationService(_preflight(repo_root.resolve()))
        try:
            yield service
        finally:
            service.close()
    return HostServiceFactoryBinding(_CAPABILITY, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p3_cli_factory(repo_root=Path.cwd())


def _preflight(root: Path) -> _Resources:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("prime P3 development host is unavailable")
    from . import p2_cli_host as p2
    docker = p2._regular_executable(Path("/usr/bin/docker"))
    socket = Path("/var/run/docker.sock")
    if not stat.S_ISSOCK(os.lstat(socket).st_mode):
        raise ValueError("prime P3 development host is unavailable")
    node = p2._regular_executable(Path("/tmp/asterion-node22/bin/node"))
    entry = p2._regular_file(root / "packages/typescript/prime-gateway/dist/src/p3-development-main.js")
    source = p2._regular_directory(root / "3th-party/prime-agent")
    p2._regular_file(source / "packages/coding-agent/dist/core/sdk.js")
    descriptor = p2._sealed_seccomp(Path("/tmp/asterion-p1-development-seccomp.json"))
    try:
        _inspect_image(docker, socket)
        transport = PrimeP3DevelopmentDockerTransport(docker_executable=str(docker), socket_path=str(socket), seccomp_profile_fd=descriptor, platform=p2._host_platform())
        return _Resources(transport, dict(p2._operator_config(root / ".env")), str(node), str(entry), str(source), descriptor)
    except BaseException:
        os.close(descriptor)
        raise ValueError("prime P3 development host is unavailable") from None


def _inspect_image(docker: Path, socket: Path) -> None:
    result = subprocess.run((str(docker), "--host", "unix://" + str(socket), "image", "inspect", "--format", "{{.Id}}", _TAG), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={}, timeout=10, check=False)
    if result.returncode != 0 or result.stdout != (_DIGEST + "\n").encode():
        raise ValueError("prime P3 development host is unavailable")
