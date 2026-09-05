"""Private five-stage DeepSeek adapter for the structured P1-B SDK bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import os
import signal
import struct
import time

from .model_broker import PrimeModelBrokerTokenUsage
from .model_session_host import _PrivatePrimeModelConfig, _private_config_from_values
from .p1_development_sdk_provider import (
    _POLL_SECONDS,
    _REAP_GRACE_SECONDS,
    _canonical_json,
    _close_quietly,
    _close_unneeded_child_fds,
    _decode_result,
    _drain,
    _post_chat_completion,
    _read_exact,
    _write_all,
)


_INPUT_CAP = 128 * 1024
_MAX_REQUESTS = 5
_TOTAL_INPUT_TOKENS = 32_768
_TOTAL_OUTPUT_TOKENS = 3_072
_TOTAL_COST_MICROUNITS = 25_000
_OUTPUT_LIMITS = (1024, 128, 768, 1024, 128)
_REQUEST_COST_RESERVATION = 5_000
_DEADLINE_SECONDS = 180.0
_NORMAL_OPTION_KEYS = frozenset({"apiKey", "maxRetries", "maxRetryDelayMs", "model", "serviceTier", "sessionId", "signal", "toolExecution", "transport"})


class PrimeP1BDevelopmentSdkProviderError(ValueError):
    """Body-free P1-B development SDK provider failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1-B development SDK provider is unavailable")


class PrimeP1BDevelopmentSdkProvider:
    """Translate only the captured five-call P1-B SDK conversation."""

    __slots__ = ("_calls", "_cancelled", "_child_pid", "_config", "_deadline", "_issued", "_provisional", "_terminal", "_uncertain")

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeP1BDevelopmentSdkProviderError()
        self._calls = 0
        self._cancelled = False
        self._child_pid: int | None = None
        self._config = config
        self._deadline: float | None = None
        self._issued: list[tuple[dict[str, object], dict[str, object]]] = []
        self._provisional = PrimeModelBrokerTokenUsage(0, 0, 0)
        self._terminal: PrimeModelBrokerTokenUsage | None = None
        self._uncertain = False

    def __repr__(self) -> str:
        return "PrimeP1BDevelopmentSdkProvider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if self._cancelled or self._child_pid is not None or type(body) is not bytes or not body or len(body) > _INPUT_CAP or self._calls >= _MAX_REQUESTS:
            raise PrimeP1BDevelopmentSdkProviderError()
        try:
            request = _decode_request(body, self._calls, self._issued)
        except BaseException:
            raise PrimeP1BDevelopmentSdkProviderError() from None
        if self._deadline is None:
            self._deadline = time.monotonic() + _DEADLINE_SECONDS
        remaining = self._deadline - time.monotonic()
        if remaining <= 0 or self._provisional.input_tokens >= _TOTAL_INPUT_TOKENS or self._provisional.cost_microunits + _REQUEST_COST_RESERVATION > _TOTAL_COST_MICROUNITS:
            raise PrimeP1BDevelopmentSdkProviderError()
        turn = self._calls
        self._calls += 1
        self._uncertain = True
        request_read = request_write = result_read = result_write = None
        try:
            request_read, request_write = os.pipe()
            result_read, result_write = os.pipe()
            pid = os.fork()
            if pid == 0:
                _provider_child(self._config, request, turn, _OUTPUT_LIMITS[turn], remaining, request_read, request_write, result_read, result_write)
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
            next_usage = PrimeModelBrokerTokenUsage(self._provisional.input_tokens + usage.input_tokens, self._provisional.output_tokens + usage.output_tokens, self._provisional.cost_microunits + usage.cost_microunits)
            if next_usage.input_tokens > _TOTAL_INPUT_TOKENS or next_usage.output_tokens > _TOTAL_OUTPUT_TOKENS or next_usage.cost_microunits > _TOTAL_COST_MICROUNITS:
                raise ValueError
            reply = json.loads(response.decode("utf-8", "strict"))
            if type(reply) is not dict:
                raise ValueError
            self._issued.append((request, reply))
            self._provisional = next_usage
            if self._calls == _MAX_REQUESTS:
                self._terminal = next_usage
                self._uncertain = False
            return response
        except asyncio.CancelledError:
            self._cancelled = True
            self._terminal = None
            await self._reap_shielded()
            raise
        except BaseException:
            self._terminal = None
            await self._reap_shielded()
            raise PrimeP1BDevelopmentSdkProviderError() from None
        finally:
            _close_quietly(request_read)
            _close_quietly(request_write)
            _close_quietly(result_read)
            _close_quietly(result_write)

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if self._uncertain or self._terminal is None:
            raise PrimeP1BDevelopmentSdkProviderError()
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
        raise PrimeP1BDevelopmentSdkProviderError()


def create_prime_p1b_development_sdk_provider(operator_config: Mapping[str, object]) -> PrimeP1BDevelopmentSdkProvider:
    try:
        return PrimeP1BDevelopmentSdkProvider(_private_config_from_values(operator_config))
    except BaseException:
        raise PrimeP1BDevelopmentSdkProviderError() from None


def _provider_child(config: _PrivatePrimeModelConfig, request: dict[str, object], turn: int, max_output: int, timeout: float, request_read: int, request_write: int, result_read: int, result_write: int) -> None:
    try:
        _close_quietly(request_write)
        _close_quietly(result_read)
        _close_unneeded_child_fds(request_read, result_write)
        _read_exact(request_read, _INPUT_CAP)
        _close_quietly(request_read)
        payload = _deepseek_payload(request, config.model_id, max_output)
        raw = _post_chat_completion(config, payload, timeout)
        response, usage = _assistant_response(request, raw, turn, max_output)
        _write_all(result_write, b"S" + struct.pack("!I", len(response)) + response + struct.pack("!QQQ", usage.input_tokens, usage.output_tokens, usage.cost_microunits))
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


def _decode_request(body: bytes, turn: int, issued: list[tuple[dict[str, object], dict[str, object]]]) -> dict[str, object]:
    value = json.loads(body.decode("utf-8", "strict"))
    if type(value) is not dict or _canonical_json(value).encode() != body:
        raise ValueError
    _validate_request(value, turn, issued)
    return value


def _validate_request(value: dict[str, object], turn: int, issued: list[tuple[dict[str, object], dict[str, object]]]) -> None:
    if set(value) != {"model", "context", "options"} or type(value["model"]) is not dict or type(value["context"]) is not dict or type(value["options"]) is not dict:
        raise ValueError
    model, context, options = value["model"], value["context"], value["options"]
    if set(model) != {"api", "provider", "id"} or any(type(model[key]) is not str or not model[key] for key in model):
        raise ValueError
    compact = turn == 2
    if set(context) != ({"messages", "systemPrompt"} if compact else {"messages", "systemPrompt", "tools"}) or type(context["systemPrompt"]) is not str or not context["systemPrompt"] or type(context["messages"]) is not list:
        raise ValueError
    if compact:
        if options != {"apiKey": "in-memory-development-provider", "maxTokens": 768, "signal": {}}:
            raise ValueError
    else:
        _validate_normal_options(options, model)
        _validate_tool(context["tools"])
        if turn and _canonical_json(options) != _canonical_json(issued[0][0]["options"]):
            raise ValueError
    messages = context["messages"]
    if turn == 0:
        if not messages or any(type(item) is not dict or item.get("role") != "user" or not _text(item.get("content")) for item in messages):
            raise ValueError
        return
    if len(issued) != turn or _canonical_json(model) != _canonical_json(issued[0][0]["model"]):
        raise ValueError
    if compact:
        if not messages or any(type(item) is not dict or item.get("role") != "user" or not _text(item.get("content")) for item in messages):
            raise ValueError
    elif turn == 1:
        previous, answer = issued[0]
        if _canonical_json(context["systemPrompt"]) != _canonical_json(previous["context"]["systemPrompt"]) or _canonical_json(context["tools"]) != _canonical_json(previous["context"]["tools"]) or _canonical_json(messages[:-2]) != _canonical_json(previous["context"]["messages"]) or _canonical_json(messages[-2]) != _canonical_json(answer):
            raise ValueError
        _validate_tool_pair(answer, messages[-1])
    elif turn == 3:
        summary = issued[2][1]
        if len(messages) != 3 or [item.get("role") if type(item) is dict else None for item in messages] != ["user", "assistant", "user"] or _canonical_json(messages[1]) != _canonical_json(summary) or not _text(messages[0].get("content")) or not _text(messages[2].get("content")):
            raise ValueError
    else:
        previous, answer = issued[3]
        if _canonical_json(messages[:-2]) != _canonical_json(previous["context"]["messages"]) or _canonical_json(messages[-2]) != _canonical_json(answer):
            raise ValueError
        _validate_tool_pair(answer, messages[-1])


def _validate_normal_options(options: dict[str, object], model: dict[str, object]) -> None:
    if set(options) != _NORMAL_OPTION_KEYS or options.get("apiKey") != "in-memory-development-provider" or _canonical_json(options.get("model")) != _canonical_json(model) or options.get("maxRetries") != 0 or options.get("maxRetryDelayMs") != 60_000 or options.get("serviceTier") != "default" or options.get("signal") != {} or options.get("toolExecution") != "parallel" or options.get("transport") != "auto" or type(options.get("sessionId")) is not str or not options["sessionId"]:
        raise ValueError


def _validate_tool(value: object) -> None:
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise ValueError
    tool = value[0]
    if tool.get("name") != "ipython" or type(tool.get("description")) is not str or type(tool.get("parameters")) is not dict or tool["parameters"].get("type") != "object" or tool["parameters"].get("required") != ["code"] or tool["parameters"].get("properties") != {"code": {"type": "string"}}:
        raise ValueError


def _validate_tool_pair(answer: dict[str, object], result: object) -> None:
    if type(result) is not dict or answer.get("role") != "assistant" or answer.get("stopReason") != "toolUse" or type(answer.get("content")) is not list or len(answer["content"]) != 1:
        raise ValueError
    call = answer["content"][0]
    if type(call) is not dict or call.get("type") != "toolCall" or call.get("name") != "ipython" or type(call.get("id")) is not str or type(call.get("arguments")) is not dict or set(call["arguments"]) != {"code"} or type(call["arguments"].get("code")) is not str or result.get("role") != "toolResult" or result.get("toolCallId") != call["id"] or result.get("toolName") != "ipython" or type(result.get("isError")) is not bool or not _text(result.get("content")):
        raise ValueError


def _text(value: object) -> str:
    if type(value) is str and value:
        return value
    if type(value) is not list or not value:
        return ""
    texts = [item.get("text") for item in value if type(item) is dict and set(item) == {"type", "text"} and item.get("type") == "text" and type(item.get("text")) is str]
    return "".join(texts) if len(texts) == len(value) else ""


def _deepseek_payload(request: dict[str, object], model_id: str, max_output: int) -> dict[str, object]:
    context = request["context"]
    payload_messages: list[dict[str, object]] = [{"role": "system", "content": context["systemPrompt"]}]
    for item in context["messages"]:
        role = item["role"]
        if role == "user":
            payload_messages.append({"role": "user", "content": _text(item["content"])})
        elif role == "assistant" and item.get("stopReason") == "toolUse":
            call = item["content"][0]
            payload_messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": call["id"], "type": "function", "function": {"name": "ipython", "arguments": _canonical_json(call["arguments"])}}]})
        elif role == "assistant":
            payload_messages.append({"role": "assistant", "content": _text(item["content"])})
        else:
            payload_messages.append({"role": "tool", "tool_call_id": item["toolCallId"], "content": _text(item["content"])})
    payload: dict[str, object] = {"max_tokens": max_output, "messages": payload_messages, "model": model_id, "stream": False, "thinking": {"type": "disabled"}}
    if "tools" in context:
        tool = context["tools"][0]
        payload.update({"tool_choice": "auto", "tools": [{"type": "function", "function": {"name": "ipython", "description": tool["description"], "parameters": tool["parameters"]}}]})
    return payload


def _assistant_response(request: dict[str, object], raw: object, turn: int, max_output: int) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if type(raw) is not dict or type(raw.get("choices")) is not list or len(raw["choices"]) != 1 or type(raw.get("usage")) is not dict or type(raw["choices"][0]) is not dict:
        raise ValueError
    choice, usage = raw["choices"][0], raw["usage"]
    if type(choice.get("message")) is not dict or type(usage.get("prompt_tokens")) is not int or usage["prompt_tokens"] < 0 or type(usage.get("completion_tokens")) is not int or not 0 <= usage["completion_tokens"] <= max_output:
        raise ValueError
    message, model = choice["message"], request["model"]
    base: dict[str, object] = {"api": model["api"], "model": model["id"], "provider": model["provider"], "role": "assistant", "timestamp": int(time.time() * 1000), "usage": {"cacheRead": 0, "cacheWrite": 0, "cost": {"cacheRead": 0, "cacheWrite": 0, "input": 0, "output": 0, "total": 0}, "input": usage["prompt_tokens"], "output": usage["completion_tokens"], "totalTokens": usage["prompt_tokens"] + usage["completion_tokens"]}}
    if turn in (0, 3):
        calls = message.get("tool_calls")
        if choice.get("finish_reason") != "tool_calls" or message.get("content") not in (None, "") or type(calls) is not list or len(calls) != 1 or type(calls[0]) is not dict or calls[0].get("type") != "function" or type(calls[0].get("id")) is not str or type(calls[0].get("function")) is not dict or calls[0]["function"].get("name") != "ipython" or type(calls[0]["function"].get("arguments")) is not str:
            raise ValueError
        arguments = json.loads(calls[0]["function"]["arguments"])
        if type(arguments) is not dict or set(arguments) != {"code"} or type(arguments.get("code")) is not str:
            raise ValueError
        base.update({"content": [{"arguments": arguments, "id": calls[0]["id"], "name": "ipython", "type": "toolCall"}], "stopReason": "toolUse"})
    else:
        if choice.get("finish_reason") != "stop" or message.get("tool_calls") is not None or type(message.get("content")) is not str or not message["content"]:
            raise ValueError
        base.update({"content": [{"text": message["content"], "type": "text"}], "stopReason": "stop"})
    return _canonical_json(base).encode(), PrimeModelBrokerTokenUsage(usage["prompt_tokens"], usage["completion_tokens"], _REQUEST_COST_RESERVATION)


__all__ = ("PrimeP1BDevelopmentSdkProvider", "PrimeP1BDevelopmentSdkProviderError", "create_prime_p1b_development_sdk_provider")
