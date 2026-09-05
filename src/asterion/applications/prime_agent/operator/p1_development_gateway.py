"""Private, bounded Python transport for the P1 development Node bridge.

This module only translates a fixed local process protocol.  It deliberately
does not select providers, compose applications, or grant execution authority.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import inspect
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
from typing import Final


_PROTOCOL: Final = "asterion.prime-p1-development-gateway/v1"
_MAX_FRAME_BYTES: Final = 1024 * 1024
_STDERR_LIMIT: Final = 4096
_ID_MAX: Final = 128
_FRAME_KEYS: Final = frozenset((
    "generation", "kind", "payload", "protocol", "request_id", "run_id",
    "runtime_id", "sequence", "session_id",
))


class PrimeP1DevelopmentGatewayError(ValueError):
    """Public-safe P1 development gateway failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 development gateway is unavailable")


Hook = Callable[[Mapping[str, object]], object]


class PrimeP1DevelopmentGateway:
    """One private inherited-FD bridge session with synchronous and async APIs."""

    __slots__ = (
        "_child", "_deadline", "_entrypoint", "_identity", "_input_sequence",
        "_lock", "_model_hook", "_output_sequence", "_socket", "_state",
        "_stderr", "_stderr_thread", "_tool_hook", "_event_loop",
    )

    def __init__(
        self, *, model_hook: Hook | None = None, tool_hook: Hook | None = None,
        node_bin: str | os.PathLike[str] | None = None,
        entrypoint: str | os.PathLike[str] | None = None,
        deadline_seconds: float = 30.0,
    ) -> None:
        if type(deadline_seconds) not in (int, float) or not 0 < deadline_seconds <= 300:
            raise PrimeP1DevelopmentGatewayError()
        resolved_node = self._resolve_node(node_bin)
        resolved_entrypoint = Path(entrypoint) if entrypoint is not None else (
            Path(__file__).resolve().parents[5] / "packages/typescript/prime-gateway/dist/src/p1-development-main.js"
        )
        if not resolved_entrypoint.is_file():
            raise PrimeP1DevelopmentGatewayError()
        self._entrypoint = (resolved_node, str(resolved_entrypoint))
        self._deadline = float(deadline_seconds)
        self._model_hook = model_hook
        self._tool_hook = tool_hook
        self._child: subprocess.Popen[bytes] | None = None
        self._socket: socket.socket | None = None
        self._identity: dict[str, object] | None = None
        self._input_sequence = 0
        self._output_sequence = 0
        self._state = "new"
        self._lock = threading.RLock()
        self._stderr = bytearray()
        self._stderr_thread: threading.Thread | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None

    @staticmethod
    def _resolve_node(candidate: str | os.PathLike[str] | None) -> str:
        value = os.fspath(candidate) if candidate is not None else shutil.which("node")
        if not value:
            raise PrimeP1DevelopmentGatewayError()
        path = shutil.which(value) if not os.path.isabs(value) else value
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise PrimeP1DevelopmentGatewayError()
        return os.path.abspath(path)

    def __repr__(self) -> str:
        return "PrimeP1DevelopmentGateway(redacted)"

    @property
    def child_pid(self) -> int | None:
        child = self._child
        return child.pid if child is not None else None

    async def open(
        self, *, run_id: str, session_id: str, generation: int,
        prime_source_root: str, workspace: str,
    ) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(
            self.open_sync, run_id=run_id, session_id=session_id,
            generation=generation, prime_source_root=prime_source_root,
            workspace=workspace,
        )

    def open_sync(
        self, *, run_id: str, session_id: str, generation: int,
        prime_source_root: str, workspace: str,
    ) -> None:
        with self._lock:
            try:
                if self._state != "new" or not all(_valid_id(value) for value in (run_id, session_id)) or type(generation) is not int or generation < 1 or not _absolute(prime_source_root) or not _absolute(workspace):
                    raise ValueError
                self._identity = {"run_id": run_id, "session_id": session_id, "runtime_id": "prime.agent", "generation": generation}
                self._launch()
                request_id = self._send("open", "open-1", {"prime_source_root": prime_source_root, "workspace": workspace})
                frame = self._receive_until(request_id, {"ready"})
                if frame["kind"] != "ready" or frame["payload"] != {}:
                    raise ValueError
                self._state = "open"
            except BaseException:
                self._fail()
                raise PrimeP1DevelopmentGatewayError() from None

    async def prompt(self, prompt: str) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        return await asyncio.to_thread(self.prompt_sync, prompt)

    def prompt_sync(self, prompt: str) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "open" or type(prompt) is not str or not prompt:
                    raise ValueError
                self._state = "prompt"
                request_id = self._send("prompt", self._next_request_id("prompt"), {"prompt": prompt})
                frame = self._receive_until(request_id, {"command.result"})
                result = frame["payload"].get("result")
                if type(result) is not dict:
                    raise ValueError
                self._state = "open"
                return result
            except BaseException:
                self._fail()
                raise PrimeP1DevelopmentGatewayError() from None

    async def cancel(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        return await asyncio.to_thread(self.cancel_sync)

    def cancel_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state not in {"open", "prompt"}:
                    raise ValueError
                request_id = self._send("cancel", self._next_request_id("cancel"), {})
                frame = self._receive_until(request_id, {"command.result"})
                result = frame["payload"].get("result")
                if type(result) is not dict or result.get("lifecycle") != "cancelled":
                    raise ValueError
                self._state = "cancelled"
                return result
            except BaseException:
                self._fail()
                raise PrimeP1DevelopmentGatewayError() from None

    async def close(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.close_sync)

    def close_sync(self) -> None:
        with self._lock:
            if self._state in {"closed", "failed"}:
                return
            try:
                if self._state not in {"open", "cancelled"}:
                    raise ValueError
                request_id = self._send("close", self._next_request_id("close"), {})
                frame = self._receive_until(request_id, {"command.result"})
                if frame["payload"] != {"result": {"lifecycle": "closed"}}:
                    raise ValueError
                self._state = "closed"
                self._reap(graceful=True)
            except BaseException:
                self._fail()
                raise PrimeP1DevelopmentGatewayError() from None

    async def aopen(self, **kwargs: object) -> None:
        await self.open(**kwargs)  # type: ignore[arg-type]

    async def aprompt(self, prompt: str) -> Mapping[str, object]:
        return await self.prompt(prompt)

    async def acancel(self) -> Mapping[str, object]:
        return await self.cancel()

    async def aclose(self) -> None:
        await self.close()

    def _launch(self) -> None:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            child.set_inheritable(True)
            fd = child.fileno()
            self._child = subprocess.Popen(
                [self._entrypoint[0], self._entrypoint[1], str(fd)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                env={}, pass_fds=(fd,), close_fds=True,
            )
            self._socket = parent
            child.close()
            self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
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
            while True:
                data = child.stderr.read(1024)
                if not data:
                    return
                if len(self._stderr) < _STDERR_LIMIT:
                    self._stderr.extend(data[: _STDERR_LIMIT - len(self._stderr)])
        except OSError:
            return

    def _send(self, kind: str, request_id: str, payload: Mapping[str, object]) -> str:
        if self._socket is None or self._identity is None or not _valid_id(request_id):
            raise ValueError
        value: dict[str, object] = {"protocol": _PROTOCOL, **self._identity, "sequence": self._output_sequence + 1, "request_id": request_id, "kind": kind, "payload": dict(payload)}
        raw = _canonical_json(value).encode("utf-8")
        if len(raw) > _MAX_FRAME_BYTES:
            raise ValueError
        self._socket.sendall(len(raw).to_bytes(4, "big") + raw)
        self._output_sequence += 1
        return request_id

    def _receive_until(self, expected_id: str, expected_kinds: set[str]) -> dict[str, object]:
        deadline = time.monotonic() + self._deadline
        while True:
            frame = self._receive(deadline)
            kind = frame["kind"]
            request_id = frame["request_id"]
            if kind == "model.request":
                self._callback("model.response", request_id, "message", self._model_hook, frame["payload"])
                continue
            if kind == "tool.request":
                self._callback("tool.response", request_id, "result", self._tool_hook, frame["payload"])
                continue
            if request_id != expected_id or kind not in expected_kinds:
                raise ValueError
            return frame

    def _callback(self, response_kind: str, request_id: object, key: str, hook: Hook | None, payload: object) -> None:
        if hook is None or type(request_id) is not str or type(payload) is not dict:
            raise ValueError
        response = hook(payload)
        if inspect.isawaitable(response):
            loop = self._event_loop
            if loop is None or loop.is_closed():
                raise ValueError
            response = asyncio.run_coroutine_threadsafe(response, loop).result(
                timeout=max(0.001, self._deadline)
            )
        self._send(response_kind, request_id, {key: response})

    def _receive(self, deadline: float) -> dict[str, object]:
        sock = self._socket
        if sock is None:
            raise ValueError
        header = self._read_exact(sock, 4, deadline)
        size = int.from_bytes(header, "big")
        if size > _MAX_FRAME_BYTES:
            raise ValueError
        raw = self._read_exact(sock, size, deadline)
        value = json.loads(raw.decode("utf-8"))
        if _canonical_json(value).encode("utf-8") != raw or type(value) is not dict or set(value) != _FRAME_KEYS:
            raise ValueError
        if value.get("protocol") != _PROTOCOL or value.get("runtime_id") != "prime.agent" or value.get("generation") != (self._identity or {}).get("generation") or any(value.get(key) != (self._identity or {}).get(key) for key in ("run_id", "session_id", "runtime_id")):
            raise ValueError
        sequence = value.get("sequence")
        if type(sequence) is not int or sequence != self._input_sequence + 1 or not _valid_id(value.get("request_id")) or type(value.get("kind")) is not str or type(value.get("payload")) is not dict:
            raise ValueError
        self._input_sequence += 1
        return value

    @staticmethod
    def _read_exact(sock: socket.socket, length: int, deadline: float) -> bytes:
        chunks: list[bytes] = []
        while sum(map(len, chunks)) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            sock.settimeout(remaining)
            chunk = sock.recv(length - sum(map(len, chunks)))
            if not chunk:
                raise EOFError
            chunks.append(chunk)
        return b"".join(chunks)

    def _next_request_id(self, prefix: str) -> str:
        return f"{prefix}-{self._output_sequence + 1}"

    def _fail(self) -> None:
        self._state = "failed"
        self._reap(graceful=False)

    def _reap(self, *, graceful: bool) -> None:
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


def _valid_id(value: object) -> bool:
    return type(value) is str and 0 < len(value) <= _ID_MAX and value[0].isalnum() and all(character.isalnum() or character in "._:-" for character in value)


def _absolute(value: object) -> bool:
    return type(value) is str and os.path.isabs(value)


def _canonical_json(value: object) -> str:
    if value is None or type(value) in (str, bool, int):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is list:
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if type(value) is dict and all(type(key) is str for key in value):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _canonical_json(value[key]) for key in sorted(value)) + "}"
    raise ValueError


__all__ = ("PrimeP1DevelopmentGateway", "PrimeP1DevelopmentGatewayError")
