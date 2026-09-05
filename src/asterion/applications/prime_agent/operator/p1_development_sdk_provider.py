"""Private two-turn DeepSeek adapter for the P1 development SDK bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import os
import signal
import struct
import time
import urllib.error
import urllib.request

from .model_broker import PrimeModelBrokerTokenUsage
from .model_session_host import (
    _ENDPOINT,
    _P1_DEADLINE_SECONDS,
    _P1_MAX_COST_MICROUNITS,
    _P1_MAX_INPUT_TOKENS,
    _P1_MAX_OUTPUT_TOKENS,
    _PrivatePrimeModelConfig,
    _private_config_from_values,
)


_INPUT_CAP = 64 * 1024
_OUTPUT_CAP = 64 * 1024
_MAX_REQUESTS = 2
_REAP_GRACE_SECONDS = 2.0
_POLL_SECONDS = 0.01
_USAGE_SIZE = struct.calcsize("!QQQ")


class PrimeP1DevelopmentSdkProviderError(ValueError):
    """Body-free P1 development SDK provider failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime development SDK provider is unavailable")


class PrimeP1DevelopmentSdkProvider:
    """Translate exactly two private Prime SDK turns through reaped children."""

    __slots__ = (
        "_calls", "_cancelled", "_child_pid", "_config", "_deadline", "_terminal",
    )

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeP1DevelopmentSdkProviderError()
        self._calls = 0
        self._cancelled = False
        self._child_pid: int | None = None
        self._config = config
        self._deadline: float | None = None
        self._terminal = PrimeModelBrokerTokenUsage(0, 0, 0)

    def __repr__(self) -> str:
        return "PrimeP1DevelopmentSdkProvider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if (
            self._cancelled
            or self._child_pid is not None
            or type(body) is not bytes
            or not body
            or len(body) > _INPUT_CAP
            or self._calls >= _MAX_REQUESTS
        ):
            raise PrimeP1DevelopmentSdkProviderError()
        try:
            request = _decode_request(body, turn=self._calls)
        except BaseException:
            raise PrimeP1DevelopmentSdkProviderError() from None
        if self._deadline is None:
            self._deadline = time.monotonic() + float(_P1_DEADLINE_SECONDS)
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise PrimeP1DevelopmentSdkProviderError()
        self._calls += 1
        request_read = request_write = result_read = result_write = None
        try:
            request_read, request_write = os.pipe()
            result_read, result_write = os.pipe()
            pid = os.fork()
            if pid == 0:
                _sdk_provider_child(
                    self._config, request, remaining, request_read, request_write,
                    result_read, result_write,
                )
            self._child_pid = pid
            _close_quietly(request_read)
            request_read = None
            _close_quietly(result_write)
            result_write = None
            _write_all(request_write, body)
            _close_quietly(request_write)
            request_write = None
            os.set_blocking(result_read, False)
            response, usage = await self._receive_result(result_read)
            next_usage = PrimeModelBrokerTokenUsage(
                self._terminal.input_tokens + usage.input_tokens,
                self._terminal.output_tokens + usage.output_tokens,
                self._terminal.cost_microunits + usage.cost_microunits,
            )
            if (
                next_usage.input_tokens > _P1_MAX_INPUT_TOKENS
                or next_usage.output_tokens > _P1_MAX_OUTPUT_TOKENS
                or next_usage.cost_microunits > _P1_MAX_COST_MICROUNITS
            ):
                raise ValueError
            self._terminal = next_usage
            return response
        except asyncio.CancelledError:
            self._cancelled = True
            await self._reap_shielded()
            raise
        except BaseException:
            await self._reap_shielded()
            raise PrimeP1DevelopmentSdkProviderError() from None
        finally:
            _close_quietly(request_read)
            _close_quietly(request_write)
            _close_quietly(result_read)
            _close_quietly(result_write)

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        return self._terminal

    async def _receive_result(self, result_read: int) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
        chunks: list[bytes] = []
        while True:
            _drain(result_read, chunks)
            try:
                observed, status = os.waitpid(self._child_pid, os.WNOHANG)  # type: ignore[arg-type]
            except ChildProcessError:
                self._child_pid = None
                raise ValueError from None
            if observed:
                self._child_pid = None
                if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
                    raise ValueError
                _drain(result_read, chunks)
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
        raise PrimeP1DevelopmentSdkProviderError()


def create_prime_p1_development_sdk_provider(
    operator_config: Mapping[str, object],
) -> PrimeP1DevelopmentSdkProvider:
    try:
        return PrimeP1DevelopmentSdkProvider(_private_config_from_values(operator_config))
    except BaseException:
        raise PrimeP1DevelopmentSdkProviderError() from None


def _sdk_provider_child(
    config: _PrivatePrimeModelConfig, request: object, timeout: float,
    request_read: int, request_write: int, result_read: int, result_write: int,
) -> None:
    try:
        _close_quietly(request_write)
        _close_quietly(result_read)
        body = _read_exact(request_read, _INPUT_CAP)
        _close_quietly(request_read)
        turn = _request_turn(body)
        payload = _deepseek_payload(request, config.model_id, turn)
        raw = _post_chat_completion(config, payload, timeout)
        response, usage = _assistant_response(request, raw, turn)
        if not response or len(response) > _OUTPUT_CAP:
            raise ValueError
        _write_all(
            result_write,
            b"S" + struct.pack("!I", len(response)) + response + struct.pack(
                "!QQQ", usage.input_tokens, usage.output_tokens, usage.cost_microunits,
            ),
        )
        os._exit(0)
    except BaseException:
        try:
            _write_all(result_write, b"F")
        except BaseException:
            pass
        os._exit(1)
    finally:
        _close_quietly(request_read)
        _close_quietly(request_write)
        _close_quietly(result_read)
        _close_quietly(result_write)


def _decode_request(body: bytes, *, turn: int) -> dict[str, object]:
    value = json.loads(body.decode("utf-8", "strict"))
    if _canonical_json(value).encode("utf-8") != body or type(value) is not dict:
        raise ValueError
    _validate_request(value, turn)
    return value


def _request_turn(body: bytes) -> int:
    value = json.loads(body.decode("utf-8", "strict"))
    messages = value["context"]["messages"]
    return 1 if type(messages) is list and len(messages) >= 2 and messages[-1].get("role") == "toolResult" else 0


def _validate_request(value: dict[str, object], turn: int) -> None:
    if set(value) != {"model", "context", "options"}:
        raise ValueError
    model, context, options = value["model"], value["context"], value["options"]
    if type(model) is not dict or type(context) is not dict or type(options) is not dict:
        raise ValueError
    if not all(type(model.get(key)) is str and model[key] for key in ("api", "provider", "id")):
        raise ValueError
    if set(context) - {"systemPrompt", "messages", "tools"} or type(context.get("messages")) is not list:
        raise ValueError
    if "systemPrompt" in context and (type(context["systemPrompt"]) is not str or not context["systemPrompt"]):
        raise ValueError
    _validate_ipython_tool(context.get("tools"))
    messages = context["messages"]
    if turn == 0:
        if not messages or any(type(item) is not dict or item.get("role") != "user" for item in messages):
            raise ValueError
        for item in messages:
            _text_content(item.get("content"))
    else:
        if len(messages) < 3 or any(type(item) is not dict for item in messages):
            raise ValueError
        for item in messages[:-2]:
            if item.get("role") != "user":
                raise ValueError
            _text_content(item.get("content"))
        _validate_tool_pair(messages[-2], messages[-1])


def _validate_ipython_tool(value: object) -> None:
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise ValueError
    tool = value[0]
    parameters = tool.get("parameters")
    if (
        tool.get("name") != "ipython" or type(tool.get("description")) is not str
        or type(parameters) is not dict or parameters.get("type") != "object"
        or parameters.get("required") != ["code"] or type(parameters.get("properties")) is not dict
        or parameters["properties"].get("code") != {"type": "string"}
    ):
        raise ValueError


def _validate_tool_pair(assistant: dict[str, object], result: dict[str, object]) -> None:
    content = assistant.get("content")
    if assistant.get("role") != "assistant" or type(content) is not list or len(content) != 1 or type(content[0]) is not dict:
        raise ValueError
    call = content[0]
    if (
        call.get("type") != "toolCall" or call.get("name") != "ipython"
        or type(call.get("id")) is not str or not call["id"]
        or type(call.get("arguments")) is not dict or set(call["arguments"]) != {"code"}
        or type(call["arguments"].get("code")) is not str or assistant.get("stopReason") != "toolUse"
    ):
        raise ValueError
    if (
        result.get("role") != "toolResult" or result.get("toolCallId") != call["id"]
        or result.get("toolName") != "ipython" or type(result.get("isError")) is not bool
    ):
        raise ValueError
    _text_content(result.get("content"))


def _text_content(value: object) -> str:
    if type(value) is str:
        if not value:
            raise ValueError
        return value
    if type(value) is not list or not value:
        raise ValueError
    texts: list[str] = []
    for block in value:
        if type(block) is not dict or set(block) != {"type", "text"} or block["type"] != "text" or type(block["text"]) is not str:
            raise ValueError
        texts.append(block["text"])
    text = "".join(texts)
    if not text:
        raise ValueError
    return text


def _deepseek_payload(request: object, model_id: str, turn: int) -> dict[str, object]:
    if type(request) is not dict or type(model_id) is not str:
        raise ValueError
    context = request["context"]
    messages: list[dict[str, object]] = []
    if "systemPrompt" in context:
        messages.append({"role": "system", "content": context["systemPrompt"]})
    source = context["messages"]
    final = source[-2:] if turn else []
    for item in source[:-2] if turn else source:
        messages.append({"role": "user", "content": _text_content(item["content"])})
    if turn:
        call = final[0]["content"][0]
        messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": call["id"], "type": "function", "function": {"name": "ipython", "arguments": _canonical_json(call["arguments"])}}]})
        messages.append({"role": "tool", "tool_call_id": call["id"], "content": _text_content(final[1]["content"])})
    tool = context["tools"][0]
    return {
        "max_tokens": _P1_MAX_OUTPUT_TOKENS,
        "messages": messages,
        "model": model_id,
        "stream": False,
        "thinking": {"type": "disabled"},
        "tool_choice": "auto",
        "tools": [{"type": "function", "function": {"name": "ipython", "description": tool["description"], "parameters": tool["parameters"]}}],
    }


def _post_chat_completion(config: _PrivatePrimeModelConfig, payload: object, timeout: float) -> object:
    request = urllib.request.Request(
        _ENDPOINT,
        data=_canonical_json(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + config.api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(_RejectRedirect())
        with opener.open(request, timeout=timeout) as response:
            if type(response.status) is not int or not 200 <= response.status < 300:
                raise ValueError
            raw = response.read(_OUTPUT_CAP + 1)
        if type(raw) is not bytes or not raw or len(raw) > _OUTPUT_CAP:
            raise ValueError
        return json.loads(raw.decode("utf-8", "strict"))
    except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError, urllib.error.URLError):
        raise ValueError from None


def _assistant_response(request: object, raw: object, turn: int) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if type(request) is not dict or type(raw) is not dict or type(raw.get("choices")) is not list or len(raw["choices"]) != 1 or type(raw.get("usage")) is not dict:
        raise ValueError
    choice = raw["choices"][0]
    usage = raw["usage"]
    if type(choice) is not dict or type(choice.get("message")) is not dict:
        raise ValueError
    input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(input_tokens) is not int or input_tokens < 0 or type(output_tokens) is not int or output_tokens < 0:
        raise ValueError
    message, finish = choice["message"], choice.get("finish_reason")
    model = request["model"]
    base = {"role": "assistant", "api": model["api"], "provider": model["provider"], "model": model["id"], "usage": _usage(input_tokens, output_tokens), "timestamp": int(time.time() * 1000)}
    calls = message.get("tool_calls")
    if turn == 0:
        if finish != "tool_calls" or message.get("content") is not None or type(calls) is not list or len(calls) != 1 or type(calls[0]) is not dict:
            raise ValueError
        tool = calls[0]
        function = tool.get("function")
        if tool.get("type") != "function" or type(tool.get("id")) is not str or not tool["id"] or type(function) is not dict or function.get("name") != "ipython" or type(function.get("arguments")) is not str:
            raise ValueError
        arguments = json.loads(function["arguments"])
        if type(arguments) is not dict or set(arguments) != {"code"} or type(arguments.get("code")) is not str:
            raise ValueError
        base.update({"content": [{"type": "toolCall", "id": tool["id"], "name": "ipython", "arguments": arguments}], "stopReason": "toolUse"})
    else:
        if calls is not None or type(message.get("content")) is not str or not message["content"] or finish not in {"stop", "length"}:
            raise ValueError
        base.update({"content": [{"type": "text", "text": message["content"]}], "stopReason": finish})
    response = _canonical_json(base).encode("utf-8")
    # The selected P1 preset reserves half of its fixed cost ceiling per
    # network request.  DeepSeek's completion response has no canonical
    # microunit charge, so this is an admitted upper bound, never a quote.
    return response, PrimeModelBrokerTokenUsage(
        input_tokens, output_tokens, _P1_MAX_COST_MICROUNITS // _MAX_REQUESTS,
    )


def _usage(input_tokens: int, output_tokens: int) -> dict[str, object]:
    return {"input": input_tokens, "output": output_tokens, "cacheRead": 0, "cacheWrite": 0, "totalTokens": input_tokens + output_tokens, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}


class _RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError


def _canonical_json(value: object) -> str:
    if value is None or type(value) in (str, bool, int):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if type(value) is float:
        raise ValueError
    if type(value) is list:
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if type(value) is dict and all(type(key) is str for key in value):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _canonical_json(value[key]) for key in sorted(value)) + "}"
    raise ValueError


def _read_exact(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, maximum + 1 - sum(map(len, chunks)))
        if not chunk:
            break
        chunks.append(chunk)
        if sum(map(len, chunks)) > maximum:
            raise ValueError
    value = b"".join(chunks)
    if not value:
        raise ValueError
    return value


def _write_all(descriptor: int | None, value: bytes) -> None:
    if type(descriptor) is not int:
        raise ValueError
    offset = 0
    while offset < len(value):
        offset += os.write(descriptor, value[offset:])


def _drain(descriptor: int, chunks: list[bytes]) -> None:
    while True:
        try:
            chunk = os.read(descriptor, _OUTPUT_CAP + _USAGE_SIZE + 6)
        except BlockingIOError:
            return
        if not chunk:
            return
        chunks.append(chunk)
        if sum(map(len, chunks)) > _OUTPUT_CAP + _USAGE_SIZE + 5:
            raise ValueError


def _decode_result(raw: bytes) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if len(raw) < 5 or raw[:1] != b"S":
        raise ValueError
    size = struct.unpack("!I", raw[1:5])[0]
    if not 0 < size <= _OUTPUT_CAP or len(raw) != 5 + size + _USAGE_SIZE:
        raise ValueError
    input_tokens, output_tokens, cost = struct.unpack("!QQQ", raw[5 + size:])
    return raw[5:5 + size], PrimeModelBrokerTokenUsage(input_tokens, output_tokens, cost)


def _close_quietly(descriptor: int | None) -> None:
    if type(descriptor) is int:
        try:
            os.close(descriptor)
        except OSError:
            pass


__all__ = (
    "PrimeP1DevelopmentSdkProvider",
    "PrimeP1DevelopmentSdkProviderError",
    "create_prime_p1_development_sdk_provider",
)
