"""Domain-neutral process and session lifecycle for Pi JSONL-RPC."""

from __future__ import annotations

import asyncio
import json
import math
import queue
import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol


_MAX_STDOUT_LINE_BYTES = 64 * 1024
_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_MAX_STDERR_BYTES = 64 * 1024
_MAX_EVENT_COUNT = 2048
_MAX_FINAL_TEXT_BYTES = 1024 * 1024
_GRACEFUL_EXIT_SECONDS = 0.1
_PROCESS_EXIT_SECONDS = 0.25
_PIPE_DRAIN_SECONDS = 0.25
_POLL_SECONDS = 0.05
_STDOUT_EOF = object()


class CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool: ...


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class PiRpcConfig:
    command: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    deadline_seconds: float
    inherited_fds: tuple[int, ...] = ()

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

    def __post_init__(self) -> None:
        if type(self.final_text) is not str:
            raise ValueError("Pi RPC final text is invalid")
        if type(self.events) is not tuple or any(
            type(event) is not PiRpcEvent for event in self.events
        ):
            raise ValueError("Pi RPC result events are invalid")
        if type(self.stderr) is not bytes:
            raise ValueError("Pi RPC stderr is invalid")


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
        self.process: subprocess.Popen[bytes] | None = None
        self._stdout_queue: queue.Queue[object] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr = bytearray()
        self._output_error: RuntimeError | None = None
        self._request_id = 0
        self._run_active = False

    @property
    def stderr(self) -> bytes:
        return bytes(self._stderr)

    def next_id(self) -> str:
        self._request_id += 1
        return f"py-{self._request_id}"

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("RPC session already started")
        self._stdout_queue = queue.Queue()
        self._stderr = bytearray()
        self._output_error = None
        try:
            self.process = self._popen(
                list(self.config.command),
                cwd=self.config.cwd,
                env=dict(self.config.environment),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=self.config.inherited_fds,
            )
            self._stdout_thread = self._thread_factory(
                target=self._drain_stdout, daemon=True
            )
            self._stdout_thread.start()
            self._stderr_thread = self._thread_factory(
                target=self._drain_stderr, daemon=True
            )
            self._stderr_thread.start()
        except BaseException:
            self.stop()
            raise

    def _fail_output(self, message: str) -> None:
        error = RuntimeError(message)
        self._output_error = error
        self._stdout_queue.put(error)

    def _drain_stdout(self) -> None:
        process = self.process
        assert process is not None and process.stdout is not None
        total_bytes = 0
        event_count = 0
        try:
            for raw in process.stdout:
                total_bytes += len(raw)
                if len(raw) > _MAX_STDOUT_LINE_BYTES or total_bytes > _MAX_STDOUT_BYTES:
                    self._fail_output("Pi RPC output limit exceeded")
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._fail_output("Pi RPC emitted invalid JSONL")
                    return
                if not isinstance(payload, dict):
                    self._fail_output("Pi RPC emitted a non-object JSON value")
                    return
                event_count += 1
                if event_count > _MAX_EVENT_COUNT:
                    self._fail_output("Pi RPC output limit exceeded")
                    return
                self._stdout_queue.put(payload)
        finally:
            self._stdout_queue.put(_STDOUT_EOF)

    def _drain_stderr(self) -> None:
        process = self.process
        assert process is not None and process.stderr is not None
        for raw in process.stderr:
            remaining = _MAX_STDERR_BYTES - len(self._stderr)
            if remaining > 0:
                self._stderr.extend(raw[:remaining])
            if len(raw) > remaining:
                self._fail_output("Pi RPC output limit exceeded")
                return

    def send(self, payload: Mapping[str, object]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise RuntimeError("RPC session is not running")
        encoded = (json.dumps(dict(payload), separators=(",", ":")) + "\n").encode()
        process.stdin.write(encoded)
        process.stdin.flush()

    def read_json_line(self, *, timeout_seconds: float | None = None) -> dict[str, Any]:
        try:
            item = self._stdout_queue.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise TimeoutError("Timed out waiting for an RPC event") from error
        if item is _STDOUT_EOF:
            if self._output_error is not None:
                raise self._output_error
            raise RuntimeError("Pi RPC process exited unexpectedly")
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, dict):
            raise RuntimeError("Pi RPC queue returned an invalid event")
        return item

    def stop(self) -> None:
        process = self.process
        if process is None:
            return
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
                    process.terminate()
                    try:
                        process.wait(timeout=_PROCESS_EXIT_SECONDS)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        try:
                            process.wait(timeout=_PROCESS_EXIT_SECONDS)
                        except subprocess.TimeoutExpired as error:
                            failure = error
        finally:
            for thread in (self._stdout_thread, self._stderr_thread):
                if thread is not None:
                    thread.join(timeout=_PIPE_DRAIN_SECONDS)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self._stdout_thread = None
            self._stderr_thread = None
            self.process = None
        if failure is not None:
            raise RuntimeError("Pi RPC process cleanup timed out") from failure

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
        deadline = asyncio.get_running_loop().time() + self.config.deadline_seconds
        events: list[PiRpcEvent] = []
        text_parts: list[str] = []
        text_bytes = 0
        request_id = self.next_id()
        acknowledged = False
        try:
            self.start()
            self.send({"id": request_id, "type": "prompt", "message": prompt})
            while True:
                if signal.cancelled:
                    self._send_abort()
                    raise RuntimeError("Pi RPC prompt was cancelled")
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._send_abort()
                    raise RuntimeError(
                        f"Pi RPC prompt timed out after {self.config.deadline_seconds:g} seconds"
                    )
                try:
                    raw = await asyncio.to_thread(
                        self.read_json_line,
                        timeout_seconds=min(_POLL_SECONDS, remaining),
                    )
                except TimeoutError:
                    continue
                event_type = raw.get("type")
                if type(event_type) is not str or not event_type:
                    raise RuntimeError("Pi RPC event type is invalid")
                event = PiRpcEvent(
                    sequence=len(events) + 1,
                    type=event_type,
                    payload={key: value for key, value in raw.items() if key != "type"},
                )
                events.append(event)
                on_event(event)
                if event_type == "response":
                    if raw.get("id") != request_id:
                        raise RuntimeError("Pi RPC response did not match the prompt")
                    if acknowledged or raw.get("success") is not True:
                        raise RuntimeError("Pi RPC prompt failed")
                    acknowledged = True
                    continue
                if event_type == "message_update":
                    assistant_event = raw.get("assistantMessageEvent")
                    if (
                        isinstance(assistant_event, Mapping)
                        and assistant_event.get("type") == "text_delta"
                        and isinstance(assistant_event.get("delta"), str)
                    ):
                        delta = assistant_event["delta"]
                        encoded_bytes = len(delta.encode("utf-8"))
                        text_bytes += encoded_bytes
                        if text_bytes > _MAX_FINAL_TEXT_BYTES:
                            raise RuntimeError("Pi RPC output limit exceeded")
                        text_parts.append(delta)
                    continue
                if event_type == "agent_end":
                    raise RuntimeError("Pi RPC agent ended before agent_settled")
                if event_type == "agent_settled":
                    if not acknowledged:
                        raise RuntimeError(
                            "Received agent_settled before prompt acknowledgement"
                        )
                    self.stop()
                    if self._output_error is not None:
                        raise self._output_error
                    return PiRpcResult("".join(text_parts), tuple(events), self.stderr)
        except asyncio.CancelledError:
            self._send_abort()
            raise
        finally:
            try:
                self.stop()
            finally:
                self._run_active = False

    def _send_abort(self) -> None:
        try:
            self.send({"id": self.next_id(), "type": "abort"})
        except (BrokenPipeError, OSError, RuntimeError):
            pass


__all__ = ("PiRpcConfig", "PiRpcEvent", "PiRpcResult", "PiRpcSession")
