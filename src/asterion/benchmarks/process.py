"""Direct, bounded execution of an already-authorized process plan."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from asterion.benchmarks.evidence import (
    BenchmarkProgressEvent,
    BenchmarkTaskResult,
)
from asterion.benchmarks.model import BenchmarkTaskInvocation
from asterion.runtime.host import CancellationSignal


_DIGEST_LENGTH = 64
_POLL_SECONDS = 0.02
_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)


class BenchmarkProcessError(RuntimeError):
    """Stable command-, output-, environment-, and path-free failure."""


@dataclass(frozen=True, slots=True, init=False)
class AuthorizedProcessTaskPlan:
    """Already-authorized direct process invocation with finite bounds."""

    argv: tuple[str, ...] = field(repr=False)
    cwd: Path = field(repr=False)
    environment: Mapping[str, str] = field(repr=False)
    deadline_seconds: float
    output_limit_bytes: int
    case_limit: int
    termination_grace_seconds: float
    content_digests: tuple[str, ...]

    def __init__(
        self,
        *,
        argv: Iterable[str],
        cwd: Path,
        environment: Mapping[str, str],
        deadline_seconds: float,
        output_limit_bytes: int,
        case_limit: int,
        termination_grace_seconds: float = 1.0,
        content_digests: Iterable[str] = (),
    ) -> None:
        try:
            argv_snapshot = tuple(argv)
            environment_snapshot = dict(environment)
            digest_snapshot = tuple(content_digests)
            cwd_snapshot = Path(cwd)
        except (TypeError, ValueError):
            raise ValueError("authorized benchmark process plan is invalid") from None
        object.__setattr__(self, "argv", argv_snapshot)
        object.__setattr__(self, "cwd", cwd_snapshot)
        object.__setattr__(
            self,
            "environment",
            MappingProxyType(environment_snapshot),
        )
        object.__setattr__(
            self,
            "deadline_seconds",
            deadline_seconds,
        )
        object.__setattr__(
            self,
            "output_limit_bytes",
            output_limit_bytes,
        )
        object.__setattr__(self, "case_limit", case_limit)
        object.__setattr__(
            self,
            "termination_grace_seconds",
            termination_grace_seconds,
        )
        object.__setattr__(self, "content_digests", digest_snapshot)
        self.__post_init__()

    def __post_init__(self) -> None:
        if (
            not self.argv
            or any(
                not isinstance(argument, str) or not argument or "\x00" in argument
                for argument in self.argv
            )
            or not Path(self.argv[0]).is_absolute()
            or not self.cwd.is_absolute()
            or any(
                not isinstance(name, str)
                or not name
                or "=" in name
                or "\x00" in name
                or not isinstance(value, str)
                or "\x00" in value
                for name, value in self.environment.items()
            )
            or not _positive_finite(self.deadline_seconds)
            or type(self.output_limit_bytes) is not int
            or self.output_limit_bytes <= 0
            or type(self.case_limit) is not int
            or self.case_limit <= 0
            or not _positive_finite(self.termination_grace_seconds)
            or any(not _digest(value) for value in self.content_digests)
        ):
            raise ValueError("authorized benchmark process plan is invalid")


# Concise compatibility name for callers that describe the same value as a
# process plan rather than a task plan.
AuthorizedProcessPlan = AuthorizedProcessTaskPlan


@dataclass(frozen=True, slots=True)
class ProcessExecutionDetails:
    """Private bounded process details excluded from public result repr."""

    exit_code: int | None
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    failure_class: str | None


@dataclass(slots=True)
class _BoundedCapture:
    limit: int
    value: bytearray = field(default_factory=bytearray)
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        remaining = self.limit - len(self.value)
        if remaining > 0:
            self.value.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True


class AuthorizedProcessTaskExecutor:
    """Execute only the immutable process plan supplied by the binding."""

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        if (
            not isinstance(invocation, BenchmarkTaskInvocation)
            or not isinstance(
                invocation.private_payload,
                AuthorizedProcessTaskPlan,
            )
            or not _is_cancellation_signal(cancellation)
            or not callable(on_progress)
        ):
            raise BenchmarkProcessError(
                "authorized benchmark process invocation is invalid"
            )
        plan = invocation.private_payload
        task_id = invocation.task_id
        if cancellation.cancelled:
            return _task_result(
                task_id,
                plan,
                status="cancelled",
                completed_cases=0,
                details=ProcessExecutionDetails(
                    exit_code=None,
                    stdout=b"",
                    stderr=b"",
                    stdout_truncated=False,
                    stderr_truncated=False,
                    duration_ms=0,
                    failure_class="cancelled",
                ),
            )

        sequence = 1
        on_progress(
            _progress(
                task_id,
                sequence=sequence,
                phase="preparing",
                completed_cases=0,
                total_cases=plan.case_limit,
            )
        )
        started_at = time.monotonic()
        process = _start_process(plan)
        stdout = _BoundedCapture(plan.output_limit_bytes)
        stderr = _BoundedCapture(plan.output_limit_bytes)
        readers = (
            _reader_thread(process.stdout, stdout),
            _reader_thread(process.stderr, stderr),
        )
        for reader in readers:
            reader.start()

        sequence += 1
        termination: str | None = None
        try:
            on_progress(
                _progress(
                    task_id,
                    sequence=sequence,
                    phase="executing",
                    completed_cases=0,
                    total_cases=plan.case_limit,
                )
            )
            deadline = started_at + plan.deadline_seconds
            while process.poll() is None:
                if cancellation.cancelled:
                    termination = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    termination = "deadline"
                    break
                try:
                    process.wait(
                        timeout=min(
                            _POLL_SECONDS,
                            max(0.001, deadline - time.monotonic()),
                        )
                    )
                except subprocess.TimeoutExpired:
                    continue

            if termination is not None:
                _terminate_process_group(
                    process,
                    grace_seconds=plan.termination_grace_seconds,
                )
                _finish_readers(
                    process,
                    readers,
                    grace_seconds=plan.termination_grace_seconds,
                )
            else:
                process.wait()
                _finish_readers(
                    process,
                    readers,
                    grace_seconds=plan.termination_grace_seconds,
                )

            return_code = process.returncode
            status = (
                "cancelled"
                if termination == "cancelled"
                else "completed"
                if termination is None and return_code == 0
                else "failed"
            )
            completed_cases = plan.case_limit if status == "completed" else 0
            sequence += 1
            on_progress(
                _progress(
                    task_id,
                    sequence=sequence,
                    phase="finalizing",
                    completed_cases=completed_cases,
                    total_cases=plan.case_limit,
                )
            )
            details = ProcessExecutionDetails(
                exit_code=return_code,
                stdout=bytes(stdout.value),
                stderr=bytes(stderr.value),
                stdout_truncated=stdout.truncated,
                stderr_truncated=stderr.truncated,
                duration_ms=max(
                    0,
                    int(round((time.monotonic() - started_at) * 1000)),
                ),
                failure_class=(
                    termination
                    if termination is not None
                    else None
                    if status == "completed"
                    else "exit"
                ),
            )
            return _task_result(
                task_id,
                plan,
                status=status,
                completed_cases=completed_cases,
                details=details,
            )
        except BaseException:
            _terminate_process_group(
                process,
                grace_seconds=plan.termination_grace_seconds,
            )
            _close_streams(process)
            for reader in readers:
                reader.join(timeout=plan.termination_grace_seconds)
            raise
        finally:
            _close_streams(process)


def _start_process(
    plan: AuthorizedProcessTaskPlan,
) -> subprocess.Popen[bytes]:
    if os.name != "posix":
        raise BenchmarkProcessError(
            "authorized benchmark process groups are unsupported"
        )
    try:
        return subprocess.Popen(
            plan.argv,
            cwd=plan.cwd,
            env=dict(plan.environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            text=False,
            bufsize=0,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError):
        raise BenchmarkProcessError(
            "authorized benchmark process failed to start"
        ) from None


def _reader_thread(
    stream: object,
    capture: _BoundedCapture,
) -> threading.Thread:
    if stream is None or not hasattr(stream, "read"):
        raise BenchmarkProcessError(
            "authorized benchmark process stream is unavailable"
        )

    def read() -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                capture.append(chunk)
        except OSError:
            return

    return threading.Thread(
        target=read,
        name="asterion-benchmark-output",
        daemon=True,
    )


def _finish_readers(
    process: subprocess.Popen[bytes],
    readers: tuple[threading.Thread, ...],
    *,
    grace_seconds: float,
) -> None:
    for reader in readers:
        reader.join(timeout=grace_seconds)
    if any(reader.is_alive() for reader in readers):
        _terminate_process_group(process, grace_seconds=grace_seconds)
        _close_streams(process)
        for reader in readers:
            reader.join(timeout=grace_seconds)
    if any(reader.is_alive() for reader in readers):
        raise BenchmarkProcessError("authorized benchmark process cleanup failed")


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float,
) -> None:
    _signal_group(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
    # The direct child may have exited while a descendant ignored SIGTERM.
    # Always signal the dedicated group forcefully before returning.
    _signal_group(process.pid, _KILL_SIGNAL)
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        raise BenchmarkProcessError(
            "authorized benchmark process cleanup failed"
        ) from None


def _signal_group(process_group: int, value: int) -> None:
    try:
        os.killpg(process_group, value)
    except ProcessLookupError:
        pass
    except OSError:
        raise BenchmarkProcessError(
            "authorized benchmark process cleanup failed"
        ) from None


def _close_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


def _progress(
    task_id: str,
    *,
    sequence: int,
    phase: str,
    completed_cases: int,
    total_cases: int,
) -> BenchmarkProgressEvent:
    return BenchmarkProgressEvent(
        task_id=task_id,
        sequence=sequence,
        phase=phase,
        completed_cases=completed_cases,
        total_cases=total_cases,
        content_digest=None,
        private_payload=None,
    )


def _task_result(
    task_id: str,
    plan: AuthorizedProcessTaskPlan,
    *,
    status: str,
    completed_cases: int,
    details: ProcessExecutionDetails,
) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(
        task_id=task_id,
        status=status,
        completed_cases=completed_cases,
        content_digests=(plan.content_digests if status == "completed" else ()),
        private_payload=details,
    )


def _positive_finite(value: object) -> bool:
    return (
        type(value) in {int, float}
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_cancellation_signal(value: object) -> bool:
    try:
        return isinstance(value.cancelled, bool)
    except Exception:
        return False
