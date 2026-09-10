"""Domain-neutral process and session lifecycle for Pi JSONL-RPC."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import math
import os
import queue
import signal as process_signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from io import UnsupportedOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol


_MAX_STDOUT_LINE_BYTES = 1024 * 1024
_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_MAX_COMPACT_STDOUT_BYTES = 64 * 1024 * 1024
_MAX_RAW_STDOUT_BYTES = 2 * 1024 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_MAX_EVENT_COUNT = 65536
_MAX_FINAL_TEXT_BYTES = 1024 * 1024
_GRACEFUL_EXIT_SECONDS = 0.1
_PROCESS_EXIT_SECONDS = 0.25
_PIPE_DRAIN_SECONDS = 0.25
_POLL_SECONDS = 0.05
_PROMPT_DRIVER_EXIT_SECONDS = 1.0
_STDOUT_EOF = object()


def normalize_pi_usage(payload: Mapping[str, object]) -> Mapping[str, int] | None:
    """Translate one native Pi assistant usage payload to the runtime contract."""

    message = payload.get("message")
    if not isinstance(message, Mapping) or message.get("role") != "assistant":
        return None
    usage = message.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        raise ValueError("Pi usage event is invalid")
    input_tokens = usage.get("input")
    output_tokens = usage.get("output")
    if (
        isinstance(input_tokens, bool)
        or type(input_tokens) is not int
        or input_tokens < 0
        or isinstance(output_tokens, bool)
        or type(output_tokens) is not int
        or output_tokens < 0
    ):
        raise ValueError("Pi usage event is invalid")
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _compact_rpc_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = payload.get("type")
    if event_type == "response":
        return {
            key: payload[key] for key in ("type", "id", "success") if key in payload
        }
    if event_type == "message_update":
        update = payload.get("assistantMessageEvent")
        compact_update: dict[str, object] = {}
        if isinstance(update, Mapping):
            if "type" in update:
                compact_update["type"] = update["type"]
            if update.get("type") == "text_delta" and "delta" in update:
                compact_update["delta"] = ""
        return {"type": event_type, "assistantMessageEvent": compact_update}
    if event_type == "message_end":
        message = payload.get("message")
        compact_message: dict[str, object] = {}
        if isinstance(message, Mapping):
            if "role" in message:
                compact_message["role"] = message["role"]
            usage = message.get("usage")
            if isinstance(usage, Mapping):
                compact_message["usage"] = {
                    key: usage[key] for key in ("input", "output") if key in usage
                }
        return {"type": event_type, "message": compact_message}
    if event_type == "tool_execution_start":
        return {
            key: payload[key]
            for key in ("type", "toolCallId", "toolName", "args")
            if key in payload
        }
    if event_type == "tool_execution_end":
        return {
            key: payload[key]
            for key in ("type", "toolCallId", "isError", "effect")
            if key in payload
        }
    if event_type in {
        "agent_start",
        "agent_end",
        "message_start",
        "turn_start",
        "turn_end",
    }:
        return {"type": event_type}
    return payload


class CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool: ...


def _freeze(value: object, active: set[int] | None = None) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Pi RPC event payload is invalid")
        return value
    if active is None:
        active = set()
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("Pi RPC event payload is invalid")
        identity = id(value)
        if identity in active:
            raise ValueError("Pi RPC event payload is invalid")
        active.add(identity)
        try:
            return MappingProxyType(
                {key: _freeze(item, active) for key, item in value.items()}
            )
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise ValueError("Pi RPC event payload is invalid")
        active.add(identity)
        try:
            return tuple(_freeze(item, active) for item in value)
        finally:
            active.remove(identity)
    raise ValueError("Pi RPC event payload is invalid")


class PiRpcDirective(Enum):
    CONTINUE = "continue"
    ABORT = "abort"
    COMPLETE = "complete"


class PiRpcPromptControl:
    """Common deadline, cancellation, abort, and bounded-wait controller."""

    def __init__(
        self,
        session: PiRpcSession,
        *,
        timeout_seconds: float | None,
        signal: CancellationSignal | threading.Event | None,
        absolute_deadline: float | None = None,
    ) -> None:
        self._session = session
        self._timeout_seconds = timeout_seconds
        self._signal = signal
        self._deadline = absolute_deadline
        if (
            self._deadline is None
            and timeout_seconds is not None
            and timeout_seconds > 0
        ):
            self._deadline = time.monotonic() + timeout_seconds
        self._abort_sent = False

    def remaining_seconds(self) -> float | None:
        return (
            None
            if self._deadline is None
            else max(0.0, self._deadline - time.monotonic())
        )

    def checkpoint(self) -> None:
        if self._session._is_cancelled(self._signal):
            self.abort()
            raise RuntimeError("RPC prompt was cancelled")
        if self.remaining_seconds() == 0:
            self.abort()
            raise RuntimeError(
                f"RPC prompt timed out after {self._timeout_seconds:g} seconds"
            )

    def check_before_prompt(self) -> None:
        if self._session._is_cancelled(self._signal):
            raise RuntimeError("RPC prompt was cancelled")
        if self.remaining_seconds() == 0:
            raise RuntimeError(
                f"RPC prompt timed out after {self._timeout_seconds:g} seconds"
            )

    def poll_seconds(self) -> float | None:
        remaining = self.remaining_seconds()
        if self._signal is None:
            return remaining
        return _POLL_SECONDS if remaining is None else min(_POLL_SECONDS, remaining)

    def read_event(self) -> dict[str, Any]:
        """Read one event under this prompt's deadline and cancellation policy."""

        while True:
            self.checkpoint()
            try:
                return self._session.read_json_line(timeout_seconds=self.poll_seconds())
            except TimeoutError:
                self.checkpoint()

    def request(
        self,
        request_type: str,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Issue a nested RPC request without creating a second lifecycle."""

        if type(request_type) is not str or not request_type:
            raise ValueError("Pi RPC request type is invalid")
        request_id = self._session.next_id()
        self._session.send({"id": request_id, "type": request_type})
        while True:
            event = self.read_event()
            if event.get("type") == "response":
                if event.get("id") != request_id:
                    raise RuntimeError("Pi RPC response did not match the request")
                return event
            if on_event is not None:
                on_event(event)

    def abort(self) -> None:
        if not self._abort_sent:
            self._session.abort()
            self._abort_sent = True

    def sleep(self, seconds: float) -> None:
        end = time.monotonic() + max(0.0, seconds)
        while True:
            self.checkpoint()
            delay = end - time.monotonic()
            if delay <= 0:
                return
            remaining = self.remaining_seconds()
            time.sleep(
                min(
                    _POLL_SECONDS,
                    delay,
                    delay if remaining is None else remaining,
                )
            )


@dataclass(slots=True)
class _ProcessState:
    process: subprocess.Popen[bytes]
    stdout_queue: queue.Queue[object]
    stderr: bytearray
    compact_final_text: bytearray = field(default_factory=bytearray)
    output_error: RuntimeError | None = None
    stdout_thread: threading.Thread | None = None
    stderr_thread: threading.Thread | None = None
    stdout_started: bool = False
    stderr_started: bool = False


@dataclass(frozen=True, slots=True)
class PiRpcConfig:
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    deadline_seconds: float
    inherited_fds: tuple[int, ...] = ()
    compact_events: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.command) is not tuple
            or not self.command
            or any(
                type(part) is not str or not part or "\x00" in part
                for part in self.command
            )
        ):
            raise ValueError("Pi RPC command is invalid")
        if not isinstance(self.cwd, Path):
            raise ValueError("Pi RPC cwd is invalid")
        try:
            environment = dict(self.environment)
        except (TypeError, ValueError):
            raise ValueError("Pi RPC environment is invalid") from None
        if any(
            type(key) is not str or type(value) is not str
            for key, value in environment.items()
        ):
            raise ValueError("Pi RPC environment is invalid")
        if (
            isinstance(self.deadline_seconds, bool)
            or not isinstance(self.deadline_seconds, (int, float))
            or not math.isfinite(self.deadline_seconds)
            or self.deadline_seconds <= 0
        ):
            raise ValueError("Pi RPC deadline is invalid")
        if type(self.inherited_fds) is not tuple or any(
            type(fd) is not int or fd < 0 for fd in self.inherited_fds
        ):
            raise ValueError("Pi RPC inherited file descriptors are invalid")
        if type(self.compact_events) is not bool:
            raise ValueError("Pi RPC event projection is invalid")
        object.__setattr__(self, "command", tuple(self.command))
        object.__setattr__(self, "cwd", Path(self.cwd))
        object.__setattr__(self, "environment", MappingProxyType(environment))
        object.__setattr__(self, "deadline_seconds", float(self.deadline_seconds))
        object.__setattr__(
            self, "inherited_fds", tuple(sorted(set(self.inherited_fds)))
        )


@dataclass(frozen=True, slots=True)
class PiRpcEvent:
    sequence: int
    type: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("Pi RPC event sequence is invalid")
        if type(self.type) is not str or not self.type:
            raise ValueError("Pi RPC event type is invalid")
        if not isinstance(self.payload, Mapping):
            raise ValueError("Pi RPC event payload is invalid")
        object.__setattr__(self, "payload", _freeze(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class PiRpcResult:
    final_text: str
    events: tuple[PiRpcEvent, ...]
    stderr: bytes
    request_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.final_text) is not str:
            raise ValueError("Pi RPC final text is invalid")
        if type(self.events) is not tuple or any(
            type(event) is not PiRpcEvent for event in self.events
        ):
            raise ValueError("Pi RPC result events are invalid")
        if type(self.stderr) is not bytes:
            raise ValueError("Pi RPC stderr is invalid")
        if self.request_id is not None and (
            type(self.request_id) is not str or not self.request_id
        ):
            raise ValueError("Pi RPC request id is invalid")


@dataclass(frozen=True, slots=True)
class PiRpcCompactResult:
    request_id: str
    rpc_type: Literal["compact"]
    events: tuple[PiRpcEvent, ...]
    stderr: bytes
    outcome: Literal["completed", "aborted"] = "completed"

    def __post_init__(self) -> None:
        if type(self.request_id) is not str or not self.request_id:
            raise ValueError("Pi RPC request id is invalid")
        if self.rpc_type != "compact":
            raise ValueError("Pi RPC compact result type is invalid")
        if type(self.events) is not tuple or any(
            type(event) is not PiRpcEvent for event in self.events
        ):
            raise ValueError("Pi RPC compact result events are invalid")
        if type(self.stderr) is not bytes:
            raise ValueError("Pi RPC stderr is invalid")
        if self.outcome not in {"completed", "aborted"}:
            raise ValueError("Pi RPC compact outcome is invalid")


def validate_pi_compact_result(result: PiRpcCompactResult) -> None:
    """Validate pinned manual-compaction events without interpreting error text."""
    try:
        if type(result) is not PiRpcCompactResult or len(result.events) != 3:
            raise ValueError
        start, end, response = result.events
        if (
            tuple(event.type for event in result.events)
            != ("compaction_start", "compaction_end", "response")
            or end.sequence != start.sequence + 1
            or response.sequence != end.sequence + 1
            or start.payload.get("reason") != "manual"
            or end.payload.get("reason") != "manual"
            or set(start.payload) - {"reason", "customInstructions"}
            or start.payload.get("customInstructions") is not None
            or end.payload.get("customInstructions") is not None
            or end.payload.get("willRetry") is not False
            or response.payload.get("id") != result.request_id
            or response.payload.get("command") != "compact"
        ):
            raise ValueError
        if result.outcome == "completed":
            body = end.payload.get("result")
            if (
                set(end.payload)
                - {"reason", "result", "aborted", "willRetry", "customInstructions"}
                or end.payload.get("aborted") is not False
                or not isinstance(body, Mapping)
                or set(body)
                - {"summary", "firstKeptEntryId", "tokensBefore", "details"}
                or type(body.get("summary")) is not str
                or not body["summary"]
                or type(body.get("firstKeptEntryId")) is not str
                or not body["firstKeptEntryId"]
                or type(body.get("tokensBefore")) is not int
                or body["tokensBefore"] < 0
                or response.payload.get("success") is not True
                or set(response.payload) != {"id", "command", "success", "data"}
                or response.payload.get("data") != body
            ):
                raise ValueError
        elif (
            result.outcome != "aborted"
            or set(end.payload)
            - {
                "reason",
                "result",
                "aborted",
                "willRetry",
                "customInstructions",
                "errorSeverity",
                "errorMessage",
            }
            or end.payload.get("aborted") is not True
            or end.payload.get("result") is not None
            or end.payload.get("errorMessage") is not None
            or end.payload.get("errorSeverity") != "error"
            or response.payload.get("success") is not False
            or set(response.payload) != {"id", "command", "success", "error"}
            or type(response.payload.get("error")) is not str
        ):
            raise ValueError
    except BaseException:
        raise ValueError("Pi RPC compact terminal is invalid") from None


class PiRpcSession:
    """Own one explicitly configured Pi JSONL-RPC child process."""

    def __init__(
        self,
        config: PiRpcConfig,
        *,
        _popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        _thread_factory: Callable[..., threading.Thread] = threading.Thread,
    ) -> None:
        if type(config) is not PiRpcConfig:
            raise TypeError("Pi RPC config is invalid")
        self.config = config
        self._popen = _popen
        self._thread_factory = _thread_factory
        self._state: _ProcessState | None = None
        self._last_stderr = b""
        self._last_failure: str | None = None
        self._request_id = 0
        self._run_active = False
        self._run_owner: asyncio.Task[object] | None = None
        self._command_lock = asyncio.Lock()
        self._lifecycle_open = False
        self._lifecycle_poisoned = False
        self._session_deadline: float | None = None
        self._event_sequence = 0
        self._lifecycle_identity: object | None = None
        self._pending_compact_abort: PiRpcCompactResult | None = None

    def validate_lifecycle(self, *, opened: bool) -> object | None:
        """Return an opaque live-child identity after a nonmutating health check."""
        if (
            type(opened) is not bool
            or self._command_lock.locked()
            or self._run_active
            or self._run_owner is not None
        ):
            raise RuntimeError("Pi RPC lifecycle is unavailable")
        state = self._state
        if opened:
            if (
                not self._lifecycle_open
                or self._lifecycle_poisoned
                or state is None
                or state.output_error is not None
                or state.process.poll() is not None
                or self._session_deadline is None
                or self._session_deadline <= time.monotonic()
                or self._lifecycle_identity is None
            ):
                raise RuntimeError("Pi RPC lifecycle is unavailable")
            return self._lifecycle_identity
        if self._lifecycle_open or self._lifecycle_poisoned or state is not None:
            raise RuntimeError("Pi RPC lifecycle is unavailable")
        return None

    def settle_rejected_compact(self, result: PiRpcCompactResult) -> None:
        """A trusted owner confirms its independent rejection witness.

        An abort alone does not prove no mutation. Only the exact pending typed
        terminal can be settled, and the caller must have rejected its matching
        compaction proposal before permitting any model/context mutation.
        """
        if (
            type(result) is not PiRpcCompactResult
            or result is not self._pending_compact_abort
            or result.outcome != "aborted"
            or self._command_lock.locked()
            or not self._lifecycle_open
            or not self._lifecycle_poisoned
            or self._state is None
            or self._state.output_error is not None
            or self._state.process.poll() is not None
            or result.events[-1].sequence != self._event_sequence
        ):
            raise RuntimeError("Pi RPC compact settlement is invalid")
        validate_pi_compact_result(result)
        self._pending_compact_abort = None
        self._lifecycle_poisoned = False

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return None if self._state is None else self._state.process

    @property
    def stderr(self) -> bytes:
        return self._last_stderr if self._state is None else bytes(self._state.stderr)

    @property
    def last_failure(self) -> str | None:
        return self._last_failure

    def next_id(self) -> str:
        self._request_id += 1
        return f"py-{self._request_id}"

    def start(self) -> None:
        if self._state is not None:
            raise RuntimeError("RPC session already started")
        self._last_stderr = b""
        try:
            process = self._popen(
                list(self.config.command),
                cwd=self.config.cwd,
                env=dict(self.config.environment),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=self.config.inherited_fds,
                start_new_session=os.name != "nt",
            )
            state = _ProcessState(process, queue.Queue(), bytearray())
            self._state = state
            state.stdout_thread = self._thread_factory(
                target=self._drain_stdout, args=(state,), daemon=True
            )
            state.stdout_thread.start()
            state.stdout_started = True
            state.stderr_thread = self._thread_factory(
                target=self._drain_stderr, args=(state,), daemon=True
            )
            state.stderr_thread.start()
            state.stderr_started = True
        except BaseException:
            self.stop()
            raise

    @staticmethod
    def _fail_output(state: _ProcessState, message: str) -> None:
        error = RuntimeError(message)
        state.output_error = error
        state.stdout_queue.put(error)

    def _drain_stdout(self, state: _ProcessState) -> None:
        process = state.process
        assert process.stdout is not None
        raw_bytes = 0
        total_bytes = 0
        event_count = 0
        try:
            for raw in process.stdout:
                raw_bytes += len(raw)
                if len(raw) > _MAX_STDOUT_LINE_BYTES:
                    self._fail_output(state, "Pi RPC output limit exceeded (line)")
                    return
                if raw_bytes > _MAX_RAW_STDOUT_BYTES:
                    self._fail_output(state, "Pi RPC output limit exceeded (raw total)")
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._fail_output(state, "Pi RPC emitted invalid JSONL")
                    return
                if not isinstance(payload, dict):
                    self._fail_output(state, "Pi RPC emitted a non-object JSON value")
                    return
                if (
                    self.config.compact_events
                    and payload.get("type") == "message_update"
                ):
                    update = payload.get("assistantMessageEvent")
                    if (
                        isinstance(update, Mapping)
                        and update.get("type") == "text_delta"
                        and isinstance(update.get("delta"), str)
                    ):
                        encoded = update["delta"].encode("utf-8")
                        remaining = _MAX_FINAL_TEXT_BYTES - len(
                            state.compact_final_text
                        )
                        if remaining > 0:
                            state.compact_final_text.extend(encoded[:remaining])
                    continue
                event_count += 1
                if event_count > _MAX_EVENT_COUNT:
                    self._fail_output(state, "Pi RPC output limit exceeded (events)")
                    return
                if self.config.compact_events:
                    payload = _compact_rpc_event(payload)
                total_bytes += len(
                    json.dumps(payload, separators=(",", ":")).encode("utf-8")
                )
                projected_limit = (
                    _MAX_COMPACT_STDOUT_BYTES
                    if self.config.compact_events
                    else _MAX_STDOUT_BYTES
                )
                if total_bytes > projected_limit:
                    self._fail_output(
                        state, "Pi RPC output limit exceeded (projected total)"
                    )
                    return
                state.stdout_queue.put(payload)
        except (OSError, ValueError):
            pass
        finally:
            state.stdout_queue.put(_STDOUT_EOF)

    def _drain_stderr(self, state: _ProcessState) -> None:
        process = state.process
        assert process.stderr is not None
        try:
            for raw in process.stderr:
                remaining = _MAX_STDERR_BYTES - len(state.stderr)
                if remaining > 0:
                    state.stderr.extend(raw[:remaining])
                if len(raw) > remaining:
                    self._fail_output(state, "Pi RPC output limit exceeded (stderr)")
                    return
        except (OSError, ValueError):
            pass

    def send(self, payload: Mapping[str, object]) -> None:
        state = self._state
        process = None if state is None else state.process
        if process is None or process.stdin is None:
            raise RuntimeError("RPC session is not running")
        encoded = (json.dumps(dict(payload), separators=(",", ":")) + "\n").encode()
        process.stdin.write(encoded)
        process.stdin.flush()

    def read_json_line(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        state = self._state
        if state is None:
            raise RuntimeError("RPC session is not running")
        try:
            item = state.stdout_queue.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise TimeoutError("Timed out waiting for an RPC event") from error
        if item is _STDOUT_EOF:
            if state.output_error is not None:
                raise state.output_error
            raise RuntimeError("Pi RPC process exited unexpectedly")
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, dict):
            raise RuntimeError("Pi RPC queue returned an invalid event")
        return item

    def drive_prompt(
        self,
        message: str,
        *,
        timeout_seconds: float | None,
        signal: CancellationSignal | threading.Event | None,
        on_event: Callable[[dict[str, Any], PiRpcPromptControl], PiRpcDirective],
        request_id: str | None = None,
        on_request_written: Callable[[], None] | None = None,
        absolute_deadline: float | None = None,
    ) -> float | None:
        """Drive one prompt exchange while the caller interprets Pi events."""

        if type(message) is not str:
            raise ValueError("Pi RPC prompt is invalid")
        control = PiRpcPromptControl(
            self,
            timeout_seconds=timeout_seconds,
            signal=signal,
            absolute_deadline=absolute_deadline,
        )
        control.check_before_prompt()
        request_id = self.next_id() if request_id is None else request_id
        if on_request_written is not None:
            on_request_written()
        self.send({"id": request_id, "type": "prompt", "message": message})
        acknowledged = False
        while True:
            event = control.read_event()
            directive = on_event(event, control)
            if type(directive) is not PiRpcDirective:
                raise RuntimeError("Pi RPC prompt directive is invalid")
            if event.get("type") == "response":
                if event.get("id") != request_id:
                    raise RuntimeError("Pi RPC response did not match the prompt")
                if acknowledged or event.get("success") is not True:
                    raise RuntimeError("RPC prompt failed")
                acknowledged = True
            if directive is PiRpcDirective.ABORT:
                control.abort()
                continue
            if directive is PiRpcDirective.COMPLETE:
                if not acknowledged:
                    event_type = event.get("type", "terminal event")
                    raise RuntimeError(
                        f"Received {event_type} before prompt acknowledgement"
                    )
                return control.remaining_seconds()

    def abort(self) -> None:
        """Send one literal abort request when the process is still writable."""

        try:
            self.send({"id": self.next_id(), "type": "abort"})
        except (BrokenPipeError, OSError, RuntimeError):
            pass

    @staticmethod
    def _is_cancelled(
        signal: CancellationSignal | threading.Event | None,
    ) -> bool:
        if signal is None:
            return False
        if isinstance(signal, threading.Event):
            return signal.is_set()
        return signal.cancelled

    def stop(self) -> None:
        state = self._state
        if state is None:
            return
        process = state.process
        failure: BaseException | None = None
        try:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                try:
                    process.wait(timeout=_GRACEFUL_EXIT_SECONDS)
                except subprocess.TimeoutExpired:
                    self._signal_process(process, process_signal.SIGTERM)
                    try:
                        process.wait(timeout=_PROCESS_EXIT_SECONDS)
                    except subprocess.TimeoutExpired:
                        self._signal_process(process, process_signal.SIGKILL)
                        try:
                            process.wait(timeout=_PROCESS_EXIT_SECONDS)
                        except subprocess.TimeoutExpired as error:
                            failure = error
        finally:
            threads = tuple(
                thread
                for thread, started in (
                    (state.stdout_thread, state.stdout_started),
                    (state.stderr_thread, state.stderr_started),
                )
                if thread is not None and started
            )
            for thread in threads:
                thread.join(timeout=_PIPE_DRAIN_SECONDS)
            alive = tuple(thread for thread in threads if thread.is_alive())
            if alive:
                self._signal_process(process, process_signal.SIGKILL)
                self._close_pipe_descriptors(process)
                for thread in alive:
                    thread.join(timeout=_PIPE_DRAIN_SECONDS)
                alive = tuple(thread for thread in alive if thread.is_alive())
            if not alive:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass
                self._last_stderr = bytes(state.stderr)
                if failure is None:
                    self._state = None
            elif failure is None:
                failure = RuntimeError("Pi RPC pipe cleanup timed out")
        if failure is not None:
            raise RuntimeError("Pi RPC process cleanup timed out") from failure

    @staticmethod
    def _signal_process(process: subprocess.Popen[bytes], signal_number: int) -> None:
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal_number)
            elif signal_number == process_signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except (AttributeError, OSError):
            pass

    @staticmethod
    def _close_pipe_descriptors(process: subprocess.Popen[bytes]) -> None:
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                descriptor = stream.fileno()
            except (OSError, UnsupportedOperation, ValueError):
                continue
            try:
                os.close(descriptor)
            except OSError:
                pass

    def _remaining_session_seconds(self, operation: str) -> float:
        deadline = self._session_deadline
        if deadline is None:
            raise RuntimeError("Pi RPC session is not open")
        remaining = max(0.0, deadline - time.monotonic())
        if remaining == 0:
            raise RuntimeError(
                f"RPC {operation} timed out after "
                f"{self.config.deadline_seconds:g} seconds"
            )
        return remaining

    def _check_command_ready(self, operation: str, signal: CancellationSignal) -> float:
        if not self._lifecycle_open or self.process is None:
            raise RuntimeError("Pi RPC session is not open")
        if self._lifecycle_poisoned:
            raise RuntimeError("Pi RPC session is poisoned; close is required")
        state = self._state
        if state is not None and state.output_error is not None:
            self._lifecycle_poisoned = True
            raise state.output_error
        if signal.cancelled:
            raise RuntimeError(f"RPC {operation} was cancelled before start")
        return self._remaining_session_seconds(operation)

    def _check_run_ownership(self) -> None:
        if self._run_active and self._run_owner is not asyncio.current_task():
            raise RuntimeError("Pi RPC session already has an active command")

    def _emit_event(
        self,
        raw: dict[str, Any],
        events: list[PiRpcEvent],
        on_event: Callable[[PiRpcEvent], None],
    ) -> PiRpcEvent:
        event_type = raw.get("type")
        if type(event_type) is not str or not event_type:
            raise RuntimeError("Pi RPC event type is invalid")
        self._event_sequence += 1
        event = PiRpcEvent(
            sequence=self._event_sequence,
            type=event_type,
            payload={key: value for key, value in raw.items() if key != "type"},
        )
        events.append(event)
        on_event(event)
        return event

    async def _await_driver(
        self,
        driver_task: asyncio.Task[object],
        *,
        local_cancel: threading.Event,
        request_written: threading.Event,
    ) -> object:
        try:
            await asyncio.wait((driver_task,))
            return driver_task.result()
        except asyncio.CancelledError:
            local_cancel.set()
            self._lifecycle_poisoned = True
            cleanup_deadline = (
                asyncio.get_running_loop().time() + _PROMPT_DRIVER_EXIT_SECONDS
            )
            while not driver_task.done():
                remaining = cleanup_deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise RuntimeError(
                        "Pi RPC prompt driver cleanup timed out"
                    ) from None
                try:
                    await asyncio.wait((driver_task,), timeout=remaining)
                except asyncio.CancelledError:
                    continue
            try:
                driver_task.result()
            except BaseException:
                pass
            state = self._state
            self._lifecycle_poisoned = (
                request_written.is_set()
                or not self._lifecycle_open
                or state is None
                or state.output_error is not None
                or state.process.poll() is not None
            )
            raise asyncio.CancelledError
        except BaseException as error:
            if request_written.is_set():
                self._lifecycle_poisoned = True
            self._last_failure = str(error)
            raise

    async def open(self, *, signal: CancellationSignal) -> None:
        """Start one reusable child and capture its absolute deadline."""

        self._check_run_ownership()
        if signal.cancelled:
            raise RuntimeError("Pi RPC session was cancelled before start")
        if self._command_lock.locked():
            raise RuntimeError("Pi RPC session already has an active command")
        async with self._command_lock:
            if self._lifecycle_open or self.process is not None:
                raise RuntimeError("Pi RPC session already has an active run")
            self._last_failure = None
            self._request_id = 0
            self._event_sequence = 0
            self._lifecycle_poisoned = False
            self._session_deadline = time.monotonic() + self.config.deadline_seconds
            try:
                self.start()
            except BaseException:
                self._session_deadline = None
                raise
            self._lifecycle_open = True
            self._lifecycle_identity = object()
            self._pending_compact_abort = None

    async def prompt(
        self,
        prompt: str,
        *,
        signal: CancellationSignal,
        on_event: Callable[[PiRpcEvent], None],
    ) -> PiRpcResult:
        """Run one prompt on the currently open child."""

        self._check_run_ownership()
        if type(prompt) is not str:
            raise ValueError("Pi RPC prompt is invalid")
        if self._command_lock.locked():
            raise RuntimeError("Pi RPC session already has an active command")
        async with self._command_lock:
            self._check_command_ready("prompt", signal)
            absolute_deadline = self._session_deadline
            assert absolute_deadline is not None
            events: list[PiRpcEvent] = []
            text_parts: list[str] = []
            text_bytes = 0
            text_truncated = False
            loop = asyncio.get_running_loop()
            local_cancel = threading.Event()
            request_written = threading.Event()
            request_id = self.next_id()
            state = self._state
            if self.config.compact_events and state is not None:
                state.compact_final_text.clear()

            class PromptCancellationSignal:
                @property
                def cancelled(self) -> bool:
                    return local_cancel.is_set() or signal.cancelled

            def handle_event(
                raw: dict[str, Any], _control: PiRpcPromptControl
            ) -> PiRpcDirective:
                nonlocal text_bytes, text_truncated
                event = self._emit_event(raw, events, on_event)
                if event.type == "message_update":
                    assistant_event = raw.get("assistantMessageEvent")
                    if (
                        isinstance(assistant_event, Mapping)
                        and assistant_event.get("type") == "text_delta"
                        and isinstance(assistant_event.get("delta"), str)
                    ):
                        delta = assistant_event["delta"]
                        if text_truncated:
                            return PiRpcDirective.CONTINUE
                        encoded = delta.encode("utf-8")
                        remaining = _MAX_FINAL_TEXT_BYTES - text_bytes
                        if len(encoded) <= remaining:
                            text_parts.append(delta)
                            text_bytes += len(encoded)
                        else:
                            if remaining > 0:
                                text_parts.append(
                                    encoded[:remaining].decode("utf-8", "ignore")
                                )
                                text_bytes = _MAX_FINAL_TEXT_BYTES
                            text_truncated = True
                elif event.type in {"agent_end", "agent_settled"}:
                    return PiRpcDirective.COMPLETE
                return PiRpcDirective.CONTINUE

            def dispatch_event(
                raw: dict[str, Any], control: PiRpcPromptControl
            ) -> PiRpcDirective:
                result: concurrent.futures.Future[PiRpcDirective] = (
                    concurrent.futures.Future()
                )

                def invoke() -> None:
                    try:
                        result.set_result(handle_event(raw, control))
                    except BaseException as error:
                        result.set_exception(error)

                loop.call_soon_threadsafe(invoke)
                return result.result()

            driver_task = asyncio.create_task(
                asyncio.to_thread(
                    self.drive_prompt,
                    prompt,
                    timeout_seconds=self.config.deadline_seconds,
                    signal=PromptCancellationSignal(),
                    on_event=dispatch_event,
                    request_id=request_id,
                    on_request_written=request_written.set,
                    absolute_deadline=absolute_deadline,
                )
            )
            await self._await_driver(
                driver_task,
                local_cancel=local_cancel,
                request_written=request_written,
            )
            if state is not None and state.output_error is not None:
                self._lifecycle_poisoned = True
                raise state.output_error
            final_text = (
                bytes(state.compact_final_text).decode("utf-8", "ignore")
                if self.config.compact_events and state is not None
                else "".join(text_parts)
            )
            return PiRpcResult(
                final_text, tuple(events), self.stderr, request_id=request_id
            )

    async def compact(
        self,
        *,
        signal: CancellationSignal,
        on_event: Callable[[PiRpcEvent], None],
    ) -> PiRpcCompactResult:
        """Request native compaction on the currently open child."""

        self._check_run_ownership()
        if self._command_lock.locked():
            raise RuntimeError("Pi RPC session already has an active command")
        async with self._command_lock:
            self._check_command_ready("compact", signal)
            absolute_deadline = self._session_deadline
            assert absolute_deadline is not None
            events: list[PiRpcEvent] = []
            loop = asyncio.get_running_loop()
            local_cancel = threading.Event()
            request_written = threading.Event()
            request_id = self.next_id()

            class CompactCancellationSignal:
                @property
                def cancelled(self) -> bool:
                    return local_cancel.is_set() or signal.cancelled

            def drive() -> PiRpcCompactResult:
                control = PiRpcPromptControl(
                    self,
                    timeout_seconds=self.config.deadline_seconds,
                    signal=CompactCancellationSignal(),
                    absolute_deadline=absolute_deadline,
                )
                control.check_before_prompt()
                request_written.set()
                self.send({"id": request_id, "type": "compact"})
                while True:
                    raw = control.read_event()
                    delivered: concurrent.futures.Future[PiRpcEvent] = (
                        concurrent.futures.Future()
                    )

                    def invoke() -> None:
                        try:
                            delivered.set_result(
                                self._emit_event(raw, events, on_event)
                            )
                        except BaseException as error:
                            delivered.set_exception(error)

                    loop.call_soon_threadsafe(invoke)
                    delivered.result()
                    if raw.get("type") != "response":
                        continue
                    if raw.get("id") != request_id:
                        raise RuntimeError(
                            "Pi RPC response did not match the compact request"
                        )
                    result = PiRpcCompactResult(
                        request_id,
                        "compact",
                        tuple(events),
                        self.stderr,
                        outcome="completed"
                        if raw.get("success") is True
                        else "aborted",
                    )
                    validate_pi_compact_result(result)
                    return result

            driver_task = asyncio.create_task(asyncio.to_thread(drive))
            result = await self._await_driver(
                driver_task,
                local_cancel=local_cancel,
                request_written=request_written,
            )
            state = self._state
            if state is not None and state.output_error is not None:
                self._lifecycle_poisoned = True
                raise state.output_error
            assert type(result) is PiRpcCompactResult
            if result.outcome == "aborted":
                self._pending_compact_abort = result
                self._lifecycle_poisoned = True
            return result

    async def close(self) -> None:
        """Stop the reusable child; repeated calls are harmless."""

        self._check_run_ownership()
        async with self._command_lock:
            if not self._lifecycle_open and self.process is None:
                return
            try:
                self.stop()
            except BaseException:
                self._lifecycle_poisoned = True
                raise
            else:
                self._lifecycle_open = False
                self._lifecycle_poisoned = False
                self._session_deadline = None
                self._lifecycle_identity = None
                self._pending_compact_abort = None

    async def run(
        self,
        prompt: str,
        *,
        signal: CancellationSignal,
        on_event: Callable[[PiRpcEvent], None],
    ) -> PiRpcResult:
        if type(prompt) is not str:
            raise ValueError("Pi RPC prompt is invalid")
        if signal.cancelled:
            raise RuntimeError("Pi RPC prompt was cancelled before start")
        if self._run_active or self.process is not None:
            raise RuntimeError("Pi RPC session already has an active run")
        self._run_active = True
        self._run_owner = asyncio.current_task()
        self._last_failure = None
        try:
            await self.open(signal=signal)
            state = self._state
            result = await self.prompt(
                prompt,
                signal=signal,
                on_event=on_event,
            )
            await self.close()
            if state is not None and state.output_error is not None:
                raise state.output_error
            return PiRpcResult(result.final_text, result.events, self.stderr)
        except Exception as error:
            self._last_failure = str(error)
            raise
        finally:
            try:
                await self.close()
            finally:
                self._run_owner = None
                self._run_active = False


__all__ = (
    "PiRpcConfig",
    "PiRpcCompactResult",
    "PiRpcDirective",
    "PiRpcEvent",
    "PiRpcPromptControl",
    "PiRpcResult",
    "PiRpcSession",
    "normalize_pi_usage",
    "validate_pi_compact_result",
)
