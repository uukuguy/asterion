"""Operator-validated lifecycle for one controlled-executor sidecar."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from asterion.services.controlled_executor import ControlledExecutorError
from asterion.services.controlled_executor_jsonl import TrustedValidationConfig
from asterion.services.controlled_executor_jsonl import ControlledExecutorJsonlClient


@dataclass(frozen=True)
class OperatorExecutorConfig:
    binary_path: Path
    policy_path: Path
    validation_config: TrustedValidationConfig


class ManagedControlledExecutor:
    """Start, expose, and reap one explicit stdio executor subprocess."""

    def __init__(self, config: OperatorExecutorConfig) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> ControlledExecutorJsonlClient:
        try:
            process = await asyncio.create_subprocess_exec(
                str(self._config.binary_path),
                str(self._config.policy_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={},
            )
        except (OSError, ValueError):
            raise ControlledExecutorError("controlled executor failed to start") from None
        self._process = process
        if process.stderr is not None:
            self._stderr_task = asyncio.create_task(_discard_stderr(process.stderr))
        await asyncio.sleep(0)
        if (
            process.returncode is not None
            or process.stdin is None
            or process.stdout is None
            or process.stderr is None
        ):
            await self._shutdown()
            raise ControlledExecutorError("controlled executor is unavailable")
        return ControlledExecutorJsonlClient(
            reader=process.stdout,
            writer=process.stdin,
            config=self._config.validation_config,
        )

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        await self._shutdown()

    async def _shutdown(self) -> None:
        process = self._process
        self._process = None
        stderr_task = self._stderr_task
        self._stderr_task = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task is not None:
            try:
                await asyncio.wait_for(stderr_task, timeout=1)
            except TimeoutError:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)


async def _discard_stderr(stream: asyncio.StreamReader) -> None:
    """Drain diagnostics without retaining unbounded child output."""

    while await stream.read(4096):
        pass


def load_operator_executor_config(
    binary: str | Path, policy: str | Path, validation: str | Path
) -> OperatorExecutorConfig:
    """Load the closed explicit operator configuration without echoing values."""

    binary_path = _regular_file(binary)
    policy_path = _regular_file(policy)
    validation_path = _regular_file(validation)
    try:
        policy_value = json.loads(policy_path.read_text())
        validation_value = json.loads(validation_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ControlledExecutorError("controlled executor configuration is invalid") from None
    if not isinstance(policy_value, Mapping) or not isinstance(validation_value, Mapping):
        raise ControlledExecutorError("controlled executor configuration is invalid")
    required = {
        "program_id",
        "argument_prefix",
        "cwd",
        "deadline_ms",
        "max_output_bytes",
    }
    if set(validation_value) != required or not isinstance(
        validation_value["argument_prefix"], list
    ):
        raise ControlledExecutorError("controlled executor configuration is invalid")
    try:
        validation_config = TrustedValidationConfig(
            program_id=validation_value["program_id"],
            argument_prefix=tuple(validation_value["argument_prefix"]),
            cwd=validation_value["cwd"],
            deadline_ms=validation_value["deadline_ms"],
            max_output_bytes=validation_value["max_output_bytes"],
        )
    except (ControlledExecutorError, TypeError):
        raise ControlledExecutorError("controlled executor configuration is invalid") from None
    return OperatorExecutorConfig(
        binary_path=binary_path,
        policy_path=policy_path,
        validation_config=validation_config,
    )


def _regular_file(value: str | Path) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ControlledExecutorError("controlled executor configuration is unsafe")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise ControlledExecutorError("controlled executor configuration is unavailable") from None
    if not resolved.is_file():
        raise ControlledExecutorError("controlled executor configuration is invalid")
    return resolved
