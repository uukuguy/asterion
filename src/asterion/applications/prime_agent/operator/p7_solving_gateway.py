"""Private 16-MiB framed transport for one autonomous P7 solve."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import os
from pathlib import Path
import socket
import time
from types import MappingProxyType
from typing import Final, cast

from .development_gateway_transport import (
    DevelopmentGatewayTransport,
    DevelopmentGatewayTransportError,
    Hook,
    _absolute,
    _canonical_json,
    _valid_id,
)

P7_SOLVING_GATEWAY_PROTOCOL: Final = "asterion.prime-p7-solving-gateway/v1"
P7_SOLVING_GATEWAY_FRAME_BYTES: Final = 16_777_216
_FRAME_KEYS = frozenset(
    {"generation", "kind", "payload", "protocol", "request_id", "run_id", "runtime_id", "sequence", "session_id"}
)
_READ_POLL_SECONDS = 0.05


class PrimeP7SolvingGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 solving gateway is unavailable")


class PrimeP7SolvingGateway(DevelopmentGatewayTransport):
    """Admit one open, one prompt, optional cancellation, and one close."""

    __slots__ = ("_state", "_terminal_witness")

    def __init__(
        self,
        *,
        model_hook: Hook | None = None,
        tool_hook: Hook | None = None,
        node_bin: str | os.PathLike[str] | None = None,
        entrypoint: str | os.PathLike[str] | None = None,
        deadline_seconds: float = 300.0,
    ) -> None:
        try:
            super().__init__(
                protocol=P7_SOLVING_GATEWAY_PROTOCOL,
                default_entrypoint=Path(__file__).resolve().parents[5]
                / "packages/typescript/prime-gateway/dist/src/p7-solving-main.js",
                model_hook=model_hook,
                tool_hook=tool_hook,
                node_bin=node_bin,
                entrypoint=entrypoint,
                deadline_seconds=deadline_seconds,
                nested_command_kinds=frozenset(),
            )
        except ValueError:
            raise PrimeP7SolvingGatewayError() from None
        self._state = "new"
        self._terminal_witness: Mapping[str, object] | None = None

    def __repr__(self) -> str:
        return "PrimeP7SolvingGateway(redacted)"

    def bind(self, *, model_hook: Hook, tool_hook: Hook) -> None:
        if self._state != "new" or not callable(model_hook) or not callable(tool_hook) or self._model_hook is not None or self._tool_hook is not None:
            raise PrimeP7SolvingGatewayError()
        self._model_hook, self._tool_hook = model_hook, tool_hook

    async def open(
        self,
        *,
        run_id: str,
        session_id: str,
        generation: int,
        prime_source_root: str = "/workspace",
        workspace: str = "/workspace",
    ) -> None:
        self._event_loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(
                self.open_sync, run_id=run_id, session_id=session_id,
                generation=generation, prime_source_root=prime_source_root, workspace=workspace,
            )
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
            raise

    def open_sync(
        self,
        *,
        run_id: str,
        session_id: str,
        generation: int,
        prime_source_root: str,
        workspace: str,
    ) -> None:
        with self._lock:
            try:
                if self._state != "new" or not _absolute(prime_source_root) or not _absolute(workspace):
                    raise ValueError
                self._set_identity(run_id=run_id, session_id=session_id, generation=generation)
                self._preflight_frame("open", "open-1", {"prime_source_root": prime_source_root, "workspace": workspace})
                self._launch()
                frame = self._receive_until(
                    self._send("open", "open-1", {"prime_source_root": prime_source_root, "workspace": workspace}),
                    {"ready"},
                )
                if frame["payload"] != {}:
                    raise ValueError
                self._state = "open"
            except BaseException:
                self._fail()
                raise PrimeP7SolvingGatewayError() from None

    async def prompt(self, prompt: str) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        try:
            return await asyncio.to_thread(self.prompt_sync, prompt)
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
            raise

    def prompt_sync(self, prompt: str) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "open" or type(prompt) is not str or not prompt:
                    raise ValueError
                request_id = self._next_request_id("prompt")
                self._preflight_frame("prompt", request_id, {"prompt": prompt})
                self._state = "prompt"
                frame = self._receive_until(self._send("prompt", request_id, {"prompt": prompt}), {"command.result"})
                payload = frame["payload"]
                if type(payload) is not dict:
                    raise ValueError
                result = payload.get("result")
                normalized, witness = _normalize_result(result)
                self._terminal_witness = witness
                self._state = "completed"
                return MappingProxyType(normalized)
            except BaseException:
                self._fail()
                raise PrimeP7SolvingGatewayError() from None

    def terminal_witness(self) -> Mapping[str, object]:
        if self._state not in {"completed", "closed"} or self._terminal_witness is None:
            raise PrimeP7SolvingGatewayError()
        identity = self._identity
        if type(identity) is not dict or set(identity) != {"run_id", "session_id", "runtime_id", "generation"}:
            raise PrimeP7SolvingGatewayError()
        witness = self._terminal_witness
        observations = witness["observations"]
        usage = witness["usage"]
        assistant = witness["assistant"]
        if type(observations) is not dict or type(usage) is not dict or type(assistant) is not dict:
            raise PrimeP7SolvingGatewayError()
        return MappingProxyType({
            "identity": MappingProxyType(dict(identity)),
            "result": MappingProxyType({
                "lifecycle": witness["lifecycle"],
                "usage": MappingProxyType(dict(usage)),
                "assistant": MappingProxyType(dict(assistant)),
                "observations": MappingProxyType(dict(observations)),
            }),
            "cumulative": MappingProxyType({
                "normal_model_callback_count": observations["normal_model_callback_count"],
                "summary_model_callback_count": observations["summary_model_callback_count"],
                "tool_callback_count": observations["tool_call_count"],
            }),
        })

    async def cancel(self) -> Mapping[str, object]:
        self._event_loop = asyncio.get_running_loop()
        if self._state == "prompt":
            await asyncio.shield(asyncio.to_thread(self._abort_active_prompt))
            raise PrimeP7SolvingGatewayError()
        return await asyncio.to_thread(self.cancel_sync)

    def cancel_sync(self) -> Mapping[str, object]:
        with self._lock:
            try:
                if self._state != "open":
                    raise ValueError
                frame = self._receive_until(self._send("cancel", self._next_request_id("cancel"), {}), {"command.result"})
                payload = frame["payload"]
                if type(payload) is not dict:
                    raise ValueError
                result = payload.get("result")
                if type(result) is not dict or result != {"lifecycle": "cancelled"}:
                    raise ValueError
                self._state = "cancelled"
                return MappingProxyType(result)
            except BaseException:
                self._fail()
                raise PrimeP7SolvingGatewayError() from None

    async def close(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        await asyncio.to_thread(self.close_sync)

    def close_sync(self) -> None:
        with self._lock:
            if self._state in {"closed", "failed"}:
                return
            try:
                if self._state not in {"open", "completed", "cancelled"}:
                    raise ValueError
                frame = self._receive_until(self._send("close", self._next_request_id("close"), {}), {"command.result"})
                if frame["payload"] != {"result": {"lifecycle": "closed"}}:
                    raise ValueError
                self._state = "closed"
                self._reap(graceful=True)
            except BaseException:
                self._fail()
                raise PrimeP7SolvingGatewayError() from None

    async def aopen(
        self,
        *,
        run_id: str,
        session_id: str,
        generation: int,
        prime_source_root: str = "/workspace",
        workspace: str = "/workspace",
    ) -> None:
        await self.open(
            run_id=run_id,
            session_id=session_id,
            generation=generation,
            prime_source_root=prime_source_root,
            workspace=workspace,
        )

    async def aprompt(self, prompt: str) -> Mapping[str, object]:
        return await self.prompt(prompt)

    async def acancel(self) -> Mapping[str, object]:
        return await self.cancel()

    async def aclose(self) -> None:
        await self.close()

    def _preflight_frame(self, kind: str, request_id: str, payload: Mapping[str, object]) -> None:
        identity = self._identity
        if type(identity) is not dict:
            raise DevelopmentGatewayTransportError()
        raw = _canonical_json({"protocol": self._protocol, **identity, "sequence": self._output_sequence + 1, "request_id": request_id, "kind": kind, "payload": dict(payload)}).encode()
        if len(raw) > P7_SOLVING_GATEWAY_FRAME_BYTES:
            raise DevelopmentGatewayTransportError()

    def _send_locked(self, kind: str, request_id: str, payload: Mapping[str, object]) -> str:
        if self._socket is None or self._identity is None or not _valid_id(request_id):
            raise DevelopmentGatewayTransportError()
        value = {"protocol": self._protocol, **cast(dict[str, object], self._identity), "sequence": self._output_sequence + 1, "request_id": request_id, "kind": kind, "payload": dict(payload)}
        raw = _canonical_json(value).encode("utf-8")
        if len(raw) > P7_SOLVING_GATEWAY_FRAME_BYTES:
            raise DevelopmentGatewayTransportError()
        self._socket.sendall(len(raw).to_bytes(4, "big") + raw)
        self._output_sequence += 1
        return request_id

    def _receive_until(
        self, expected_id: str, expected_kinds: set[str]
    ) -> dict[str, object]:
        try:
            deadline = time.monotonic() + self._deadline
            while True:
                frame = self._receive(deadline)
                if frame["kind"] == "model.request":
                    self._dispatch_callback(
                        "model.response",
                        frame["request_id"],
                        "message",
                        self._model_hook,
                        frame["payload"],
                    )
                    continue
                if frame["kind"] == "tool.request":
                    self._dispatch_callback(
                        "tool.response",
                        frame["request_id"],
                        "result",
                        self._tool_hook,
                        frame["payload"],
                    )
                    continue
                if frame["kind"] == "compaction.accepted":
                    self._accept_compaction_event(frame["payload"])
                    continue
                if (
                    frame["request_id"] == expected_id
                    and frame["kind"] in expected_kinds
                ):
                    return frame
                if frame["kind"] == "command.result":
                    self._resolve_nested(frame)
                    continue
                raise DevelopmentGatewayTransportError()
        except BaseException:
            self._fail_transport()
            raise

    def _accept_compaction_event(self, payload: object) -> None:
        if type(payload) is not dict or set(payload) != {"replaced_messages", "replacement_messages", "summary_spans"}:
            raise DevelopmentGatewayTransportError()
        accept = _compaction_acceptor(self._model_hook)
        if not callable(accept):
            raise DevelopmentGatewayTransportError()
        try:
            accept(
                replaced_messages=payload["replaced_messages"],
                replacement_messages=payload["replacement_messages"],
                summary_spans=payload["summary_spans"],
            )
        except BaseException:
            raise DevelopmentGatewayTransportError() from None

    def _receive(self, deadline: float) -> dict[str, object]:
        if self._socket is None:
            raise DevelopmentGatewayTransportError()
        size = int.from_bytes(self._read_exact_large(self._socket, 4, deadline), "big")
        if size > P7_SOLVING_GATEWAY_FRAME_BYTES:
            raise DevelopmentGatewayTransportError()
        raw = self._read_exact_large(self._socket, size, deadline)
        value = json.loads(raw.decode("utf-8"))
        if _canonical_json(value).encode("utf-8") != raw or type(value) is not dict or set(value) != _FRAME_KEYS:
            raise DevelopmentGatewayTransportError()
        identity = self._identity or {}
        if value.get("protocol") != self._protocol or any(value.get(key) != identity.get(key) for key in ("run_id", "session_id", "runtime_id", "generation")):
            raise DevelopmentGatewayTransportError()
        if type(value.get("sequence")) is not int or value["sequence"] != self._input_sequence + 1 or not _valid_id(value.get("request_id")) or type(value.get("kind")) is not str or type(value.get("payload")) is not dict:
            raise DevelopmentGatewayTransportError()
        self._input_sequence += 1
        return value

    @staticmethod
    def _read_exact_large(sock: socket.socket, length: int, deadline: float) -> bytes:
        chunks: list[bytes] = []
        received = 0
        while received < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                sock.settimeout(min(remaining, _READ_POLL_SECONDS))
                chunk = sock.recv(length - received)
            except TimeoutError:
                continue
            except OSError as error:
                raise DevelopmentGatewayTransportError() from error
            if not chunk:
                raise EOFError
            chunks.append(chunk)
            received += len(chunk)
        return b"".join(chunks)

    def _fail(self) -> None:
        self._state = "failed"
        self._fail_transport()

    def _abort_active_prompt(self) -> None:
        self._fail()


def _normalize_result(value: object) -> tuple[dict[str, object], dict[str, object]]:
    if type(value) is not dict or set(value) != {"lifecycle", "usage", "assistant", "observations"}:
        raise ValueError
    usage, assistant, observations = value["usage"], value["assistant"], value["observations"]
    observation_keys = {"active_tool_names", "compact_count", "normal_model_callback_count", "summary_model_callback_count", "rlm_child_count", "tool_call_count", "solved_latched"}
    if (
        value["lifecycle"] != "completed"
        or type(assistant) is not dict or set(assistant) != {"completed", "stop_reason"}
        or assistant.get("completed") is not True or assistant.get("stop_reason") not in {"stop", "toolUse"}
        or type(observations) is not dict or set(observations) != observation_keys
        or observations.get("active_tool_names") != ["ipython"] or observations.get("solved_latched") is not True
        or any(type(observations.get(key)) is not int or not 0 <= observations[key] <= 128 for key in ("compact_count", "normal_model_callback_count", "summary_model_callback_count", "rlm_child_count", "tool_call_count"))
        or observations["normal_model_callback_count"] + observations["summary_model_callback_count"] > 128
        or type(usage) is not dict or set(usage) != {"input_tokens", "output_tokens", "total_tokens"}
        or any(type(usage[key]) is not int or usage[key] < 0 for key in usage)
        or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
    ):
        raise ValueError
    normalized = {
        "lifecycle": "completed",
        "normal_model_callback_count": observations["normal_model_callback_count"],
        "summary_model_callback_count": observations["summary_model_callback_count"],
        "tool_callback_count": observations["tool_call_count"],
    }
    return normalized, value


def _compaction_acceptor(hook: object) -> object:
    accept = getattr(hook, "accept_compaction", None)
    if callable(accept):
        return accept
    owner = getattr(hook, "__self__", None)
    accept = getattr(owner, "accept_compaction", None)
    return accept


__all__ = (
    "PrimeP7SolvingGateway", "PrimeP7SolvingGatewayError",
    "P7_SOLVING_GATEWAY_PROTOCOL", "P7_SOLVING_GATEWAY_FRAME_BYTES",
)
