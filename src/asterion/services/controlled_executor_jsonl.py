"""JSONL client for an already running controlled-executor sidecar."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import monotonic

from asterion.services.controlled_executor import (
    ControlledExecutionRequest,
    ControlledExecutionResult,
    ControlledExecutorError,
)
from asterion.services.executor_protocol import (
    EXECUTOR_PROTOCOL_VERSION,
    ExecutorProtocolError,
    validate_message,
)


@dataclass(frozen=True)
class TrustedValidationConfig:
    program_id: str
    argument_prefix: tuple[str, ...]
    cwd: str
    deadline_ms: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.argument_prefix, tuple):
            raise ControlledExecutorError("trusted validation configuration is invalid")
        try:
            validate_message(
                {
                    "protocol": EXECUTOR_PROTOCOL_VERSION,
                    "request_id": "validation",
                    "type": "execute",
                    "program_id": self.program_id,
                    "arguments": list(self.argument_prefix),
                    "cwd": self.cwd,
                    "deadline_ms": self.deadline_ms,
                    "max_output_bytes": self.max_output_bytes,
                }
            )
        except (ExecutorProtocolError, TypeError, ValueError):
            raise ControlledExecutorError(
                "trusted validation configuration is invalid"
            ) from None


class ControlledExecutorJsonlClient:
    """Correlate requests over caller-owned JSONL streams without process startup."""

    def __init__(self, *, reader: asyncio.StreamReader, writer: object, config: TrustedValidationConfig) -> None:
        self._reader = reader
        self._writer = writer
        self._config = config
        self._counter = 0
        self._cancel_counter = 0
        self._lock = asyncio.Lock()

    async def execute(self, request: ControlledExecutionRequest, *, signal=None) -> ControlledExecutionResult:
        if not isinstance(request, ControlledExecutionRequest):
            raise ControlledExecutorError("controlled execution request is invalid")
        if signal is not None and signal.cancelled:
            return _cancelled_result()
        async with self._lock:
            self._counter += 1
            request_id = f"asterion-exec-{self._counter}"
            message = {
                "protocol": EXECUTOR_PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "execute",
                "program_id": self._config.program_id,
                "arguments": [*self._config.argument_prefix, request.target],
                "cwd": self._config.cwd,
                "deadline_ms": self._config.deadline_ms,
                "max_output_bytes": self._config.max_output_bytes,
            }
            try:
                validate_message(message)
                self._writer.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
                await self._writer.drain()
                started = monotonic()
                cancellation_sent = False
                cancel_request_id = ""
                while True:
                    if signal is not None and signal.cancelled and not cancellation_sent:
                        self._cancel_counter += 1
                        cancel_request_id = f"asterion-cancel-{self._cancel_counter}"
                        cancel = {
                            "protocol": EXECUTOR_PROTOCOL_VERSION,
                            "request_id": cancel_request_id,
                            "type": "cancel",
                            "target_request_id": request_id,
                        }
                        validate_message(cancel)
                        self._writer.write(
                            (json.dumps(cancel, separators=(",", ":")) + "\n").encode()
                        )
                        await self._writer.drain()
                        cancellation_sent = True
                    try:
                        raw = await asyncio.wait_for(self._reader.readline(), timeout=0.05)
                    except TimeoutError:
                        continue
                    if not raw:
                        raise ValueError("executor stream ended")
                    response = json.loads(raw)
                    validate_message(response)
                    if response.get("type") == "cancel.acknowledged":
                        if (
                            not cancellation_sent
                            or response.get("request_id") != cancel_request_id
                            or response.get("target_request_id") != request_id
                        ):
                            raise ValueError("executor cancellation response mismatch")
                        continue
                    if (
                        response.get("request_id") != request_id
                        or response.get("type") != "execution.result"
                    ):
                        raise ValueError("executor response mismatch")
                    break
            except Exception:
                raise ControlledExecutorError("controlled executor transport failed") from None
            return _result(response, duration_ms=max(0, int((monotonic() - started) * 1000)))


def _result(response: dict[str, object], *, duration_ms: int) -> ControlledExecutionResult:
    status = response["status"]
    mapped = {
        "completed": "succeeded",
        "failed": "failed",
        "timed_out": "failed",
        "cancelled": "cancelled",
        "denied": "rejected",
    }[status]
    return ControlledExecutionResult(
        status=mapped,
        exit_code=response["exit_code"],
        stdout_bytes=len(response["stdout"].encode()),
        stderr_bytes=len(response["stderr"].encode()),
        stdout_truncated=response["stdout_truncated"],
        stderr_truncated=response["stderr_truncated"],
        duration_ms=duration_ms,
        failure_class=None if mapped == "succeeded" else f"execution-{status}",
    )


def _cancelled_result() -> ControlledExecutionResult:
    return ControlledExecutionResult(
        status="cancelled",
        exit_code=None,
        stdout_bytes=0,
        stderr_bytes=0,
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=0,
        failure_class="execution-cancelled",
    )
