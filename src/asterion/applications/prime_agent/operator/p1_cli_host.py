"""One local-root development CLI host for the P1-B small verification."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from dotenv import dotenv_values

from asterion.applications.prime_agent.operator.image_input_lock import ImagePlatformDescriptor
from asterion.applications.prime_agent.operator.p1b_development_docker import P1BDevelopmentSnapshotTransport
from asterion.applications.prime_agent.operator.p1b_development_host import run_prime_p1b_development
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryContext


_CAPABILITY_ID = "prime.ipython-production"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.ipython-coding"
_APPLICATION_VERSION = "1.0.0"
_SCOPE = "p1-b-development"
_PROMOTION = "unpromoted"
_DEADLINE_SECONDS = 300
_IMAGE_TAG = "asterion-p1b-development:20260906"
_DOCKER = "/usr/bin/docker"
_SOCKET = "/var/run/docker.sock"
_SECCOMP = "/tmp/asterion-p1-development-seccomp.json"
_NODE = "/tmp/asterion-node22/bin/node"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")


class PrimeP1CliHostError(ValueError):
    """Public-safe local CLI host failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 CLI host is unavailable")


@dataclass(frozen=True, repr=False)
class _P1CliResources:
    image_digest: str
    transport: object
    operator_config: Mapping[str, object]
    node_bin: str
    entrypoint: str
    prime_source_root: str
    seccomp_fd: int | None = None


class PrimeSmallVerificationService:
    """One active-context, one-shot, fixed-request verification service."""

    __slots__ = ("_active", "_consumed", "_resources")

    def __init__(self, resources: _P1CliResources) -> None:
        self._active = True
        self._consumed = False
        self._resources = resources

    def __repr__(self) -> str:
        return "PrimeSmallVerificationService(redacted)"

    async def verify(
        self,
        request: PrimeSmallVerificationRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> PrimeSmallVerificationResult:
        if (
            not self._active
            or self._consumed
            or type(request) is not PrimeSmallVerificationRequest
            or request.preset != "fixed-small-verification"
            or _RUN_ID.fullmatch(request.run_id) is None
            or (signal is not None and not hasattr(signal, "cancelled"))
        ):
            raise PrimeP1CliHostError()
        self._consumed = True
        if _cancelled(signal):
            raise asyncio.CancelledError
        task = asyncio.create_task(
            run_prime_p1b_development(
                image_digest=self._resources.image_digest,
                transport=self._resources.transport,  # type: ignore[arg-type]
                operator_config=self._resources.operator_config,
                node_bin=self._resources.node_bin,
                entrypoint=self._resources.entrypoint,
                prime_source_root=self._resources.prime_source_root,
                run_id=request.run_id,
            )
        )
        try:
            async with asyncio.timeout(_DEADLINE_SECONDS):
                trace = await _await_with_cancellation(task, signal)
            return PrimeSmallVerificationResult(
                run_id=request.run_id, trace_sha256=trace.trace_sha256
            )
        except asyncio.CancelledError:
            task.cancel()
            await _shielded_wait(task)
            raise
        except BaseException:
            task.cancel()
            await _shielded_wait(task)
            raise PrimeP1CliHostError() from None

    def _close(self) -> None:
        self._active = False
        descriptor = self._resources.seccomp_fd
        if type(descriptor) is int and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def create_prime_p1_cli_factory(*, repo_root: Path) -> HostServiceFactoryBinding:
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        try:
            resources = _preflight(root)
            service = PrimeSmallVerificationService(resources)
        except BaseException:
            raise PrimeP1CliHostError() from None
        try:
            yield service
        finally:
            service._close()

    return HostServiceFactoryBinding(_CAPABILITY_ID, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p1_cli_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        raise PrimeP1CliHostError()


def _preflight(repo_root: Path) -> _P1CliResources:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PrimeP1CliHostError()
    docker = _regular_executable(Path(_DOCKER))
    socket = Path(_SOCKET)
    if not stat.S_ISSOCK(os.lstat(socket).st_mode):
        raise PrimeP1CliHostError()
    node = _regular_executable(Path(_NODE))
    entrypoint = _regular_file(repo_root / "packages/typescript/prime-gateway/dist/src/p1b-development-main.js")
    source = _regular_directory(repo_root / "packages/typescript/prime-gateway")
    seccomp_fd = _sealed_seccomp(Path(_SECCOMP))
    try:
        image_digest = _inspect_image(docker, socket)
        transport = P1BDevelopmentSnapshotTransport(
            docker_executable=str(docker), socket_path=str(socket), seccomp_profile_fd=seccomp_fd,
            platform=_host_platform(), operator_confirmed_same_guest=True,
        )
        return _P1CliResources(
            image_digest=image_digest, transport=transport,
            operator_config=_operator_config(repo_root / ".env"), node_bin=str(node),
            entrypoint=str(entrypoint), prime_source_root=str(source), seccomp_fd=seccomp_fd,
        )
    except BaseException:
        os.close(seccomp_fd)
        raise PrimeP1CliHostError() from None


def _operator_config(path: Path) -> Mapping[str, object]:
    values = dotenv_values(path)
    if not values or any(type(key) is not str or type(value) is not str for key, value in values.items()):
        raise PrimeP1CliHostError()
    return dict(values)


def _inspect_image(docker: Path, socket: Path) -> str:
    try:
        result = subprocess.run(
            (str(docker), "--host", "unix://" + str(socket), "image", "inspect", "--format", "{{.Id}}", _IMAGE_TAG),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={}, timeout=10, check=False,
        )
    except BaseException:
        raise PrimeP1CliHostError() from None
    try:
        value = result.stdout.decode("ascii", "strict")
    except UnicodeDecodeError:
        raise PrimeP1CliHostError() from None
    if result.returncode != 0 or _DIGEST.fullmatch(value.rstrip("\n")) is None or value != value.rstrip("\n") + "\n":
        raise PrimeP1CliHostError()
    return value[:-1]


def _regular_executable(path: Path) -> Path:
    value = _regular_file(path)
    if value.stat().st_mode & 0o111 == 0:
        raise PrimeP1CliHostError()
    return value


def _regular_file(path: Path) -> Path:
    try:
        details = os.lstat(path)
        if not stat.S_ISREG(details.st_mode) or details.st_size <= 0:
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP1CliHostError() from None
    return path


def _regular_directory(path: Path) -> Path:
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP1CliHostError() from None
    return path


def _sealed_seccomp(path: Path) -> int:
    source = _regular_file(path).read_bytes()
    if not source or len(source) > 64 * 1024 or not hasattr(os, "memfd_create"):
        raise PrimeP1CliHostError()
    descriptor = os.memfd_create("asterion-p1-development-seccomp", getattr(os, "MFD_CLOEXEC", 0))
    try:
        if os.write(descriptor, source) != len(source):
            raise ValueError
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise PrimeP1CliHostError() from None


def _host_platform() -> ImagePlatformDescriptor:
    machine = os.uname().machine
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
    if architecture is None:
        raise PrimeP1CliHostError()
    return ImagePlatformDescriptor("linux", architecture, None)


def _cancelled(signal: CancellationSignal | None) -> bool:
    if signal is None:
        return False
    try:
        return signal.cancelled is True
    except BaseException:
        raise PrimeP1CliHostError() from None


async def _await_with_cancellation(task: asyncio.Task[object], signal: CancellationSignal | None) -> object:
    while not task.done():
        if _cancelled(signal):
            raise asyncio.CancelledError
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        except TimeoutError:
            continue
    return task.result()


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


__all__ = (
    "PrimeP1CliHostError", "PrimeSmallVerificationService",
    "create_host_service_factory", "create_prime_p1_cli_factory",
)
