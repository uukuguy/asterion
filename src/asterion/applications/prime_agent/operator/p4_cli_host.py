"""Installed local-root host for the fixed P4 continuity verification."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

from asterion.applications.prime_agent.operator import p2_cli_host as _p2
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


_CAPABILITY_ID = "prime.long-session-continuity-development"
_PROVIDER_ID = "prime-agent"
_APPLICATION_ID = "prime.long-session-continuity"
_APPLICATION_VERSION = "1.0.0"
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")
_MAX_OUTPUT_BYTES = 4096
_DEADLINE_SECONDS = 30


class PrimeP4CliHostError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P4 CLI host is unavailable")


@dataclass(frozen=True, repr=False)
class _P4CliResources:
    node_bin: str
    entrypoint: str
    prime_source_root: str


_Runner = Callable[[_P4CliResources, str], Awaitable[object]]


class PrimeP4SmallVerificationService:
    __slots__ = ("_active", "_consumed", "_resources", "_runner")

    def __init__(
        self, resources: _P4CliResources, *, runner: _Runner | None = None
    ) -> None:
        self._active = True
        self._consumed = False
        self._resources = resources
        self._runner = _run_p4_development if runner is None else runner

    def __repr__(self) -> str:
        return "PrimeP4SmallVerificationService(redacted)"

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
            raise PrimeP4CliHostError()
        self._consumed = True
        if _cancelled(signal):
            raise PrimeSmallVerificationCancelled()
        task = asyncio.create_task(self._runner(self._resources, request.run_id))
        try:
            result = await _await_with_cancellation(task, signal)
            digest = _private_result_digest(result, request.run_id)
            return PrimeSmallVerificationResult(
                run_id=request.run_id,
                trace_sha256=digest,
                scope="p4-development",
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
            raise PrimeP4CliHostError() from None

    def _close(self) -> None:
        self._active = False


def create_prime_p4_cli_factory(*, repo_root: Path) -> HostServiceFactoryBinding:
    root = Path(repo_root).resolve()

    @asynccontextmanager
    async def factory(context: HostServiceFactoryContext):
        _validate_context(context)
        try:
            service = PrimeP4SmallVerificationService(_preflight(root))
        except BaseException:
            raise PrimeP4CliHostError() from None
        try:
            yield service
        finally:
            service._close()

    return HostServiceFactoryBinding(_CAPABILITY_ID, (), factory)


def create_host_service_factory() -> HostServiceFactoryBinding:
    return create_prime_p4_cli_factory(repo_root=Path.cwd())


def _validate_context(context: object) -> None:
    if (
        type(context) is not HostServiceFactoryContext
        or context.provider_id != _PROVIDER_ID
        or context.application_id != _APPLICATION_ID
        or context.application_version != _APPLICATION_VERSION
        or context.capability_id != _CAPABILITY_ID
        or dict(context.options)
    ):
        raise PrimeP4CliHostError()


def _preflight(repo_root: Path) -> _P4CliResources:
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PrimeP4CliHostError()
    node = _p2._regular_executable(Path("/tmp/asterion-node22/bin/node"))
    entrypoint = _p2._regular_file(
        repo_root / "packages/typescript/prime-gateway/dist/src/p4-development-session.js"
    )
    source = _p2._regular_directory(repo_root / "3th-party/prime-agent")
    _p2._regular_file(
        source
        / "node_modules/@earendil-works/pi-coding-agent/dist/modes/daemon/daemon-mode.js"
    )
    _p2._regular_file(
        source
        / "node_modules/@earendil-works/pi-coding-agent/dist/modes/daemon/daemon-client.js"
    )
    _p2._regular_file(source / "node_modules/@earendil-works/pi-coding-agent/dist/index.js")
    return _P4CliResources(str(node), str(entrypoint), str(source))


async def _run_p4_development(resources: _P4CliResources, _: str) -> object:
    script = (
        "import { pathToFileURL } from 'node:url';"
        "const module = await import(pathToFileURL(process.argv[1]).href);"
        "const value = await module.runPrimeP4DevelopmentSmoke(process.argv[2]);"
        "process.stdout.write(JSON.stringify(value));"
    )
    try:
        process = await asyncio.create_subprocess_exec(
            resources.node_bin,
            "--input-type=module",
            "--eval",
            script,
            resources.entrypoint,
            resources.prime_source_root,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={},
        )
        async with asyncio.timeout(_DEADLINE_SECONDS):
            stdout, _stderr = await process.communicate()
    except BaseException:
        _terminate(process if "process" in locals() else None)
        raise PrimeP4CliHostError() from None
    if process.returncode != 0 or len(stdout) > _MAX_OUTPUT_BYTES:
        raise PrimeP4CliHostError()
    try:
        return json.loads(stdout.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PrimeP4CliHostError() from None


def _private_result_digest(result: object, run_id: str) -> str:
    if type(result) is not dict or set(result) != {"activeSessionId", "cursor"}:
        raise PrimeP4CliHostError()
    active_session_id = result["activeSessionId"]
    cursor = result["cursor"]
    if (
        type(active_session_id) is not str
        or not active_session_id
        or type(cursor) is not dict
        or set(cursor) != {"generation", "sequence"}
        or type(cursor["generation"]) is not str
        or not cursor["generation"]
        or type(cursor["sequence"]) is not int
        or isinstance(cursor["sequence"], bool)
        or cursor["sequence"] < 0
    ):
        raise PrimeP4CliHostError()
    encoded = json.dumps(
        {"run_id": run_id, "session": result},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _cancelled(signal: CancellationSignal | None) -> bool:
    return signal is not None and signal.cancelled


async def _await_with_cancellation(
    task: asyncio.Task[object], signal: CancellationSignal | None
) -> object:
    while not task.done():
        if _cancelled(signal):
            raise PrimeSmallVerificationCancelled()
        try:
            await asyncio.wait_for(asyncio.shield(task), 0.05)
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


def _terminate(process: asyncio.subprocess.Process | None) -> None:
    if process is not None and process.returncode is None:
        process.kill()
