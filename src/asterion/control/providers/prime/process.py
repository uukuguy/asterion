"""Private process boundary for the Prime control sidecar."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import IO

from asterion.immutable import RedactedImmutableMapping


PRIME_GATEWAY_IPC_PROTOCOL = "asterion.prime-gateway-ipc/v1"
PRIME_DAEMON_LIFECYCLE_PROTOCOL = "asterion.prime-daemon-lifecycle/v1"
_MAX_FRAME_BYTES = 1024 * 1024
_MAX_PRIVATE_ATTACHMENT_FRAME_BYTES = 12 * 1024 * 1024
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_PRIVATE_PROCESS_UMASK = 0o077
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LIFECYCLE_TOKEN = re.compile(r"^[0-9a-f]{64}$")
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

    _SAFE_CODES = frozenset({"response-timeout"})

    def __init__(
        self, message: str = "Prime sidecar process failed", *, safe_code: str | None = None
    ) -> None:
        if safe_code is not None and safe_code not in self._SAFE_CODES:
            raise ValueError("Prime sidecar process error safe code is invalid")
        self.safe_code = safe_code
        super().__init__(message)


class PrimeDaemonLifecycleFailure(PrimeSidecarProcessError):
    """A fixed, safe host lifecycle failure category."""

    _PHASES = frozenset({"coordinator", "manifest", "prepare", "shutdown", "fence", "start", "restore"})

    def __init__(self, phase: str = "coordinator") -> None:
        if phase not in self._PHASES:
            phase = "coordinator"
        super().__init__()
        self.phase = phase


class PrimeDaemonLifecycle:
    """Host-injected, serialized restart boundary for one owned Prime daemon."""

    def __init__(
        self,
        *,
        stop: Callable[[str], Awaitable[None]],
        start: Callable[[str], Awaitable[None]],
        timeout: float,
    ) -> None:
        if not callable(stop) or not callable(start) or not _positive_finite(timeout):
            raise PrimeSidecarProcessError()
        self._stop = stop
        self._start = start
        self._timeout = float(timeout)
        self._lock = asyncio.Lock()

    async def restart(self, active_session_id: str) -> None:
        if not isinstance(active_session_id, str) or _REQUEST_ID.fullmatch(active_session_id) is None:
            raise PrimeSidecarProcessError()
        async with self._lock:
            try:
                await asyncio.wait_for(self._stop(active_session_id), timeout=self._timeout)
                await asyncio.wait_for(self._start(active_session_id), timeout=self._timeout)
            except PrimeDaemonLifecycleFailure:
                raise
            except (OSError, RuntimeError, TimeoutError, ValueError):
                raise PrimeSidecarProcessError() from None


class PrimeDaemonLifecycleServer:
    """Private, single-purpose restart endpoint injected by the host.

    The Node gateway receives only this socket address and an opaque bearer
    token.  The owned daemon argv, environment, and process handles remain in
    the Python host, so a checkpoint cannot turn into arbitrary process
    execution.
    """

    def __init__(
        self,
        *,
        lifecycle: PrimeDaemonLifecycle,
        socket_path: Path,
        token: str,
        session_id: str,
        diagnostic: Callable[[str], None] | None = None,
    ) -> None:
        if (
            not isinstance(lifecycle, PrimeDaemonLifecycle)
            or not isinstance(socket_path, Path)
            or not isinstance(token, str)
            or _LIFECYCLE_TOKEN.fullmatch(token) is None
            or not isinstance(session_id, str)
            or _REQUEST_ID.fullmatch(session_id) is None
            or diagnostic is not None and not callable(diagnostic)
        ):
            raise PrimeSidecarProcessError()
        self._lifecycle = lifecycle
        self._socket_path = socket_path
        self._token = token
        self._session_id = session_id
        self._diagnostic = diagnostic
        self._server: asyncio.AbstractServer | None = None
        self._restart_tasks: set[asyncio.Task[None]] = set()

    @property
    def descriptor(self) -> Mapping[str, str]:
        return MappingProxyType({
            "socketPath": str(self._socket_path),
            "token": self._token,
        })

    async def start(self) -> None:
        if self._server is not None:
            raise PrimeSidecarProcessError()
        parent = self._socket_path.parent
        try:
            if not parent.is_dir() or parent.is_symlink():
                raise OSError
            if self._socket_path.exists() or self._socket_path.is_symlink():
                raise OSError
            self._server = await asyncio.start_unix_server(
                self._handle_client, path=str(self._socket_path)
            )
            self._socket_path.chmod(0o600)
        except (OSError, ValueError):
            await self.close()
            raise PrimeSidecarProcessError() from None

    async def close(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        tasks, self._restart_tasks = self._restart_tasks, set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            if self._socket_path.exists() and not self._socket_path.is_symlink():
                self._socket_path.unlink()
        except OSError:
            raise PrimeSidecarProcessError() from None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            frame = await asyncio.wait_for(reader.readline(), timeout=5)
            request = self._validated_restart_request(frame)
            if request is not None:
                request_id, active_session_id = request
                # This connection belongs to the predecessor gateway.  Prime
                # deliberately tears it down during its prepared shutdown, so
                # only acknowledge admission here; the successor observes the
                # durable, request-id-bound completion receipt.
                task = asyncio.create_task(
                    self._restart_and_record(request_id, active_session_id)
                )
                self._restart_tasks.add(task)
                task.add_done_callback(self._restart_tasks.discard)
                self._note("accepted")
                writer.write(_encode_frame({
                    "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                    "id": request_id,
                    "type": "accepted",
                }))
                await writer.drain()
        except (OSError, TimeoutError, ValueError, PrimeSidecarProcessError):
            self._note("failed")
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    def _note(self, stage: str) -> None:
        if stage not in {"accepted", "failed"}:
            return
        callback = self._diagnostic
        if callback is not None:
            with suppress(Exception):
                callback(stage)

    async def _restart_and_record(self, request_id: str, active_session_id: str) -> None:
        response: Mapping[str, object]
        try:
            await self._lifecycle.restart(active_session_id)
            response = {
                "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                "id": request_id,
                "type": "restarted",
            }
        except PrimeDaemonLifecycleFailure as error:
            response = {
                "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                "id": request_id,
                "type": "error",
                "phase": error.phase,
            }
        except PrimeSidecarProcessError:
            response = {
                "protocol": PRIME_DAEMON_LIFECYCLE_PROTOCOL,
                "id": request_id,
                "type": "error",
                "phase": "coordinator",
            }
        self._write_restart_receipt(request_id, response)

    def _write_restart_receipt(self, request_id: str, response: Mapping[str, object]) -> None:
        """Durably publish only the fixed lifecycle outcome for its requester."""
        target = self._socket_path.parent / f".asterion-lifecycle-{request_id}.json"
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(_encode_frame(response))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except OSError:
            with suppress(OSError):
                temporary.unlink()
            raise PrimeSidecarProcessError() from None

    def _validated_restart_request(self, frame: bytes) -> tuple[str, str] | None:
        if not frame or len(frame) > 4096:
            return None
        try:
            request = _decode_frame(frame)
        except PrimeSidecarProcessError:
            return None
        request_id = request.get("id")
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            return None
        if (
            set(request) != {"protocol", "id", "type", "token", "session_id", "active_session_id"}
            or request.get("protocol") != PRIME_DAEMON_LIFECYCLE_PROTOCOL
            or request.get("type") != "restart"
            or request.get("token") != self._token
            or request.get("session_id") != self._session_id
            or not isinstance(request.get("active_session_id"), str)
            or _REQUEST_ID.fullmatch(request["active_session_id"]) is None
        ):
            return None
        return request_id, request["active_session_id"]


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
            future.set_exception(PrimeSidecarProcessError(safe_code="response-timeout"))
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
                start_new_session=True,
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
    request = dict(envelope)
    if request.get("type") != "client_observations":
        response = await process.request(request)
        values = response.get("events")
        if not isinstance(values, list):
            raise PrimeSidecarProcessError()
        for event in values:
            if not isinstance(event, Mapping):
                raise PrimeSidecarProcessError()
            yield event
        return

    cursor = request.get("cursor")
    if cursor is None:
        generation: int | None = None
        sequence = 0
    elif (
        isinstance(cursor, Mapping)
        and set(cursor) == {"generation", "sequence"}
        and _safe_integer(cursor.get("generation"), minimum=1)
        and _safe_integer(cursor.get("sequence"), minimum=0)
    ):
        generation = int(cursor["generation"])
        sequence = int(cursor["sequence"])
    else:
        raise PrimeSidecarProcessError()

    while True:
        response = await process.request(request)
        values = response.get("observations")
        if not isinstance(values, list):
            raise PrimeSidecarProcessError()

        page_generation = generation
        page_sequence = sequence
        for event in values:
            event_generation = event.get("generation") if isinstance(event, Mapping) else None
            event_sequence = event.get("source_sequence") if isinstance(event, Mapping) else None
            if (
                not isinstance(event, Mapping)
                or not _safe_integer(event_generation, minimum=1)
                or not _safe_integer(event_sequence, minimum=1)
                or not isinstance(event_generation, int)
                or not isinstance(event_sequence, int)
                or event_sequence != page_sequence + 1
                or (page_generation is not None and event_generation != page_generation)
            ):
                raise PrimeSidecarProcessError()
            page_generation = event_generation
            page_sequence = event_sequence

        next_cursor = response.get("next_cursor")
        if next_cursor is None:
            generation = page_generation
            sequence = page_sequence
            for event in values:
                if not isinstance(event, Mapping):
                    raise PrimeSidecarProcessError()
                yield event
            return
        if (
            not isinstance(next_cursor, Mapping)
            or set(next_cursor) != {"generation", "sequence"}
            or not _safe_integer(next_cursor.get("generation"), minimum=1)
            or not _safe_integer(next_cursor.get("sequence"), minimum=1)
            or not values
            or page_generation is None
            or next_cursor["generation"] != page_generation
            or next_cursor["sequence"] != page_sequence
        ):
            raise PrimeSidecarProcessError()
        generation = page_generation
        sequence = page_sequence
        request["cursor"] = dict(next_cursor)
        for event in values:
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


def _safe_integer(value: object, *, minimum: int) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and minimum <= value <= _MAX_SAFE_INTEGER
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
        "client_value_read": "client_value",
        "ecosystem_activate": "ecosystem_receipt",
        "long-running.execute": "long-running.receipt",
        "operation.cancel": "operation.receipt",
        "operation.execute": "operation.receipt",
        "operation.reconcile": "operation.receipt",
        "events.stream": "events.batch",
        "client_observations": "client_observations.batch",
        "private.read": "private.value",
        "rlm.binding.read": "rlm.binding.value",
        "rlm.message.binding.read": "rlm.message.binding.value",
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
            "client_value",
            "client_observations.batch",
            "ecosystem_receipt",
            "long-running.receipt",
            "operation.receipt",
            "events.batch",
            "private.value",
            "rlm.binding.value",
            "rlm.message.binding.value",
            "rlm.lifecycle.batch",
            "session-context.cancel.accepted",
            "session-context.receipt",
        }
    ):
        raise PrimeSidecarProcessError()
    expected = {"protocol", "id", "type"}
    if response.get("type") == "events.batch":
        expected = expected | {"events"}
    if response.get("type") == "client_observations.batch":
        expected = expected | {"observations", "next_cursor"}
        if not isinstance(response.get("observations"), list):
            raise PrimeSidecarProcessError()
        next_cursor = response.get("next_cursor")
        if next_cursor is not None and not isinstance(next_cursor, Mapping):
            raise PrimeSidecarProcessError()
    if response.get("type") == "client_value":
        expected = expected | {"descriptor", "body_base64"}
        if (
            not isinstance(response.get("descriptor"), Mapping)
            or not isinstance(response.get("body_base64"), str)
        ):
            raise PrimeSidecarProcessError()
    if response.get("type") == "rlm.lifecycle.batch":
        expected = expected | {"lifecycle"}
        if not isinstance(response.get("lifecycle"), list):
            raise PrimeSidecarProcessError()
    if response.get("type") in {
        "rlm.binding.value",
        "rlm.message.binding.value",
    }:
        expected = expected | {"binding"}
        if not isinstance(response.get("binding"), Mapping):
            raise PrimeSidecarProcessError()
    if response.get("type") == "private.value":
        expected = expected | {"text"}
        if not isinstance(response.get("text"), str):
            raise PrimeSidecarProcessError()
    if response.get("type") == "long-running.receipt":
        expected = expected | {"receipt"}
        receipt = response.get("receipt")
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != {"commandId", "commandDigest", "status"}
            or receipt.get("commandId") != request.get("command_id")
            or not isinstance(receipt.get("commandId"), str)
            or _REQUEST_ID.fullmatch(receipt["commandId"]) is None
            or not isinstance(receipt.get("commandDigest"), str)
            or _LIFECYCLE_TOKEN.fullmatch(receipt["commandDigest"]) is None
            or receipt.get("status") not in {"succeeded", "failed", "uncertain"}
        ):
            raise PrimeSidecarProcessError()
    if response.get("type") in {
        "ecosystem_receipt",
        "operation.receipt",
        "session-context.receipt",
    }:
        expected = expected | {"receipt"}
        if not isinstance(response.get("receipt"), Mapping):
            raise PrimeSidecarProcessError()
    if set(response) != expected:
        raise PrimeSidecarProcessError()
    return response
