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
from dataclasses import dataclass
from enum import Enum
from io import UnsupportedOperation
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
_PROMPT_DRIVER_EXIT_SECONDS = 1.0
_STDOUT_EOF = object()


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
    ) -> None:
        self._session = session
        self._timeout_seconds = timeout_seconds
        self._signal = signal
        self._deadline = (
            time.monotonic() + timeout_seconds
            if timeout_seconds is not None and timeout_seconds > 0
            else None
        )
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
                return self._session.read_json_line(
                    timeout_seconds=self.poll_seconds()
                )
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
        self._state: _ProcessState | None = None
        self._last_stderr = b""
        self._request_id = 0
        self._run_active = False

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return None if self._state is None else self._state.process

    @property
    def stderr(self) -> bytes:
        return self._last_stderr if self._state is None else bytes(self._state.stderr)

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
        total_bytes = 0
        event_count = 0
        try:
            for raw in process.stdout:
                total_bytes += len(raw)
                if len(raw) > _MAX_STDOUT_LINE_BYTES or total_bytes > _MAX_STDOUT_BYTES:
                    self._fail_output(state, "Pi RPC output limit exceeded")
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._fail_output(state, "Pi RPC emitted invalid JSONL")
                    return
                if not isinstance(payload, dict):
                    self._fail_output(state, "Pi RPC emitted a non-object JSON value")
                    return
                event_count += 1
                if event_count > _MAX_EVENT_COUNT:
                    self._fail_output(state, "Pi RPC output limit exceeded")
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
                    self._fail_output(state, "Pi RPC output limit exceeded")
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
    ) -> float | None:
        """Drive one prompt exchange while the caller interprets Pi events."""

        if type(message) is not str:
            raise ValueError("Pi RPC prompt is invalid")
        control = PiRpcPromptControl(
            self,
            timeout_seconds=timeout_seconds,
            signal=signal,
        )
        control.check_before_prompt()
        request_id = self.next_id()
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
        events: list[PiRpcEvent] = []
        text_parts: list[str] = []
        text_bytes = 0
        loop = asyncio.get_running_loop()
        local_cancel = threading.Event()

        class RunCancellationSignal:
            @property
            def cancelled(self) -> bool:
                return local_cancel.is_set() or signal.cancelled

        run_signal = RunCancellationSignal()

        def handle_event(
            raw: dict[str, Any], _control: PiRpcPromptControl
        ) -> PiRpcDirective:
            nonlocal text_bytes
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
            elif event_type == "agent_end":
                raise RuntimeError("Pi RPC agent ended before agent_settled")
            elif event_type == "agent_settled":
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

        driver_task: asyncio.Task[float | None] | None = None
        try:
            self.start()
            driver_task = asyncio.create_task(
                asyncio.to_thread(
                    self.drive_prompt,
                    prompt,
                    timeout_seconds=self.config.deadline_seconds,
                    signal=run_signal,
                    on_event=dispatch_event,
                )
            )
            await asyncio.wait((driver_task,))
            driver_task.result()
            state = self._state
            self.stop()
            if state is not None and state.output_error is not None:
                raise state.output_error
            return PiRpcResult("".join(text_parts), tuple(events), self.stderr)
        except asyncio.CancelledError:
            if driver_task is not None and not driver_task.done():
                local_cancel.set()
                self.abort()
                done, _pending = await asyncio.wait(
                    (driver_task,), timeout=_PROMPT_DRIVER_EXIT_SECONDS
                )
                if not done:
                    raise RuntimeError(
                        "Pi RPC prompt driver cleanup timed out"
                    ) from None
                try:
                    driver_task.result()
                except BaseException:
                    pass
            raise
        finally:
            if driver_task is None or driver_task.done():
                try:
                    self.stop()
                finally:
                    self._run_active = False


__all__ = (
    "PiRpcConfig",
    "PiRpcDirective",
    "PiRpcEvent",
    "PiRpcPromptControl",
    "PiRpcResult",
    "PiRpcSession",
)
