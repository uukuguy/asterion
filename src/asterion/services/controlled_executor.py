"""Typed host-service boundary for controlled validation execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from asterion.runtime.host import CancellationSignal


class ControlledExecutorError(ValueError):
    """Raised when a controlled-executor value or operation is invalid."""


@dataclass(frozen=True)
class ControlledExecutionRequest:
    target: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) or not self.target or "\x00" in self.target:
            raise ControlledExecutorError("controlled execution target is invalid")
        path = PurePosixPath(self.target)
        if path.is_absolute() or ".." in path.parts or self.target.strip() != self.target:
            raise ControlledExecutorError("controlled execution target is invalid")


@dataclass(frozen=True)
class ControlledExecutionResult:
    status: str
    exit_code: int | None
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    failure_class: str | None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "rejected", "cancelled"}:
            raise ControlledExecutorError("controlled execution result is invalid")
        if self.status == "succeeded" and (
            type(self.exit_code) is not int or self.exit_code < 0
        ):
            raise ControlledExecutorError("controlled execution result is invalid")
        if self.status in {"rejected", "cancelled"} and self.exit_code is not None:
            raise ControlledExecutorError("controlled execution result is invalid")
        if self.status == "failed" and self.exit_code is not None and (
            type(self.exit_code) is not int or self.exit_code < 0
        ):
            raise ControlledExecutorError("controlled execution result is invalid")
        for value in (self.stdout_bytes, self.stderr_bytes, self.duration_ms):
            if type(value) is not int or value < 0:
                raise ControlledExecutorError("controlled execution result is invalid")
        if not isinstance(self.stdout_truncated, bool) or not isinstance(
            self.stderr_truncated, bool
        ):
            raise ControlledExecutorError("controlled execution result is invalid")
        if self.failure_class is not None and (
            not isinstance(self.failure_class, str) or not self.failure_class
        ):
            raise ControlledExecutorError("controlled execution result is invalid")


class ControlledExecutorService(Protocol):
    async def execute(
        self,
        request: ControlledExecutionRequest,
        *,
        signal: CancellationSignal | None = None,
    ) -> ControlledExecutionResult: ...
