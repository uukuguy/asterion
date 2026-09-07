"""Operator-only host service for the one fixed P7 solving action."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, cast

from dotenv import dotenv_values

from asterion.applications.prime_agent.operator.development_preparation import (
    PrimeDevelopmentPaths,
    resolve_prepared_prime_development,
)
from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
    validate_prime_arc_agi_3_solve_receipt,
)
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.prime_agent_host import (
    PrimePresetExecutionCancelled,
    PrimePresetExecutionRequest,
    PrimePresetExecutionResult,
)
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK, HostPresentationSink
from asterion.services.progress import HostProgressEvent, HostProgressReporter
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryContext

from .p7_solving_host import P7SolvingReceiptStore, run_p7_solving_lifecycle
from .p7_solving_resource_lock import verify_p7_solving_resources
from .p7_solving_preparation import p7_solving_preparation_lock


_CAPABILITY_ID = "prime.arc-agi-3-solving"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.arc-agi-3-solving"
_APPLICATION_VERSION = "1.0.0"
_PRESET = "solve-first-public-level"
_MODEL = "deepseek-v4-flash"
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")
_DOCKER = Path("/usr/bin/docker")
_SOCKET = Path("/var/run/docker.sock")


class PrimeP7SolvingCliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 solving CLI host is unavailable")


@dataclass(frozen=True, repr=False)
class _Resources:
    paths: PrimeDevelopmentPaths
    operator_config: Mapping[str, object]
    external_root: Path
    image_digest: str
    asterion_src: Path


_LifecycleRunner = Callable[..., Awaitable[object]]


class PrimeP7SolvingService:
    """One execution and one matched receipt retrieval for a selected host."""

    __slots__ = ("_active", "_consumed", "_lifecycle_runner", "_progress", "_presentation", "_resources", "_store")

    def __init__(
        self,
        resources: object,
        *,
        lifecycle_runner: _LifecycleRunner | None = None,
        progress: HostProgressReporter | None = None,
        presentation: HostPresentationSink | None = None,
    ) -> None:
        self._active = True
        self._consumed = False
        self._resources = resources
        self._lifecycle_runner = _run_lifecycle if lifecycle_runner is None else lifecycle_runner
        self._progress = progress
        self._presentation = NOOP_HOST_PRESENTATION_SINK if presentation is None else presentation
        self._store = P7SolvingReceiptStore()

    def __repr__(self) -> str:
        return "PrimeP7SolvingService(redacted)"

    async def execute(
        self, request: PrimePresetExecutionRequest, *, signal: CancellationSignal | None = None
    ) -> PrimePresetExecutionResult:
        if (
            not self._active
            or self._consumed
            or type(request) is not PrimePresetExecutionRequest
            or request.preset != _PRESET
            or _RUN_ID.fullmatch(request.run_id) is None
        ):
            raise PrimeP7SolvingCliHostError()
        self._consumed = True
        if _cancelled(signal):
            raise PrimePresetExecutionCancelled()
        task = asyncio.ensure_future(self._lifecycle_runner(
            cast(_Resources, self._resources), request.run_id, receipt_store=self._store,
            progress=self._progress, presentation=self._presentation,
        ))
        try:
            receipt = await _await_with_cancellation(task, signal)
            validate_prime_arc_agi_3_solve_receipt(receipt)
            if not isinstance(receipt, PrimeArcAgi3SolveReceipt) or receipt.run_id != request.run_id:
                raise ValueError
            return PrimePresetExecutionResult(
                run_id=request.run_id, receipt_sha256=receipt.receipt_sha256,
                scope="p7-solving", promotion="unpromoted",
            )
        except PrimePresetExecutionCancelled:
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
            raise PrimeP7SolvingCliHostError() from None

    def get_receipt(self, *, run_id: str, receipt_sha256: str) -> PrimeArcAgi3SolveReceipt:
        if not self._active:
            raise PrimeP7SolvingCliHostError()
        try:
            return self._store.get_receipt(run_id=run_id, receipt_sha256=receipt_sha256)
        except BaseException:
            raise PrimeP7SolvingCliHostError() from None

    def _close(self) -> None:
        self._active = False


def create_prime_p7_solving_factory(
    *, repo_root: Path, lifecycle_runner: _LifecycleRunner | None = None,
) -> HostServiceFactoryBinding:
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        _emit(context.progress, "preflight", "started")
        try:
            resources = _preflight(root)
        except BaseException:
            _emit(context.progress, "preflight", "failed")
            raise PrimeP7SolvingCliHostError() from None
        _emit(context.progress, "preflight", "succeeded")
        service = PrimeP7SolvingService(
            resources, lifecycle_runner=lifecycle_runner, progress=context.progress,
            presentation=context.presentation,
        )
        try:
            yield service
        finally:
            service._close()

    return HostServiceFactoryBinding(_CAPABILITY_ID, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p7_solving_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or (context.provider_id, context.application_id, context.application_version, context.capability_id)
        != (_PROVIDER_ID, _APPLICATION_ID, _APPLICATION_VERSION, _CAPABILITY_ID)
        or dict(context.options)
    ):
        raise PrimeP7SolvingCliHostError()


def _preflight(repo_root: Path) -> _Resources:
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError
        paths = resolve_prepared_prime_development(repo_root, "p7-solving")
        external = (repo_root.parent / "external-prime" / "arc-agi-3").resolve()
        verify_p7_solving_resources(external)
        if not _DOCKER.is_file() or not _SOCKET.exists():
            raise ValueError
        return _Resources(
            paths, _operator_config(repo_root / ".env"), external,
            _inspect_image(), repo_root / "src",
        )
    except BaseException:
        raise PrimeP7SolvingCliHostError() from None


def _operator_config(path: Path) -> Mapping[str, object]:
    try:
        values = dotenv_values(path)
        api_key = values.get("DEEPSEEK_API_KEY")
        if (
            not values
            or any(type(key) is not str or type(value) is not str for key, value in values.items())
            or type(api_key) is not str
            or not api_key.strip()
            or values.get("ASTERION_PRIME_EXPERIMENT_MODEL") != _MODEL
        ):
            raise ValueError
        return dict(values)
    except BaseException:
        raise PrimeP7SolvingCliHostError() from None


async def _run_lifecycle(
    resources: _Resources, run_id: str, *, receipt_store: P7SolvingReceiptStore,
    progress: HostProgressReporter | None, presentation: HostPresentationSink | None,
) -> PrimeArcAgi3SolveReceipt:
    """Late-bind executable resources so factory preflight never starts a model or game."""
    try:
        from .p5_cli_host import _host_platform, _sealed_seccomp
        from .p7_solving_broker_service import P7SolvingBrokerService
        from .p7_solving_docker import P7SolvingDockerTransport, P7SolvingDockerWorker
        from .p7_solving_gateway import PrimeP7SolvingGateway
        from .p7_solving_sdk_provider import create_prime_p7_solving_sdk_provider

        resource_root = resources.external_root / "environment_files" / "ls20" / "9607627b"
        interpreter = resources.external_root / "venv" / "bin" / "python3"
        provider = create_prime_p7_solving_sdk_provider(resources.operator_config)
        broker = P7SolvingBrokerService(
            interpreter=interpreter, asterion_src=resources.asterion_src,
            resource_root=resource_root,
        )
        descriptor = _sealed_seccomp(resources.paths.seccomp)
        transport = P7SolvingDockerTransport(
            docker_executable=str(_DOCKER), socket_path=str(_SOCKET),
            seccomp_profile_fd=descriptor, platform=_host_platform(),
        )
        try:
            with TemporaryDirectory(prefix="asterion-p7-solving-") as workspace:
                os.chown(workspace, 65534, 65534)
                os.chmod(workspace, 0o700)
                worker = P7SolvingDockerWorker(
                    image_digest=resources.image_digest, transport=transport,
                    workspace=workspace, broker_private_dir=str(broker.private_dir),
                    broker_model_socket=str(broker.model_socket),
                )
                return await run_p7_solving_lifecycle(
                    gateway=cast(Any, PrimeP7SolvingGateway(node_bin=resources.paths.node)),
                    provider=provider, worker=worker, broker=broker,
                    receipt_store=receipt_store, run_id=run_id,
                    session_id="p7-solving-" + run_id,
                    prime_source_root=str(resources.paths.source_root), workspace=workspace,
                    progress=progress,
                    presentation=NOOP_HOST_PRESENTATION_SINK if presentation is None else presentation,
                )
        finally:
            try:
                transport.close()
            finally:
                os.close(descriptor)
    except asyncio.CancelledError:
        raise
    except BaseException:
        raise PrimeP7SolvingCliHostError() from None


def _inspect_image() -> str:
    try:
        image = p7_solving_preparation_lock()["image"]
        if type(image) is not dict or type(image.get("tag")) is not str or type(image.get("digest")) is not str:
            raise ValueError
        result = subprocess.run(
            (str(_DOCKER), "--host", "unix://" + str(_SOCKET), "image", "inspect", "--format", "{{.Id}}", image["tag"]),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={}, timeout=10, check=False,
        )
        if result.returncode != 0 or result.stdout.decode("ascii", "strict") != image["digest"] + "\n":
            raise ValueError
        return image["digest"]
    except BaseException:
        raise PrimeP7SolvingCliHostError() from None


def _emit(reporter: HostProgressReporter | None, component: str, state: str) -> None:
    if reporter is not None:
        try:
            reporter.emit(HostProgressEvent(component, state))
        except BaseException:
            pass


def _cancelled(signal: CancellationSignal | None) -> bool:
    if signal is None:
        return False
    try:
        return signal.cancelled is True
    except BaseException:
        raise PrimeP7SolvingCliHostError() from None


async def _await_with_cancellation(task: asyncio.Task[object], signal: CancellationSignal | None) -> object:
    while not task.done():
        if _cancelled(signal):
            raise PrimePresetExecutionCancelled()
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
    "PrimeP7SolvingCliHostError", "PrimeP7SolvingService",
    "create_host_service_factory", "create_prime_p7_solving_factory",
)
