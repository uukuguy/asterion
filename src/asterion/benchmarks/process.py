"""Authorized local process execution for benchmark tasks."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import IO, NoReturn, Self

from asterion.benchmarks.evidence import BenchmarkProgressEvent, BenchmarkTaskResult
from asterion.benchmarks.model import BenchmarkTaskInvocation
from asterion.runtime.host import CancellationSignal


_MAX_OUTPUT_CAP_BYTES = 1024 * 1024
_IDENTIFIER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyz0123456789.-"
)
_SECRET_ENV_FRAGMENTS = (
    "answer",
    "auth",
    "credential",
    "key",
    "password",
    "prompt",
    "secret",
    "token",
)


class BenchmarkProcessError(ValueError):
    """Raised when an authorized benchmark process boundary is invalid."""


class _ProcessAuthority:
    pass


class AuthorizedProcessTaskIssuer:
    """Host-owned issuer for already-authorized benchmark process payloads."""

    def __init__(self, authority: _ProcessAuthority) -> None:
        if not isinstance(authority, _ProcessAuthority):
            _fail("authorized benchmark process issuer is invalid")
        self._authority = authority

    def __call__(
        self,
        *,
        argv: tuple[str, ...],
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
        case_count: int = 1,
        artifact_ids: tuple[str, ...] = (),
        termination_grace_seconds: float = 2.0,
    ) -> object:
        return _AuthorizedProcessTaskPlan(
            authority=self._authority,
            argv=argv,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            case_count=case_count,
            artifact_ids=artifact_ids,
            termination_grace_seconds=termination_grace_seconds,
        )


@dataclass(frozen=True, slots=True, repr=False)
class _AuthorizedProcessTaskPlan:
    """Already-authorized direct process invocation for one benchmark task."""

    authority: _ProcessAuthority = field(repr=False, compare=False)
    argv: tuple[str, ...] = field(repr=False)
    cwd: Path = field(repr=False)
    env: Mapping[str, str] = field(default_factory=dict, repr=False)
    timeout_seconds: float = field(default=30.0, repr=False)
    max_output_bytes: int = field(default=64 * 1024, repr=False)
    case_count: int = field(default=1, repr=False)
    artifact_ids: tuple[str, ...] = field(default=(), repr=False)
    termination_grace_seconds: float = field(default=2.0, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.authority, _ProcessAuthority):
            _fail("authorized benchmark process plan is invalid")
        argv = tuple(self.argv)
        if (
            not argv
            or not all(_valid_argument(argument) for argument in argv)
            or _looks_like_shell_command(argv[0])
        ):
            _fail("authorized benchmark process plan is invalid")
        if not isinstance(self.cwd, Path):
            _fail("authorized benchmark process plan is invalid")
        try:
            cwd = self.cwd.resolve(strict=True)
        except OSError:
            _fail("authorized benchmark process plan is invalid")
        if not cwd.is_dir():
            _fail("authorized benchmark process plan is invalid")
        env = _freeze_env(self.env)
        _positive_finite(self.timeout_seconds)
        _positive_finite(self.termination_grace_seconds)
        if (
            type(self.max_output_bytes) is not int
            or self.max_output_bytes < 1
            or self.max_output_bytes > _MAX_OUTPUT_CAP_BYTES
        ):
            _fail("authorized benchmark process plan is invalid")
        if type(self.case_count) is not int or self.case_count < 0:
            _fail("authorized benchmark process plan is invalid")
        artifact_ids = tuple(self.artifact_ids)
        if tuple(sorted(set(artifact_ids))) != artifact_ids or not all(
            _safe_identifier(artifact_id) for artifact_id in artifact_ids
        ):
            _fail("authorized benchmark process plan is invalid")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "env", env)
        object.__setattr__(self, "artifact_ids", artifact_ids)

    def __repr__(self) -> str:
        return "_AuthorizedProcessTaskPlan(<redacted>)"


class AuthorizedProcessTaskExecutor:
    """Execute an already-authorized process payload without selecting authority."""

    @classmethod
    def create_pair(
        cls,
        *,
        poll_interval_seconds: float = 0.05,
    ) -> tuple[Self, AuthorizedProcessTaskIssuer]:
        authority = _ProcessAuthority()
        return (
            cls(
                poll_interval_seconds=poll_interval_seconds,
                _authority=authority,
            ),
            AuthorizedProcessTaskIssuer(authority),
        )

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 0.05,
        _authority: _ProcessAuthority | None = None,
    ) -> None:
        _positive_finite(poll_interval_seconds)
        self._poll_interval_seconds = poll_interval_seconds
        self._authority = _authority or _ProcessAuthority()

    def execute(
        self,
        invocation: BenchmarkTaskInvocation,
        *,
        cancellation: CancellationSignal,
        on_progress: Callable[[BenchmarkProgressEvent], None],
    ) -> BenchmarkTaskResult:
        if not isinstance(invocation, BenchmarkTaskInvocation):
            _fail("benchmark process invocation is invalid")
        payload = invocation.private_payload
        if (
            not isinstance(payload, _AuthorizedProcessTaskPlan)
            or payload.authority is not self._authority
        ):
            _fail("benchmark process invocation is invalid")
        plan = payload
        if cancellation.cancelled:
            return _cancelled_result(invocation.task_id)
        if os.name != "posix":
            _fail("benchmark process execution is unsupported")

        process: subprocess.Popen[bytes] | None = None
        stdout: _BoundedPipeCollector | None = None
        stderr: _BoundedPipeCollector | None = None
        result: BenchmarkTaskResult | None = None
        progress_pending = False
        try:
            process = subprocess.Popen(
                list(plan.argv),
                cwd=plan.cwd,
                env=dict(plan.env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=True,
            )
            if process.stdout is None or process.stderr is None:
                _fail("benchmark process execution failed")
            stdout = _BoundedPipeCollector(
                process.stdout,
                max_bytes=plan.max_output_bytes,
            )
            stderr = _BoundedPipeCollector(
                process.stderr,
                max_bytes=plan.max_output_bytes,
            )
            stdout.start()
            stderr.start()
            status = self._wait_for_exit(
                process,
                plan=plan,
                cancellation=cancellation,
                output_exceeded=lambda: _output_exceeded(stdout, stderr),
            )
            stdout.join()
            stderr.join()
            progress_pending = True
            if status == "cancelled":
                result = _cancelled_result(invocation.task_id)
            elif status == "output-exceeded" or _output_exceeded(stdout, stderr):
                result = _failed_result(invocation.task_id)
            elif process.returncode == 0:
                result = BenchmarkTaskResult(
                    task_id=invocation.task_id,
                    status="completed",
                    case_count=plan.case_count,
                    artifact_ids=plan.artifact_ids,
                )
            else:
                result = _failed_result(invocation.task_id)
        except BenchmarkProcessError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError):
            if process is not None and process.poll() is None:
                _terminate_process_group(process, grace_seconds=0.1)
            return _failed_result(invocation.task_id)
        finally:
            for collector in (stdout, stderr):
                if collector is not None:
                    collector.close()
        if progress_pending:
            on_progress(
                BenchmarkProgressEvent(
                    sequence=1,
                    status="task.process-exited",
                    task_id=invocation.task_id,
                )
            )
        if result is None:
            _fail("benchmark process execution failed")
        return result

    def _wait_for_exit(
        self,
        process: subprocess.Popen[bytes],
        *,
        plan: _AuthorizedProcessTaskPlan,
        cancellation: CancellationSignal,
        output_exceeded: Callable[[], bool],
    ) -> str:
        deadline = time.monotonic() + plan.timeout_seconds
        while process.poll() is None:
            if output_exceeded():
                _terminate_process_group(
                    process,
                    grace_seconds=plan.termination_grace_seconds,
                )
                return "output-exceeded"
            if cancellation.cancelled or time.monotonic() >= deadline:
                _terminate_process_group(
                    process,
                    grace_seconds=plan.termination_grace_seconds,
                )
                return "cancelled"
            remaining = max(0.0, deadline - time.monotonic())
            time.sleep(min(self._poll_interval_seconds, remaining))
        return "exited"


class _BoundedPipeCollector:
    def __init__(self, stream: IO[bytes], *, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self.bytes_seen = 0
        self.exceeded = False
        self._thread = threading.Thread(target=self._drain, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join(timeout=2.0)

    def close(self) -> None:
        try:
            self._stream.close()
        except OSError:
            pass
        self.join()

    def _drain(self) -> None:
        while True:
            try:
                chunk = self._stream.read(4096)
            except OSError:
                return
            if not chunk:
                return
            self.bytes_seen += len(chunk)
            if self.bytes_seen > self._max_bytes:
                self.exceeded = True
                self.bytes_seen = self._max_bytes


def _terminate_process_group(
    process: subprocess.Popen[bytes],
    *,
    grace_seconds: float,
) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        if process.poll() is None:
            process.kill()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
            process.wait()


def _output_exceeded(
    stdout: _BoundedPipeCollector,
    stderr: _BoundedPipeCollector,
) -> bool:
    return stdout.exceeded or stderr.exceeded


def _freeze_env(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        _fail("authorized benchmark process plan is invalid")
    frozen: dict[str, str] = {}
    for key, item in value.items():
        if not _valid_env_key(key) or not _valid_env_value(item):
            _fail("authorized benchmark process plan is invalid")
        frozen[key] = item
    return MappingProxyType(frozen)


def _valid_argument(value: object) -> bool:
    return type(value) is str and value != "" and "\x00" not in value


def _looks_like_shell_command(value: str) -> bool:
    return any(character.isspace() for character in value)


def _valid_env_key(value: object) -> bool:
    if type(value) is not str or value == "" or "\x00" in value:
        return False
    lowered = value.lower()
    return not any(fragment in lowered for fragment in _SECRET_ENV_FRAGMENTS)


def _valid_env_value(value: object) -> bool:
    return type(value) is str and "\x00" not in value


def _positive_finite(value: object) -> None:
    if (
        type(value) is not float
        or not math.isfinite(value)
        or value <= 0
    ):
        _fail("authorized benchmark process plan is invalid")


def _safe_identifier(value: object) -> bool:
    if type(value) is not str or value == "":
        return False
    if value[0] not in "abcdefghijklmnopqrstuvwxyz":
        return False
    if value[-1] in ".-":
        return False
    if any(character not in _IDENTIFIER_CHARS for character in value):
        return False
    return ".." not in value and "--" not in value


def _failed_result(task_id: str) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(task_id=task_id, status="failed", case_count=0)


def _cancelled_result(task_id: str) -> BenchmarkTaskResult:
    return BenchmarkTaskResult(task_id=task_id, status="cancelled", case_count=0)


def _fail(message: str) -> NoReturn:
    raise BenchmarkProcessError(message)


__all__ = (
    "AuthorizedProcessTaskExecutor",
    "AuthorizedProcessTaskIssuer",
    "BenchmarkProcessError",
)
