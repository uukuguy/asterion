"""Private process boundary for the Prime control sidecar."""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from asterion.immutable import RedactedImmutableMapping


PRIME_GATEWAY_IPC_PROTOCOL = "asterion.prime-gateway-ipc/v1"
_MAX_FRAME_BYTES = 1024 * 1024
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
        build_prime_sidecar_spawn_plan(options)

    @classmethod
    async def start(cls, options: PrimeSidecarLaunchOptions) -> PrimeSidecarProcess:
        process = cls(options)
        await process._ensure_started()
        return process

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process is not None else None

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        async with self._lock:
            if self._closed:
                raise PrimeSidecarProcessError()
            sidecar = await self._ensure_started()
            writer = sidecar.stdin
            reader = sidecar.stdout
            if writer is None or reader is None:
                raise PrimeSidecarProcessError()
            line = _encode_frame(envelope)
            try:
                writer.write(line)
                await asyncio.wait_for(writer.drain(), timeout=self._options.request_timeout)
                response_line = await asyncio.wait_for(
                    reader.readline(), timeout=self._options.request_timeout
                )
            except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
                raise PrimeSidecarProcessError() from None
            if not response_line or len(response_line) > _MAX_FRAME_BYTES:
                raise PrimeSidecarProcessError()
            response = _decode_frame(response_line)
            return _validate_response(response, envelope)

    def events(
        self, envelope: Mapping[str, object]
    ) -> AsyncIterator[Mapping[str, object]]:
        return _event_iterator(self, envelope)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is None:
            return
        try:
            if process.stdin is not None and not process.stdin.is_closing():
                process.stdin.close()
                await process.stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=self._options.close_timeout)
        except TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=self._options.close_timeout)
            except TimeoutError:
                raise PrimeSidecarProcessError() from None

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
                stderr=asyncio.subprocess.DEVNULL,
                env=dict(plan.env),
                pass_fds=plan.pass_fds,
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
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        ) + b"\n"
    except (TypeError, ValueError):
        raise PrimeSidecarProcessError() from None
    if len(encoded) > _MAX_FRAME_BYTES:
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


def _validate_response(
    response: Mapping[str, object], request: Mapping[str, object]
) -> Mapping[str, object]:
    if (
        response.get("protocol") != PRIME_GATEWAY_IPC_PROTOCOL
        or response.get("id") != request.get("id")
        or response.get("type") not in {"command.accepted", "events.batch"}
    ):
        raise PrimeSidecarProcessError()
    expected = {"protocol", "id", "type"}
    if response.get("type") == "events.batch":
        expected = expected | {"events"}
    if set(response) != expected:
        raise PrimeSidecarProcessError()
    return response
