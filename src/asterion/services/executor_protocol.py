"""Reference validation for the controlled executor JSONL protocol."""

from __future__ import annotations

from collections.abc import Mapping


EXECUTOR_PROTOCOL_VERSION = "dci.executor/v1"
MAX_EXECUTOR_DEADLINE_MS = 86_400_000
MAX_EXECUTOR_OUTPUT_BYTES = 16_777_216


class ExecutorProtocolError(ValueError):
    """Raised when an executor request or response violates protocol v1."""


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ExecutorProtocolError("executor message must be an object")
    return value


def _keys(
    value: Mapping[str, object],
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    missing = required - value.keys()
    unknown = value.keys() - required - (optional or set())
    if missing:
        raise ExecutorProtocolError("executor message has missing fields")
    if unknown:
        raise ExecutorProtocolError("executor message has unknown fields")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutorProtocolError(f"{label} must be a non-empty string")
    return value


def _bounded_integer(value: object, label: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ExecutorProtocolError(f"{label} is outside the protocol limit")
    return value


def validate_message(message: Mapping[str, object]) -> None:
    """Validate one executor request or response envelope."""

    message = _mapping(message)
    if message.get("protocol") != EXECUTOR_PROTOCOL_VERSION:
        raise ExecutorProtocolError("executor protocol is not dci.executor/v1")
    _string(message.get("request_id"), "request_id")
    message_type = _string(message.get("type"), "type")

    if message_type == "execute":
        _keys(
            message,
            {
                "protocol",
                "request_id",
                "type",
                "program_id",
                "arguments",
                "cwd",
                "deadline_ms",
                "max_output_bytes",
            },
        )
        _string(message["program_id"], "program_id")
        arguments = message["arguments"]
        if not isinstance(arguments, list) or any(
            not isinstance(argument, str) for argument in arguments
        ):
            raise ExecutorProtocolError("arguments must be an array of strings")
        _string(message["cwd"], "cwd")
        _bounded_integer(
            message["deadline_ms"], "deadline_ms", MAX_EXECUTOR_DEADLINE_MS
        )
        _bounded_integer(
            message["max_output_bytes"],
            "max_output_bytes",
            MAX_EXECUTOR_OUTPUT_BYTES,
        )
    elif message_type == "cancel":
        _keys(
            message,
            {"protocol", "request_id", "type", "target_request_id"},
        )
        _string(message["target_request_id"], "target_request_id")
    elif message_type == "execution.result":
        _keys(
            message,
            {
                "protocol",
                "request_id",
                "type",
                "status",
                "exit_code",
                "stdout",
                "stderr",
                "stdout_truncated",
                "stderr_truncated",
                "code",
            },
        )
        if message["status"] not in {
            "completed",
            "failed",
            "timed_out",
            "cancelled",
            "denied",
        }:
            raise ExecutorProtocolError("execution result status is not recognized")
        if message["exit_code"] is not None and (
            isinstance(message["exit_code"], bool)
            or not isinstance(message["exit_code"], int)
        ):
            raise ExecutorProtocolError("exit_code must be an integer or null")
        for field in ("stdout", "stderr"):
            if not isinstance(message[field], str):
                raise ExecutorProtocolError(f"{field} must be a string")
        for field in ("stdout_truncated", "stderr_truncated"):
            if not isinstance(message[field], bool):
                raise ExecutorProtocolError(f"{field} must be a boolean")
        if message["code"] is not None:
            _string(message["code"], "code")
    elif message_type == "cancel.acknowledged":
        _keys(
            message,
            {
                "protocol",
                "request_id",
                "type",
                "target_request_id",
                "accepted",
            },
        )
        _string(message["target_request_id"], "target_request_id")
        if not isinstance(message["accepted"], bool):
            raise ExecutorProtocolError("accepted must be a boolean")
    elif message_type == "protocol.error":
        _keys(message, {"protocol", "request_id", "type", "code", "message"})
        _string(message["code"], "code")
        _string(message["message"], "message")
    else:
        raise ExecutorProtocolError("executor message type is not recognized")
