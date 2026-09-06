"""Installed local-root host for the fixed P6 continual-improvement verification."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory

from dotenv import dotenv_values

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.p6_development_docker import (
    P6DevelopmentDockerTransport,
    P6DevelopmentDockerWorkerService,
)
from asterion.applications.prime_agent.operator.p6_development_sdk_provider import (
    create_prime_p6_development_sdk_provider,
)
from asterion.applications.prime_agent.operator.p6_development_gateway import (
    PrimeP6DevelopmentGateway,
)
from asterion.applications.prime_agent.operator.p6_development_host import (
    run_p6_development_lifecycle,
)
from asterion.applications.prime_agent.operator.p6_development_receipt import (
    P6DevelopmentReceipt,
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


_CAPABILITY_ID = "prime.continual-improvement-development"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.continual-improvement"
_APPLICATION_VERSION = "1.0.0"
_DEADLINE_SECONDS = 300
P6_CLI_DEADLINE_SECONDS = _DEADLINE_SECONDS
_IMAGE_TAG = "asterion-p3-development:20260906"
_CONFIRMED_IMAGE_DIGEST = (
    "sha256:68ffbf922d6dae7ca7c79294c7dceb680bceda599d3cfd0bc8bb0323a9d5a243"
)
_DOCKER = "/usr/bin/docker"
_SOCKET = "/var/run/docker.sock"
_SECCOMP = "/tmp/asterion-p1-development-seccomp.json"
_NODE = "/tmp/asterion-node22/bin/node"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")


class PrimeP6CliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P6 CLI host is unavailable")


@dataclass(frozen=True, repr=False)
class _P6CliResources:
    image_digest: str
    transport: object
    operator_config: Mapping[str, object]
    node_bin: str
    entrypoint: str
    prime_source_root: str
    seccomp_fd: int | None = None


_LifecycleRunner = Callable[[_P6CliResources, str], Awaitable[object]]


class PrimeP6SmallVerificationService:
    __slots__ = ("_active", "_consumed", "_lifecycle_runner", "_resources")

    def __init__(
        self,
        resources: _P6CliResources,
        *,
        lifecycle_runner: _LifecycleRunner | None = None,
    ) -> None:
        self._active = True
        self._consumed = False
        self._lifecycle_runner = (
            _run_p6_development_lifecycle
            if lifecycle_runner is None
            else lifecycle_runner
        )
        self._resources = resources

    def __repr__(self) -> str:
        return "PrimeP6SmallVerificationService(redacted)"

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
            raise PrimeP6CliHostError()
        self._consumed = True
        if _cancelled(signal):
            raise PrimeSmallVerificationCancelled()
        task = asyncio.create_task(
            self._lifecycle_runner(self._resources, request.run_id)
        )
        try:
            async with asyncio.timeout(_DEADLINE_SECONDS):
                trace = await _await_with_cancellation(task, signal)
            digest = getattr(trace, "trace_sha256", None)
            if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
                raise ValueError
            return PrimeSmallVerificationResult(
                run_id=request.run_id,
                trace_sha256=digest,
                scope="p6-development",
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
            raise PrimeP6CliHostError() from None

    def _close(self) -> None:
        if not self._active:
            return
        self._active = False
        _close_transport(self._resources.transport)
        descriptor = self._resources.seccomp_fd
        if type(descriptor) is int and descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def create_prime_p6_cli_factory(*, repo_root: Path) -> HostServiceFactoryBinding:
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        try:
            service = PrimeP6SmallVerificationService(_preflight(root))
        except BaseException:
            raise PrimeP6CliHostError() from None
        try:
            yield service
        finally:
            service._close()

    return HostServiceFactoryBinding(_CAPABILITY_ID, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p6_cli_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        raise PrimeP6CliHostError()


def _preflight(repo_root: Path) -> _P6CliResources:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PrimeP6CliHostError()
    docker = _regular_executable(Path(_DOCKER))
    socket = Path(_SOCKET)
    try:
        if not stat.S_ISSOCK(os.lstat(socket).st_mode):
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP6CliHostError() from None
    node = _regular_executable(Path(_NODE))
    entrypoint = _regular_file(
        repo_root / "packages/typescript/prime-gateway/dist/src/p6-development-main.js"
    )
    source = _regular_directory(repo_root / "3th-party/prime-agent")
    _regular_file(source / "packages/coding-agent/dist/core/sdk.js")
    _regular_file(source / "node_modules/typebox/build/index.mjs")
    seccomp_fd = _sealed_seccomp(Path(_SECCOMP))
    transport: object | None = None
    try:
        transport = P6DevelopmentDockerTransport(
            docker_executable=str(docker),
            socket_path=str(socket),
            seccomp_profile_fd=seccomp_fd,
            platform=_host_platform(),
        )
        return _P6CliResources(
            image_digest=_inspect_image(docker, socket),
            transport=transport,
            operator_config=_operator_config(repo_root / ".env"),
            node_bin=str(node),
            entrypoint=str(entrypoint),
            prime_source_root=str(source),
            seccomp_fd=seccomp_fd,
        )
    except BaseException:
        if transport is not None:
            _close_transport(transport)
        try:
            os.close(seccomp_fd)
        except OSError:
            pass
        raise PrimeP6CliHostError() from None


async def _run_p6_development_lifecycle(
    resources: _P6CliResources, run_id: str
) -> P6DevelopmentReceipt:
    session_id = "prime-p6-session-" + sha256(run_id.encode("ascii")).hexdigest()
    try:
        provider = create_prime_p6_development_sdk_provider(resources.operator_config)
        gateway = PrimeP6DevelopmentGateway(
            node_bin=resources.node_bin,
            entrypoint=resources.entrypoint,
            deadline_seconds=_DEADLINE_SECONDS,
        )
        with TemporaryDirectory(prefix="asterion-prime-p6-") as workspace:
            _prepare_workspace(Path(workspace))
            worker = P6DevelopmentDockerWorkerService(
                image_digest=resources.image_digest,
                transport=resources.transport,
                run_id=run_id,
                session_id=session_id,
                goal_id="prime.continual-improvement/v1",
                workspace=workspace,
            )
            return await run_p6_development_lifecycle(
                gateway=gateway,
                provider=provider,
                worker=worker,
                run_id=run_id,
                session_id=session_id,
                prime_source_root=resources.prime_source_root,
                workspace=workspace,
            )
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise PrimeP6CliHostError() from None


def _prepare_workspace(workspace: Path) -> None:
    try:
        os.chown(workspace, 65534, 65534)
        os.chmod(workspace, 0o700)
        source = workspace / "baseline.py"
        source.write_bytes(
            b"def clamp(value, lower, upper):\n    return min(upper, value)\n"
        )
        os.chown(source, 65534, 65534)
        os.chmod(source, 0o600)
    except OSError:
        raise PrimeP6CliHostError() from None


def _operator_config(path: Path) -> Mapping[str, object]:
    values = dotenv_values(path)
    if not values or any(
        type(key) is not str or type(value) is not str for key, value in values.items()
    ):
        raise PrimeP6CliHostError()
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
        value = result.stdout.decode("ascii", "strict")
    except BaseException:
        raise PrimeP6CliHostError() from None
    if result.returncode != 0 or value != _CONFIRMED_IMAGE_DIGEST + "\n":
        raise PrimeP6CliHostError()
    return _CONFIRMED_IMAGE_DIGEST


def _close_transport(transport: object) -> None:
    close = getattr(transport, "close", None)
    if callable(close):
        try:
            close()
        except BaseException:
            pass


def _regular_executable(path: Path) -> Path:
    value = _regular_file(path)
    if value.stat().st_mode & 0o111 == 0:
        raise PrimeP6CliHostError()
    return value


def _regular_file(path: Path) -> Path:
    try:
        details = os.lstat(path)
        if not stat.S_ISREG(details.st_mode) or details.st_size <= 0:
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP6CliHostError() from None
    return path


def _regular_directory(path: Path) -> Path:
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise ValueError
    except (OSError, ValueError):
        raise PrimeP6CliHostError() from None
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
        raise PrimeP6CliHostError()
    add, get, write, grow, shrink, seal, get_fd, cloexec = constants
    descriptor = -1
    try:
        descriptor = os.memfd_create(
            "asterion-p6-development-seccomp", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
        )  # type: ignore[attr-defined]
        offset = 0
        while offset < len(source):
            written = os.write(descriptor, source[offset:])
            if type(written) is not int or written <= 0:
                raise ValueError
            offset += written
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
        raise PrimeP6CliHostError() from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _host_platform() -> ImagePlatformDescriptor:
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
    if architecture is None:
        raise PrimeP6CliHostError()
    return ImagePlatformDescriptor("linux", architecture, None)


def _cancelled(signal: CancellationSignal | None) -> bool:
    if signal is None:
        return False
    try:
        return signal.cancelled is True
    except BaseException:
        raise PrimeP6CliHostError() from None


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
    "P6_CLI_DEADLINE_SECONDS",
    "PrimeP6CliHostError",
    "PrimeP6SmallVerificationService",
    "create_host_service_factory",
    "create_prime_p6_cli_factory",
)
