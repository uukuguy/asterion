"""Installed local-root host for the fixed P2 development verification."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from dotenv import dotenv_values

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.p2_development_docker import (
    PrimeP2DevelopmentDockerTransport,
)
from asterion.applications.prime_agent.operator.p2_development_host import (
    run_prime_p2_development,
)
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import (
    PrimeSmallVerificationCancelled,
    PrimeSmallVerificationRequest,
    PrimeSmallVerificationResult,
)
from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
)


_CAPABILITY_ID = "prime.programmatic-long-context-development"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.programmatic-long-context"
_APPLICATION_VERSION = "1.0.0"
_DEADLINE_SECONDS = 300
_IMAGE_TAG = "asterion-p2-development:20260906"
_CONFIRMED_IMAGE_DIGEST = (
    "sha256:7d97b51a21bfffe6caa574063294f72205c60b05d8650fab8c70fdf661921c33"
)
_DOCKER = "/usr/bin/docker"
_SOCKET = "/var/run/docker.sock"
_SECCOMP = "/tmp/asterion-p1-development-seccomp.json"
_NODE = "/tmp/asterion-node22/bin/node"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")


class PrimeP2CliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P2 CLI host is unavailable")


@dataclass(frozen=True, repr=False)
class _P2CliResources:
    image_digest: str
    transport: object
    operator_config: Mapping[str, object]
    node_bin: str
    entrypoint: str
    prime_source_root: str
    seccomp_fd: int | None = None


class PrimeP2SmallVerificationService:
    __slots__ = ("_active", "_consumed", "_resources")

    def __init__(self, resources: _P2CliResources) -> None:
        self._active = True
        self._consumed = False
        self._resources = resources

    def __repr__(self) -> str:
        return "PrimeP2SmallVerificationService(redacted)"

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
        ):
            raise PrimeP2CliHostError()
        self._consumed = True
        if _cancelled(signal):
            raise PrimeSmallVerificationCancelled()
        task = asyncio.create_task(
            run_prime_p2_development(
                image_digest=self._resources.image_digest,
                transport=self._resources.transport,  # type: ignore[arg-type]
                operator_config=self._resources.operator_config,
                node_bin=self._resources.node_bin,
                entrypoint=self._resources.entrypoint,
                prime_source_root=self._resources.prime_source_root,
                run_id=request.run_id,
                signal=signal,
            )
        )
        try:
            async with asyncio.timeout(_DEADLINE_SECONDS):
                trace = await _await_with_cancellation(task, signal)
            return PrimeSmallVerificationResult(
                run_id=request.run_id,
                trace_sha256=trace.trace_sha256,
                scope="p2-development",
            )
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
        raise PrimeP2CliHostError()

    def _close(self) -> None:
        if not self._active:
            return
        self._active = False
        close = getattr(self._resources.transport, "close", None)
        if callable(close):
            try:
                close()
            except BaseException:
                pass
        descriptor = self._resources.seccomp_fd
        if type(descriptor) is int and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def create_prime_p2_cli_factory(*, repo_root: Path) -> HostServiceFactoryBinding:
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        service: PrimeP2SmallVerificationService | None = None
        try:
            service = PrimeP2SmallVerificationService(_preflight(root))
        except BaseException:
            pass
        if service is None:
            raise PrimeP2CliHostError()
        try:
            yield service
        finally:
            service._close()

    return HostServiceFactoryBinding(_CAPABILITY_ID, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p2_cli_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        raise PrimeP2CliHostError()


def _preflight(repo_root: Path) -> _P2CliResources:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PrimeP2CliHostError()
    docker = _regular_executable(Path(_DOCKER))
    socket = Path(_SOCKET)
    try:
        if not stat.S_ISSOCK(os.lstat(socket).st_mode):
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP2CliHostError() from None
    node = _regular_executable(Path(_NODE))
    entrypoint = _regular_file(
        repo_root
        / "packages/typescript/prime-gateway/dist/src/p2-development-main.js"
    )
    source = _regular_directory(repo_root / "3th-party/prime-agent")
    _regular_file(source / "packages/coding-agent/dist/core/sdk.js")
    _regular_file(source / "node_modules/typebox/build/index.mjs")
    seccomp_fd = _sealed_seccomp(Path(_SECCOMP))
    transport: object | None = None
    try:
        image_digest = _inspect_image(docker, socket)
        transport = PrimeP2DevelopmentDockerTransport(
            docker_executable=str(docker),
            socket_path=str(socket),
            seccomp_profile_fd=seccomp_fd,
            platform=_host_platform(),
        )
        return _P2CliResources(
            image_digest=image_digest,
            transport=transport,
            operator_config=_operator_config(repo_root / ".env"),
            node_bin=str(node),
            entrypoint=str(entrypoint),
            prime_source_root=str(source),
            seccomp_fd=seccomp_fd,
        )
    except BaseException:
        if transport is not None:
            close = getattr(transport, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException:
                    pass
        try:
            os.close(seccomp_fd)
        except OSError:
            pass
        raise PrimeP2CliHostError() from None


def _operator_config(path: Path) -> Mapping[str, object]:
    values = dotenv_values(path)
    if not values or any(
        type(key) is not str or type(value) is not str
        for key, value in values.items()
    ):
        raise PrimeP2CliHostError()
    return dict(values)


def _inspect_image(docker: Path, socket: Path) -> str:
    try:
        result = subprocess.run(
            (
                str(docker),
                "--host",
                "unix://" + str(socket),
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                _IMAGE_TAG,
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={},
            timeout=10,
            check=False,
        )
    except BaseException:
        raise PrimeP2CliHostError() from None
    try:
        value = result.stdout.decode("ascii", "strict")
    except UnicodeDecodeError:
        raise PrimeP2CliHostError() from None
    if (
        result.returncode != 0
        or value != _CONFIRMED_IMAGE_DIGEST + "\n"
        or _DIGEST.fullmatch(_CONFIRMED_IMAGE_DIGEST) is None
    ):
        raise PrimeP2CliHostError()
    return _CONFIRMED_IMAGE_DIGEST


def _regular_executable(path: Path) -> Path:
    value = _regular_file(path)
    if value.stat().st_mode & 0o111 == 0:
        raise PrimeP2CliHostError()
    return value


def _regular_file(path: Path) -> Path:
    try:
        details = os.lstat(path)
        if not stat.S_ISREG(details.st_mode) or details.st_size <= 0:
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP2CliHostError() from None
    return path


def _regular_directory(path: Path) -> Path:
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP2CliHostError() from None
    return path


def _sealed_seccomp(path: Path) -> int:
    source = _regular_file(path).read_bytes()
    constants = tuple(
        getattr(fcntl, name, None)
        for name in (
            "F_ADD_SEALS",
            "F_GET_SEALS",
            "F_SEAL_WRITE",
            "F_SEAL_GROW",
            "F_SEAL_SHRINK",
            "F_SEAL_SEAL",
            "F_GETFD",
            "FD_CLOEXEC",
        )
    )
    if (
        not source
        or len(source) > 64 * 1024
        or not hasattr(os, "memfd_create")
        or any(type(value) is not int for value in constants)
    ):
        raise PrimeP2CliHostError()
    add, get, write, grow, shrink, seal, get_fd, cloexec = constants
    descriptor = -1
    try:
        descriptor = os.memfd_create(  # type: ignore[attr-defined]
            "asterion-p2-development-seccomp",
            os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,  # type: ignore[attr-defined]
        )
        offset = 0
        while offset < len(source):
            offset += os.write(descriptor, source[offset:])
        os.lseek(descriptor, 0, os.SEEK_SET)
        seals = write | grow | shrink | seal
        if not fcntl.fcntl(descriptor, get_fd) & cloexec:
            raise ValueError
        fcntl.fcntl(descriptor, add, seals)
        if fcntl.fcntl(descriptor, get) != seals:
            raise ValueError
        result = descriptor
        descriptor = -1
        return result
    except BaseException:
        raise PrimeP2CliHostError() from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _host_platform() -> ImagePlatformDescriptor:
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
    if architecture is None:
        raise PrimeP2CliHostError()
    return ImagePlatformDescriptor("linux", architecture, None)


def _cancelled(signal: CancellationSignal | None) -> bool:
    if signal is None:
        return False
    try:
        return signal.cancelled is True
    except BaseException:
        raise PrimeP2CliHostError() from None


async def _await_with_cancellation(
    task: asyncio.Task[object], signal: CancellationSignal | None
) -> object:
    while not task.done():
        if _cancelled(signal):
            raise PrimeSmallVerificationCancelled()
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
    "PrimeP2CliHostError",
    "PrimeP2SmallVerificationService",
    "create_host_service_factory",
    "create_prime_p2_cli_factory",
)
