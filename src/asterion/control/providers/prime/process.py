"""Private process boundary for the Prime control sidecar."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import IO

from asterion.immutable import RedactedImmutableMapping


PRIME_GATEWAY_IPC_PROTOCOL = "asterion.prime-gateway-ipc/v1"
_MAX_FRAME_BYTES = 1024 * 1024
_MAX_PRIVATE_ATTACHMENT_FRAME_BYTES = 12 * 1024 * 1024
_PRIVATE_PROCESS_UMASK = 0o077
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PUBLIC_ENV_ALLOWLIST = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "TMPDIR",
    }
)


class PrimeSidecarProcessError(RuntimeError):
    """Raised when the private Prime sidecar cannot produce a safe result."""

    def __init__(self, message: str = "Prime sidecar process failed") -> None:
        super().__init__(message)


@dataclass(frozen=True, repr=False)
class PrimeSidecarLaunchOptions:
    """Private launch inputs for the Prime sidecar."""

    node_executable: Path
    sidecar_entry: Path
    private_descriptor: Mapping[str, object]
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    close_timeout: float = 2.0
    request_timeout: float = 30.0
    private_stderr_sink: IO[bytes] | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_executable, Path)
            or not isinstance(self.sidecar_entry, Path)
            or not isinstance(self.private_descriptor, Mapping)
            or not isinstance(self.environ, Mapping)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in self.environ.items()
            )
            or not _positive_finite(self.close_timeout)
            or not _positive_finite(self.request_timeout)
            or not _valid_private_sink(self.private_stderr_sink)
        ):
            raise PrimeSidecarProcessError()
        object.__setattr__(
            self,
            "private_descriptor",
            RedactedImmutableMapping(self.private_descriptor),
        )
        object.__setattr__(self, "environ", MappingProxyType(dict(self.environ)))

    @property
    def argv(self) -> tuple[str, str]:
        return (
            str(self.node_executable.resolve(strict=False)),
            str(self.sidecar_entry.resolve(strict=False)),
        )

    def __repr__(self) -> str:
        return (
            "PrimeSidecarLaunchOptions("
            f"node_executable={str(self.node_executable)!r}, "
            f"sidecar_entry={str(self.sidecar_entry)!r}, "
            "private_descriptor=<redacted>, environ=<redacted>)"
        )


@dataclass(frozen=True, repr=False)
class PrimeSidecarSpawnPlan:
    """Preflighted direct process invocation."""

    argv: tuple[str, str]
    env: Mapping[str, str]
    pass_fds: tuple[int, ...]
    shell: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))

    def __repr__(self) -> str:
        return (
            "PrimeSidecarSpawnPlan("
            f"argv={self.argv!r}, pass_fds={self.pass_fds!r}, shell=False, "
            "env=<redacted>)"
        )


def build_prime_sidecar_spawn_plan(
    options: PrimeSidecarLaunchOptions,
    *,
    private_descriptor_fd: int = 3,
) -> PrimeSidecarSpawnPlan:
    """Validate executable/source paths and build a shell-free spawn plan."""

    if not isinstance(options, PrimeSidecarLaunchOptions):
        raise PrimeSidecarProcessError()
    if (
        isinstance(private_descriptor_fd, bool)
        or not isinstance(private_descriptor_fd, int)
        or private_descriptor_fd < 3
    ):
        raise PrimeSidecarProcessError()
    executable = _regular_existing_path(options.node_executable, executable=True)
    entry = _regular_existing_path(options.sidecar_entry, executable=False)
    env = {
        key: options.environ[key]
        for key in sorted(_PUBLIC_ENV_ALLOWLIST)
        if key in options.environ
    }
    env["ASTERION_PRIME_PRIVATE_FD"] = str(private_descriptor_fd)
    if options.private_stderr_sink is not None:
        env["ASTERION_PRIME_PRIVATE_DIAGNOSTICS"] = "1"
    return PrimeSidecarSpawnPlan(
        argv=(str(executable), str(entry)),
        env=env,
        pass_fds=(private_descriptor_fd,),
    )


class PrimeSidecarProcess:
    """JSON-line transport to a private Node sidecar process."""

    def __init__(self, options: PrimeSidecarLaunchOptions) -> None:
        self._options = options
        self._process: asyncio.subprocess.Process | None = None
        self._descriptor_fd: int | None = None
        self._closed = False
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: dict[
            str,
            tuple[
                Mapping[str, object],
                asyncio.Future[Mapping[str, object]],
                asyncio.TimerHandle,
            ],
        ] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._transport_failed = False
        build_prime_sidecar_spawn_plan(options)

    @classmethod
    async def start(cls, options: PrimeSidecarLaunchOptions) -> PrimeSidecarProcess:
        process = cls(options)
        await process._ensure_started()
        return process

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process is not None else None

    @property
    def pid(self) -> int | None:
        """Return the exact live sidecar PID without exposing launch inputs."""

        return self._process.pid if self._process is not None else None

    @property
    def closed(self) -> bool:
        return self._closed

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        request_id = envelope.get("id")
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            raise PrimeSidecarProcessError()
        line = _encode_frame(envelope)
        future: asyncio.Future[Mapping[str, object]] = (
            asyncio.get_running_loop().create_future()
        )
        async with self._lock:
            if self._closed or self._transport_failed or request_id in self._pending:
                raise PrimeSidecarProcessError()
            sidecar = await self._ensure_started()
            writer = sidecar.stdin
            reader = sidecar.stdout
            if writer is None or reader is None:
                raise PrimeSidecarProcessError()
            timeout_handle = asyncio.get_running_loop().call_later(
                self._options.request_timeout,
                self._expire_pending,
                request_id,
                future,
            )
            self._pending[request_id] = (dict(envelope), future, timeout_handle)
            if self._reader_task is None:
                self._reader_task = asyncio.create_task(self._read_responses(reader))
        try:
            try:
                async with self._write_lock:
                    if self._closed or self._transport_failed or writer.is_closing():
                        raise PrimeSidecarProcessError()
                    current = self._pending.get(request_id)
                    if current is not None and current[1] is future:
                        writer.write(line)
                        await asyncio.wait_for(
                            writer.drain(), timeout=self._options.request_timeout
                        )
            except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
                self._fail_transport()
                raise PrimeSidecarProcessError() from None
            except PrimeSidecarProcessError:
                self._fail_transport()
                raise
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            future.add_done_callback(_consume_future_exception)
            raise

    async def _read_responses(self, reader: asyncio.StreamReader) -> None:
        try:
            while not self._closed and not self._transport_failed:
                response_line = await reader.readline()
                if not response_line or len(response_line) > _MAX_FRAME_BYTES:
                    raise PrimeSidecarProcessError()
                response = _decode_frame(response_line)
                response_id = response.get("id")
                if not isinstance(response_id, str):
                    raise PrimeSidecarProcessError()
                pending = self._pending.pop(response_id, None)
                if pending is None:
                    raise PrimeSidecarProcessError()
                request, future, timeout_handle = pending
                timeout_handle.cancel()
                if future.cancelled():
                    continue
                if _is_exact_error_response(response, request):
                    future.set_exception(PrimeSidecarProcessError())
                    continue
                try:
                    validated = _validate_response(response, request)
                except PrimeSidecarProcessError:
                    future.set_exception(PrimeSidecarProcessError())
                    raise
                future.set_result(validated)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, PrimeSidecarProcessError):
            self._fail_transport()

    def _fail_transport(self) -> None:
        self._transport_failed = True
        pending = tuple(self._pending.values())
        self._pending.clear()
        for _, future, timeout_handle in pending:
            timeout_handle.cancel()
            if not future.done():
                future.set_exception(PrimeSidecarProcessError())
                future.add_done_callback(_consume_future_exception)

    def _expire_pending(
        self,
        request_id: str,
        future: asyncio.Future[Mapping[str, object]],
    ) -> None:
        current = self._pending.get(request_id)
        if current is None or current[1] is not future:
            return
        self._pending.pop(request_id, None)
        if not future.done():
            future.set_exception(PrimeSidecarProcessError())
            future.add_done_callback(_consume_future_exception)

    async def _stop_reader(self) -> None:
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task is None:
            return
        reader_task.cancel()
        with suppress(asyncio.CancelledError):
            await reader_task

    def events(
        self, envelope: Mapping[str, object]
    ) -> AsyncIterator[Mapping[str, object]]:
        return _event_iterator(self, envelope)

    async def close(self) -> None:
        if self._closed:
            return
        deadline = asyncio.get_running_loop().time() + self._options.close_timeout
        acquired = False
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=_remaining(deadline))
            acquired = True
            self._closed = True
            self._fail_transport()
            await self._stop_reader()
            process = self._process
            if process is None:
                return
            try:
                if process.stdin is not None and not process.stdin.is_closing():
                    process.stdin.close()
                    timeout = _phase_timeout(deadline, self._options.close_timeout)
                    await asyncio.wait_for(process.stdin.wait_closed(), timeout=timeout)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            if process.returncode is None:
                try:
                    timeout = _graceful_shutdown_timeout(
                        deadline, self._options.close_timeout
                    )
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                except TimeoutError:
                    if process.returncode is None:
                        process.terminate()
                    try:
                        timeout = _phase_timeout(deadline, self._options.close_timeout)
                        await asyncio.wait_for(process.wait(), timeout=timeout)
                    except TimeoutError:
                        if process.returncode is None:
                            process.kill()
                        await asyncio.wait_for(process.wait(), timeout=0.01)
            stopped = process.returncode is not None
            if not stopped:
                self._closed = False
                raise PrimeSidecarProcessError()
        except (TimeoutError, OSError):
            self._closed = False
            raise PrimeSidecarProcessError() from None
        finally:
            if acquired:
                self._lock.release()

    async def _ensure_started(self) -> asyncio.subprocess.Process:
        if self._process is not None:
            if self._process.returncode is not None:
                raise PrimeSidecarProcessError()
            return self._process
        read_fd, write_fd = os.pipe()
        self._descriptor_fd = read_fd
        try:
            os.set_inheritable(read_fd, True)
            descriptor = json.dumps(
                dict(self._options.private_descriptor),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            os.write(write_fd, descriptor)
            os.close(write_fd)
            write_fd = -1
            plan = build_prime_sidecar_spawn_plan(
                self._options, private_descriptor_fd=read_fd
            )
            self._process = await asyncio.create_subprocess_exec(
                *plan.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=self._options.private_stderr_sink
                if self._options.private_stderr_sink is not None
                else asyncio.subprocess.DEVNULL,
                env=dict(plan.env),
                pass_fds=plan.pass_fds,
                umask=_PRIVATE_PROCESS_UMASK,
                limit=_MAX_FRAME_BYTES + 1,
            )
            return self._process
        except (OSError, ValueError):
            raise PrimeSidecarProcessError() from None
        finally:
            if write_fd >= 0:
                os.close(write_fd)
            os.close(read_fd)


async def _event_iterator(
    process: PrimeSidecarProcess, envelope: Mapping[str, object]
) -> AsyncIterator[Mapping[str, object]]:
    response = await process.request(envelope)
    events = response.get("events")
    if not isinstance(events, list):
        raise PrimeSidecarProcessError()
    for event in events:
        if not isinstance(event, Mapping):
            raise PrimeSidecarProcessError()
        yield event


def _positive_finite(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _valid_private_sink(value: object) -> bool:
    if value is None:
        return True
    fileno = getattr(value, "fileno", None)
    if not callable(fileno):
        return False
    try:
        descriptor = fileno()
    except (OSError, ValueError):
        return False
    return type(descriptor) is int and descriptor >= 0


def _remaining(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _phase_timeout(deadline: float, total: float) -> float:
    return min(_remaining(deadline), max(total / 3, 0.001))


def _graceful_shutdown_timeout(deadline: float, total: float) -> float:
    return min(_remaining(deadline), max(total * 2 / 3, 0.001))


def _regular_existing_path(path: Path, *, executable: bool) -> Path:
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except (OSError, RuntimeError):
        raise PrimeSidecarProcessError() from None
    if not stat.st_mode or not resolved.is_file():
        raise PrimeSidecarProcessError()
    if executable and not os.access(resolved, os.X_OK):
        raise PrimeSidecarProcessError()
    return resolved


def _encode_frame(value: Mapping[str, object]) -> bytes:
    try:
        encoded = (
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError):
        raise PrimeSidecarProcessError() from None
    maximum = _MAX_FRAME_BYTES
    command = value.get("command")
    if (
        value.get("type") == "session-context.execute"
        and isinstance(command, Mapping)
        and command.get("operation") == "session.attachment.bind"
    ):
        maximum = _MAX_PRIVATE_ATTACHMENT_FRAME_BYTES
    if len(encoded) > maximum:
        raise PrimeSidecarProcessError()
    return encoded


def _decode_frame(line: bytes) -> Mapping[str, object]:
    if not line.endswith(b"\n"):
        raise PrimeSidecarProcessError()
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PrimeSidecarProcessError() from None
    if not isinstance(value, Mapping):
        raise PrimeSidecarProcessError()
    return value


def _consume_future_exception(
    future: asyncio.Future[Mapping[str, object]],
) -> None:
    if future.cancelled():
        return
    with suppress(PrimeSidecarProcessError):
        future.exception()


def _is_exact_error_response(
    response: Mapping[str, object], request: Mapping[str, object]
) -> bool:
    return (
        response.get("protocol") == PRIME_GATEWAY_IPC_PROTOCOL
        and response.get("id") == request.get("id")
        and response.get("type") == "error"
        and response.get("code") == "prime-gateway-sidecar-failed"
        and set(response) == {"protocol", "id", "type", "code"}
    )


def _validate_response(
    response: Mapping[str, object], request: Mapping[str, object]
) -> Mapping[str, object]:
    if response.get("type") == "error":
        if (
            response.get("protocol") == PRIME_GATEWAY_IPC_PROTOCOL
            and response.get("id") == request.get("id")
            and response.get("code") == "prime-gateway-sidecar-failed"
            and set(response) == {"protocol", "id", "type", "code"}
        ):
            raise PrimeSidecarProcessError()
        raise PrimeSidecarProcessError()
    request_type = request.get("type")
    expected_response_type = {
        "authority.update": "authority.accepted",
        "command.accept": "command.accepted",
        "ecosystem_activate": "ecosystem_receipt",
        "events.stream": "events.batch",
        "private.read": "private.value",
        "rlm.binding.read": "rlm.binding.value",
        "rlm.lifecycle.read": "rlm.lifecycle.batch",
        "session-context.cancel": "session-context.cancel.accepted",
        "session-context.execute": "session-context.receipt",
    }.get(request_type) if isinstance(request_type, str) else None
    if (
        response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
        or response.get("id") != request.get("id")
        or response.get("type") != expected_response_type
        or response.get("type")
        not in {
            "authority.accepted",
            "command.accepted",
            "ecosystem_receipt",
            "events.batch",
            "private.value",
            "rlm.binding.value",
            "rlm.lifecycle.batch",
            "session-context.cancel.accepted",
            "session-context.receipt",
        }
    ):
        raise PrimeSidecarProcessError()
    expected = {"protocol", "id", "type"}
    if response.get("type") == "events.batch":
        expected = expected | {"events"}
    if response.get("type") == "rlm.lifecycle.batch":
        expected = expected | {"lifecycle"}
        if not isinstance(response.get("lifecycle"), list):
            raise PrimeSidecarProcessError()
    if response.get("type") == "rlm.binding.value":
        expected = expected | {"binding"}
        if not isinstance(response.get("binding"), Mapping):
            raise PrimeSidecarProcessError()
    if response.get("type") == "private.value":
        expected = expected | {"text"}
        if not isinstance(response.get("text"), str):
            raise PrimeSidecarProcessError()
    if response.get("type") in {
        "ecosystem_receipt",
        "session-context.receipt",
    }:
        expected = expected | {"receipt"}
        if not isinstance(response.get("receipt"), Mapping):
            raise PrimeSidecarProcessError()
    if set(response) != expected:
        raise PrimeSidecarProcessError()
    return response
