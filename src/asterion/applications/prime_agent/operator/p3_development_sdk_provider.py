"""Private role-partitioned P3 SDK adapter with a single bounded ledger."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
import json
import os
import re
import signal
import struct
import time

from . import p2_development_sdk_provider as _p2
from .model_broker import PrimeModelBrokerTokenUsage
from .model_session_host import _PrivatePrimeModelConfig, _private_config_from_values
from .p3_development_workload import P3_ROLE_MODEL_CALLBACKS

_INPUT_CAP = 128 * 1024
_OUTPUT_CAP = 64 * 1024
_TOTAL_INPUT_TOKENS = 40_960
_TOTAL_OUTPUT_TOKENS = 5_120
_TOTAL_COST_MICROUNITS = 50_000
_RESERVATION = _TOTAL_COST_MICROUNITS // sum(P3_ROLE_MODEL_CALLBACKS.values())
_DEADLINE_SECONDS = 180.0
_REAP_GRACE_SECONDS = 2.0
_POLL_SECONDS = 0.01
_USAGE_SIZE = struct.calcsize("!QQQ")
_SELECTOR = re.compile(
    r"^(?P<role>root|implementation|review)-(?P<identity>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
_TERMINAL_NOTICE = {
    "implementation": "P3 implementation child completed.",
    "review": "P3 review child completed.",
}
_TERMINAL_NOTICE_PATTERN = re.compile(
    r"^RLM child (implementation|review) \([A-Za-z0-9._:-]+\) completed(?: without sending a reply)?$"
)


class PrimeP3DevelopmentSdkProviderError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development SDK provider is unavailable")


class PrimeP3DevelopmentSdkProvider:
    """Translate role-bound bridge callbacks through reaped HTTP children."""

    __slots__ = (
        "_calls",
        "_cancelled",
        "_child_pid",
        "_config",
        "_deadline",
        "_histories",
        "_issued",
        "_provisional",
        "_terminal",
        "_uncertain",
    )

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeP3DevelopmentSdkProviderError()
        self._calls = {role: 0 for role in P3_ROLE_MODEL_CALLBACKS}
        self._cancelled = False
        self._child_pid: int | None = None
        self._config = config
        self._deadline: float | None = None
        self._histories: dict[str, list[bytes]] = {
            role: [] for role in P3_ROLE_MODEL_CALLBACKS
        }
        self._issued: dict[str, tuple[dict[str, object], dict[str, object]] | None] = {
            role: None for role in P3_ROLE_MODEL_CALLBACKS
        }
        self._provisional = PrimeModelBrokerTokenUsage(0, 0, 0)
        self._terminal: PrimeModelBrokerTokenUsage | None = None
        self._uncertain = False

    def __repr__(self) -> str:
        return "PrimeP3DevelopmentSdkProvider(redacted)"

    @property
    def calls(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._calls))

    @property
    def histories(self) -> Mapping[str, tuple[bytes, ...]]:
        return MappingProxyType(
            {role: tuple(items) for role, items in self._histories.items()}
        )

    def terminal(self) -> bool:
        return (
            self._calls == dict(P3_ROLE_MODEL_CALLBACKS)
            and self._terminal is not None
            and not self._uncertain
        )

    def model_callback(self, role: str) -> Callable[[bytes], Awaitable[bytes]]:
        if role not in P3_ROLE_MODEL_CALLBACKS:
            raise PrimeP3DevelopmentSdkProviderError()

        async def invoke(body: bytes) -> bytes:
            return await self.callback(role, body)

        return invoke

    async def __call__(self, role: str, body: bytes) -> bytes:
        return await self.callback(role, body)

    async def callback(self, role: object, body: object) -> bytes:
        if (
            type(role) is not str
            or role not in P3_ROLE_MODEL_CALLBACKS
            or self._cancelled
            or self._child_pid is not None
            or type(body) is not bytes
            or not body
            or len(body) > _INPUT_CAP
            or self._calls[role] >= P3_ROLE_MODEL_CALLBACKS[role]
        ):
            raise PrimeP3DevelopmentSdkProviderError()
        try:
            request = _decode_request(body, self._issued[role], role)
        except BaseException:
            raise PrimeP3DevelopmentSdkProviderError() from None
        if self._deadline is None:
            self._deadline = time.monotonic() + _DEADLINE_SECONDS
        remaining = self._deadline - time.monotonic()
        if (
            remaining <= 0
            or self._provisional.input_tokens >= _TOTAL_INPUT_TOKENS
            or self._provisional.output_tokens >= _TOTAL_OUTPUT_TOKENS
            or self._provisional.cost_microunits + _RESERVATION > _TOTAL_COST_MICROUNITS
        ):
            raise PrimeP3DevelopmentSdkProviderError()
        self._uncertain = True
        try:
            response, usage = await self._run_child(
                request, role, self._calls[role], remaining
            )
            value = json.loads(response.decode("utf-8", "strict"))
            if type(value) is not dict:
                raise ValueError
            total = PrimeModelBrokerTokenUsage(
                self._provisional.input_tokens + usage.input_tokens,
                self._provisional.output_tokens + usage.output_tokens,
                self._provisional.cost_microunits + usage.cost_microunits,
            )
            if (
                total.input_tokens > _TOTAL_INPUT_TOKENS
                or total.output_tokens > _TOTAL_OUTPUT_TOKENS
                or total.cost_microunits > _TOTAL_COST_MICROUNITS
            ):
                raise ValueError
            self._calls[role] += 1
            self._histories[role].append(bytes(body))
            self._issued[role] = (request, value)
            self._provisional = total
            if self._calls == dict(P3_ROLE_MODEL_CALLBACKS):
                self._terminal, self._uncertain = total, False
            return response
        except asyncio.CancelledError:
            self._cancelled, self._terminal = True, None
            await self._reap_shielded()
            raise
        except BaseException:
            self._terminal = None
            await self._reap_shielded()
            raise PrimeP3DevelopmentSdkProviderError() from None

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if not self.terminal():
            raise PrimeP3DevelopmentSdkProviderError()
        return self._terminal  # type: ignore[return-value]

    async def _run_child(
        self, request: dict[str, object], role: str, call: int, timeout: float
    ) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
        left = right = result_left = result_right = None
        try:
            left, right = os.pipe()
            result_left, result_right = os.pipe()
            pid = os.fork()
            if pid == 0:
                _child(
                    self._config,
                    request,
                    role,
                    call,
                    timeout,
                    left,
                    right,
                    result_left,
                    result_right,
                )
            self._child_pid = pid
            _p2._close_quietly(left)
            left = None
            _p2._close_quietly(result_right)
            result_right = None
            _p2._write_all(right, b"1")
            _p2._close_quietly(right)
            right = None
            os.set_blocking(result_left, False)
            return await self._receive_result(result_left)
        finally:
            _p2._close_quietly(left)
            _p2._close_quietly(right)
            _p2._close_quietly(result_left)
            _p2._close_quietly(result_right)

    async def _receive_result(
        self, descriptor: int
    ) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
        chunks: list[bytes] = []
        while True:
            _p2._drain(descriptor, chunks)
            try:
                observed, status = os.waitpid(self._child_pid, os.WNOHANG)  # type: ignore[arg-type]
            except ChildProcessError:
                self._child_pid = None
                raise ValueError from None
            if observed:
                self._child_pid = None
                if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
                    raise ValueError
                _p2._drain(descriptor, chunks)
                return _decode_result(b"".join(chunks))
            if self._deadline is None or time.monotonic() >= self._deadline:
                raise TimeoutError
            await asyncio.sleep(_POLL_SECONDS)

    async def _reap_shielded(self) -> None:
        task = asyncio.create_task(self._kill_and_reap())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        task.result()
        if interrupted:
            raise asyncio.CancelledError

    async def _kill_and_reap(self) -> None:
        pid = self._child_pid
        if pid is None:
            return
        try:
            observed, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            self._child_pid = None
            return
        if observed:
            self._child_pid = None
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        deadline = time.monotonic() + _REAP_GRACE_SECONDS
        while time.monotonic() < deadline:
            try:
                observed, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                self._child_pid = None
                return
            if observed:
                self._child_pid = None
                return
            await asyncio.sleep(_POLL_SECONDS)
        raise PrimeP3DevelopmentSdkProviderError()


def create_prime_p3_development_sdk_provider(
    operator_config: Mapping[str, object],
) -> PrimeP3DevelopmentSdkProvider:
    try:
        return PrimeP3DevelopmentSdkProvider(
            _private_config_from_values(operator_config)
        )
    except BaseException:
        raise PrimeP3DevelopmentSdkProviderError() from None


def _decode_request(
    body: bytes, prior: tuple[dict[str, object], dict[str, object]] | None, role: str
) -> dict[str, object]:
    value = json.loads(body.decode("utf-8", "strict"))
    if role not in P3_ROLE_MODEL_CALLBACKS or (
        _p2._canonical_json(value).encode() != body
        or type(value) is not dict
        or set(value) != {"model", "context", "options"}
    ):
        raise ValueError
    model, context, options = value["model"], value["context"], value["options"]
    if (
        type(model) is not dict
        or type(context) is not dict
        or type(options) is not dict
        or not all(
            type(model.get(key)) is str and model[key]
            for key in ("api", "provider", "id")
        )
    ):
        raise ValueError
    if (
        set(context) - {"systemPrompt", "messages", "tools"}
        or type(context.get("messages")) is not list
    ):
        raise ValueError
    _validate_selector(model, role)
    _p2._validate_options(options, model)
    _p2._validate_ipython_tool(context.get("tools"))
    messages = context["messages"]
    if prior is None:
        if not messages or any(
            type(item) is not dict or item.get("role") != "user" for item in messages
        ):
            raise ValueError
        for item in messages:
            _p2._text_content(item.get("content"))
    else:
        old, issued = prior
        old_context = old["context"]
        old_messages = old_context["messages"]
        if (
            _p2._canonical_json(model) != _p2._canonical_json(old["model"])
            or _p2._canonical_json(options) != _p2._canonical_json(old["options"])
            or _p2._canonical_json(context.get("systemPrompt"))
            != _p2._canonical_json(old_context.get("systemPrompt"))
            or _p2._canonical_json(context.get("tools"))
            != _p2._canonical_json(old_context.get("tools"))
        ):
            raise ValueError
        if len(messages) <= len(old_messages) or _p2._canonical_json(
            messages[: len(old_messages)]
        ) != _p2._canonical_json(old_messages):
            raise ValueError
        messages[len(old_messages)] = _normalize_issued(
            issued, messages[len(old_messages)]
        )
        tail = messages[len(old_messages) + 1 :]
        if issued.get("stopReason") == "toolUse":
            if len(tail) != 1:
                raise ValueError
            _p2._validate_tool_pair(issued, tail[0])
        elif not tail or any(
            type(item) is not dict or item.get("role") != "user" for item in tail
        ):
            raise ValueError
        else:
            for item in tail:
                _p2._text_content(item.get("content"))
    return value


def _validate_selector(model: dict[str, object], role: str) -> None:
    match = _SELECTOR.fullmatch(model["id"])
    if match is None or match["role"] != role:
        raise ValueError
    identity = match["identity"]
    if (
        model["api"] != f"asterion-p3-{role}-{identity}"
        or model["provider"] != f"asterion-p3-{role}-{identity}"
    ):
        raise ValueError


def _normalize_issued(issued: dict[str, object], observed: object) -> dict[str, object]:
    if type(observed) is not dict or not _valid_usage(observed.get("usage")):
        raise ValueError
    stable = dict(observed)
    stable.pop("usage", None)
    expected = dict(issued)
    expected.pop("usage", None)
    if _p2._canonical_json(stable) != _p2._canonical_json(expected):
        raise ValueError
    return issued


def _valid_usage(value: object) -> bool:
    if type(value) is not dict or set(value) != {
        "input",
        "output",
        "cacheRead",
        "cacheWrite",
        "totalTokens",
        "cost",
    }:
        return False
    counts = (
        value["input"],
        value["output"],
        value["cacheRead"],
        value["cacheWrite"],
        value["totalTokens"],
    )
    if any(type(item) is not int or item < 0 for item in counts) or value[
        "totalTokens"
    ] != sum(counts[:4]):
        return False
    cost = value["cost"]
    return (
        type(cost) is dict
        and set(cost) == {"input", "output", "cacheRead", "cacheWrite", "total"}
        and all(
            type(item) in (int, float) and not isinstance(item, bool) and item >= 0
            for item in cost.values()
        )
    )


def _terminal_notice(text: str, callback_role: str) -> str:
    match = _TERMINAL_NOTICE_PATTERN.fullmatch(text)
    if match is None or callback_role != "root":
        return text
    return _TERMINAL_NOTICE[match[1]]


def _child(
    config: _PrivatePrimeModelConfig,
    request: dict[str, object],
    role: str,
    call: int,
    timeout: float,
    left: int,
    right: int,
    result_left: int,
    result_right: int,
) -> None:
    try:
        _p2._close_quietly(right)
        _p2._close_quietly(result_left)
        _p2._close_unneeded_child_fds(left, result_right)
        _p2._read_exact(left, 1)
        _p2._close_quietly(left)
        raw = _p2._post_chat_completion(
            config, _payload(request, config.model_id, role, call), timeout
        )
        response, usage = _assistant_response(
            request, raw, expected_tool=_tool_turn(role, call)
        )
        _p2._write_all(
            result_right,
            b"S"
            + struct.pack("!I", len(response))
            + response
            + struct.pack(
                "!QQQ", usage.input_tokens, usage.output_tokens, usage.cost_microunits
            ),
        )
        os._exit(0)
    except BaseException:
        try:
            _p2._write_all(result_right, b"F")
        except BaseException:
            pass
        os._exit(1)
    finally:
        _p2._close_quietly(left)
        _p2._close_quietly(result_right)


def _payload(
    request: dict[str, object], model_id: str, callback_role: str, call: int = 0
) -> dict[str, object]:
    context = request["context"]
    messages: list[dict[str, object]] = []
    if "systemPrompt" in context:
        messages.append({"role": "system", "content": context["systemPrompt"]})
    for item in context["messages"]:
        message_role = item["role"]
        if message_role == "user":
            text = _p2._text_content(item["content"])
            messages.append(
                {"role": "user", "content": _terminal_notice(text, callback_role)}
            )
        elif message_role == "toolResult":
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["toolCallId"],
                    "content": _p2._text_content(item["content"]),
                }
            )
        elif message_role == "assistant":
            block = item["content"][0]
            if block["type"] == "toolCall":
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": "ipython",
                                    "arguments": _p2._canonical_json(
                                        block["arguments"]
                                    ),
                                },
                            }
                        ],
                    }
                )
            else:
                messages.append({"role": "assistant", "content": block["text"]})
        else:
            raise ValueError
    tool = context["tools"][0]
    return {
        "max_tokens": 1024,
        "messages": messages,
        "model": model_id,
        "stream": False,
        "thinking": {"type": "disabled"},
        "tool_choice": "auto" if _tool_turn(callback_role, call) else "none",
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "ipython",
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
        ],
    }


def _assistant_response(
    request: dict[str, object], raw: object, *, expected_tool: bool
) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if (
        type(raw) is not dict
        or type(raw.get("choices")) is not list
        or len(raw["choices"]) != 1
        or type(raw.get("usage")) is not dict
    ):
        raise ValueError
    choice, usage = raw["choices"][0], raw["usage"]
    if (
        type(choice) is not dict
        or type(choice.get("message")) is not dict
        or type(usage.get("prompt_tokens")) is not int
        or type(usage.get("completion_tokens")) is not int
        or not 0 <= usage["completion_tokens"] <= 1024
    ):
        raise ValueError
    message, finish, model = (
        choice["message"],
        choice.get("finish_reason"),
        request["model"],
    )
    base = {
        "role": "assistant",
        "api": model["api"],
        "provider": model["provider"],
        "model": model["id"],
        "usage": _p2._usage(usage["prompt_tokens"], usage["completion_tokens"]),
        "timestamp": int(time.time() * 1000),
    }
    calls = message.get("tool_calls")
    if (
        expected_tool
        and finish == "tool_calls"
        and (message.get("content") is None or type(message.get("content")) is str)
        and type(calls) is list
        and len(calls) == 1
        and type(calls[0]) is dict
    ):
        call, fn = calls[0], calls[0].get("function")
        if (
            call.get("type") != "function"
            or type(call.get("id")) is not str
            or not call["id"]
            or type(fn) is not dict
            or fn.get("name") != "ipython"
            or type(fn.get("arguments")) is not str
        ):
            raise ValueError
        args = json.loads(fn["arguments"])
        if (
            type(args) is not dict
            or set(args) != {"code"}
            or type(args.get("code")) is not str
        ):
            raise ValueError
        base.update(
            {
                "content": [
                    {
                        "type": "toolCall",
                        "id": call["id"],
                        "name": "ipython",
                        "arguments": args,
                    }
                ],
                "stopReason": "toolUse",
            }
        )
    elif (
        not expected_tool
        and finish == "stop"
        and calls is None
        and type(message.get("content")) is str
        and message["content"]
    ):
        base.update(
            {
                "content": [{"type": "text", "text": message["content"]}],
                "stopReason": finish,
            }
        )
    else:
        raise ValueError
    return _p2._canonical_json(base).encode(), PrimeModelBrokerTokenUsage(
        usage["prompt_tokens"], usage["completion_tokens"], _RESERVATION
    )


def _tool_turn(role: str, call: int) -> bool:
    if role not in P3_ROLE_MODEL_CALLBACKS or type(call) is not int or call < 0:
        raise ValueError
    return call == 0 or (role == "review" and call == 2)


def _decode_result(raw: bytes) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if len(raw) < 5 or raw[:1] != b"S":
        raise ValueError
    size = struct.unpack("!I", raw[1:5])[0]
    if not 0 < size <= _OUTPUT_CAP or len(raw) != 5 + size + _USAGE_SIZE:
        raise ValueError
    source, values = raw[5 : 5 + size], raw[5 + size :]
    return source, PrimeModelBrokerTokenUsage(*struct.unpack("!QQQ", values))


__all__ = (
    "PrimeP3DevelopmentSdkProvider",
    "PrimeP3DevelopmentSdkProviderError",
    "create_prime_p3_development_sdk_provider",
)
