"""Private framed-process transport shared by development gateway sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import inspect
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from typing import Final

_MAX_FRAME_BYTES: Final = 1024 * 1024
_STDERR_LIMIT: Final = 4096
_READ_POLL_SECONDS: Final = 0.05
_ID_MAX: Final = 128
_FRAME_KEYS: Final = frozenset(
    (
        "generation",
        "kind",
        "payload",
        "protocol",
        "request_id",
        "run_id",
        "runtime_id",
        "sequence",
        "session_id",
    )
)
Hook = Callable[[Mapping[str, object]], object]


class DevelopmentGatewayTransportError(ValueError):
    pass


class DevelopmentGatewayTransport:
    """One inherited-FD child with canonical, identity-bound request frames."""

    __slots__ = (
        "_child",
        "_deadline",
        "_entrypoint",
        "_identity",
        "_input_sequence",
        "_lock",
        "_model_hook",
        "_output_sequence",
        "_protocol",
        "_socket",
        "_stderr",
        "_stderr_thread",
        "_tool_hook",
        "_event_loop",
        "_reap_lock",
    )

    def __init__(
        self,
        *,
        protocol: str,
        default_entrypoint: Path,
        model_hook: Hook | None,
        tool_hook: Hook | None,
        node_bin: str | os.PathLike[str] | None,
        entrypoint: str | os.PathLike[str] | None,
        deadline_seconds: float,
    ) -> None:
        if (
            type(deadline_seconds) not in (int, float)
            or not 0 < deadline_seconds <= 300
        ):
            raise DevelopmentGatewayTransportError()
        resolved_node = self._resolve_node(node_bin)
        resolved_entrypoint = (
            Path(entrypoint) if entrypoint is not None else default_entrypoint
        )
        if not resolved_entrypoint.is_file():
            raise DevelopmentGatewayTransportError()
        self._protocol = protocol
        self._entrypoint = (resolved_node, str(resolved_entrypoint))
        self._deadline = float(deadline_seconds)
        self._model_hook, self._tool_hook = model_hook, tool_hook
        self._child: subprocess.Popen[bytes] | None = None
        self._socket: socket.socket | None = None
        self._identity: dict[str, object] | None = None
        self._input_sequence = self._output_sequence = 0
        self._lock, self._reap_lock = threading.RLock(), threading.Lock()
        self._stderr = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    @staticmethod
    def _resolve_node(candidate: str | os.PathLike[str] | None) -> str:
        value = os.fspath(candidate) if candidate is not None else shutil.which("node")
        path = shutil.which(value) if value and not os.path.isabs(value) else value
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise DevelopmentGatewayTransportError()
        return os.path.abspath(path)

    @property
    def child_pid(self) -> int | None:
        return self._child.pid if self._child is not None else None

    def _set_identity(self, *, run_id: str, session_id: str, generation: int) -> None:
        if (
            not all(_valid_id(value) for value in (run_id, session_id))
            or type(generation) is not int
            or generation < 1
        ):
            raise DevelopmentGatewayTransportError()
        self._identity = {
            "run_id": run_id,
            "session_id": session_id,
            "runtime_id": "prime.agent",
            "generation": generation,
        }

    def _launch(self) -> None:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            child.set_inheritable(True)
            fd = child.fileno()
            self._child = subprocess.Popen(
                [self._entrypoint[0], self._entrypoint[1], str(fd)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env={},
                pass_fds=(fd,),
                close_fds=True,
            )
            self._socket = parent
            child.close()
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, daemon=True
            )
            self._stderr_thread.start()
        except BaseException:
            parent.close()
            child.close()
            raise

    def _drain_stderr(self) -> None:
        child = self._child
        if child is None or child.stderr is None:
            return
        try:
            while data := child.stderr.read(1024):
                if len(self._stderr) < _STDERR_LIMIT:
                    self._stderr.extend(data[: _STDERR_LIMIT - len(self._stderr)])
        except OSError:
            pass

    def _send(self, kind: str, request_id: str, payload: Mapping[str, object]) -> str:
        if self._socket is None or self._identity is None or not _valid_id(request_id):
            raise DevelopmentGatewayTransportError()
        value: dict[str, object] = {
            "protocol": self._protocol,
            **self._identity,
            "sequence": self._output_sequence + 1,
            "request_id": request_id,
            "kind": kind,
            "payload": dict(payload),
        }
        raw = _canonical_json(value).encode("utf-8")
        if len(raw) > _MAX_FRAME_BYTES:
            raise DevelopmentGatewayTransportError()
        self._socket.sendall(len(raw).to_bytes(4, "big") + raw)
        self._output_sequence += 1
        return request_id

    def _receive_until(
        self, expected_id: str, expected_kinds: set[str]
    ) -> dict[str, object]:
        deadline = time.monotonic() + self._deadline
        while True:
            frame = self._receive(deadline)
            if frame["kind"] == "model.request":
                self._callback(
                    "model.response",
                    frame["request_id"],
                    "message",
                    self._model_hook,
                    frame["payload"],
                )
                continue
            if frame["kind"] == "tool.request":
                self._callback(
                    "tool.response",
                    frame["request_id"],
                    "result",
                    self._tool_hook,
                    frame["payload"],
                )
                continue
            if (
                frame["request_id"] != expected_id
                or frame["kind"] not in expected_kinds
            ):
                raise DevelopmentGatewayTransportError()
            return frame

    def _callback(
        self,
        response_kind: str,
        request_id: object,
        key: str,
        hook: Hook | None,
        payload: object,
    ) -> None:
        if hook is None or type(request_id) is not str or type(payload) is not dict:
            raise DevelopmentGatewayTransportError()
        response = hook(payload)
        if inspect.isawaitable(response):
            loop = self._event_loop
            if loop is None or loop.is_closed():
                raise DevelopmentGatewayTransportError()
            response = asyncio.run_coroutine_threadsafe(response, loop).result(
                timeout=max(0.001, self._deadline)
            )
        self._send(response_kind, request_id, {key: response})

    def _receive(self, deadline: float) -> dict[str, object]:
        if self._socket is None:
            raise DevelopmentGatewayTransportError()
        size = int.from_bytes(self._read_exact(self._socket, 4, deadline), "big")
        if size > _MAX_FRAME_BYTES:
            raise DevelopmentGatewayTransportError()
        raw = self._read_exact(self._socket, size, deadline)
        value = json.loads(raw.decode("utf-8"))
        if (
            _canonical_json(value).encode("utf-8") != raw
            or type(value) is not dict
            or set(value) != _FRAME_KEYS
        ):
            raise DevelopmentGatewayTransportError()
        identity = self._identity or {}
        if value.get("protocol") != self._protocol or any(
            value.get(key) != identity.get(key)
            for key in ("run_id", "session_id", "runtime_id", "generation")
        ):
            raise DevelopmentGatewayTransportError()
        if (
            type(value.get("sequence")) is not int
            or value["sequence"] != self._input_sequence + 1
            or not _valid_id(value.get("request_id"))
            or type(value.get("kind")) is not str
            or type(value.get("payload")) is not dict
        ):
            raise DevelopmentGatewayTransportError()
        self._input_sequence += 1
        return value

    @staticmethod
    def _read_exact(sock: socket.socket, length: int, deadline: float) -> bytes:
        chunks: list[bytes] = []
        received = 0
        while received < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            sock.settimeout(min(remaining, _READ_POLL_SECONDS))
            try:
                chunk = sock.recv(length - received)
            except TimeoutError:
                continue
            if not chunk:
                raise EOFError()
            chunks.append(chunk)
            received += len(chunk)
        return b"".join(chunks)

    def _next_request_id(self, prefix: str) -> str:
        return f"{prefix}-{self._output_sequence + 1}"

    def _reap(self, *, graceful: bool) -> None:
        with self._reap_lock:
            sock, self._socket = self._socket, None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            child, self._child = self._child, None
            if child is None:
                return
            try:
                if graceful:
                    child.wait(timeout=min(self._deadline, 1.0))
                else:
                    child.terminate()
                    child.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                try:
                    child.kill()
                except OSError:
                    pass
                try:
                    child.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            finally:
                if child.stderr is not None:
                    try:
                        child.stderr.close()
                    except OSError:
                        pass

    def _fail_transport(self) -> None:
        self._reap(graceful=False)


def _valid_id(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= _ID_MAX
        and value[0].isalnum()
        and all(c.isalnum() or c in "._:-" for c in value)
    )


def _absolute(value: object) -> bool:
    return type(value) is str and os.path.isabs(value)


def _canonical_json(value: object) -> str:
    if value is None or type(value) in (str, bool, int):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is float:
        if not math.isfinite(value):
            raise DevelopmentGatewayTransportError()
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is list:
        return "[" + ",".join(_canonical_json(x) for x in value) + "]"
    if type(value) is dict and all(type(key) is str for key in value):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False) + ":" + _canonical_json(value[key])
                for key in sorted(value)
            )
            + "}"
        )
    raise DevelopmentGatewayTransportError()
