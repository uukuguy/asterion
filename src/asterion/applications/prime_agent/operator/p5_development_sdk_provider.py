"""Private four-stage DeepSeek adapter for the structured P5 SDK bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import json
import math
import os
import re
import signal
import struct
import time

from .model_broker import PrimeModelBrokerTokenUsage
from .model_session_host import _PrivatePrimeModelConfig, _private_config_from_values
from .p1_development_sdk_provider import (
    _POLL_SECONDS,
    _REAP_GRACE_SECONDS,
    _ProviderFailure,
    _canonical_json,
    _close_quietly,
    _decode_provider_failure,
    _close_unneeded_child_fds,
    _decode_result,
    _drain,
    _encode_provider_failure,
    _post_chat_completion,
    _read_exact,
    _write_all,
)


_INPUT_CAP = 128 * 1024
_MAX_REQUESTS = 4
_TOTAL_INPUT_TOKENS = 32_768
_TOTAL_OUTPUT_TOKENS = 2_304
_TOTAL_COST_MICROUNITS = 20_000
_OUTPUT_LIMITS = (1024, 128, 1024, 128)
_REQUEST_COST_RESERVATION = 5_000
_DEADLINE_SECONDS = 180.0
_NORMAL_OPTION_KEYS = frozenset(
    {
        "apiKey",
        "maxRetries",
        "maxRetryDelayMs",
        "model",
        "serviceTier",
        "sessionId",
        "signal",
        "toolExecution",
        "transport",
    }
)
_MODEL_KEYS = frozenset(
    {
        "api",
        "baseUrl",
        "contextWindow",
        "cost",
        "id",
        "input",
        "maxTokens",
        "name",
        "provider",
        "reasoning",
    }
)

P5_PROVIDER_CALLBACK_LIMIT = _MAX_REQUESTS
P5_PROVIDER_INPUT_LIMIT = _TOTAL_INPUT_TOKENS
P5_PROVIDER_OUTPUT_LIMIT = _TOTAL_OUTPUT_TOKENS
P5_PROVIDER_COST_LIMIT = _TOTAL_COST_MICROUNITS
P5_PROVIDER_DEADLINE_SECONDS = int(_DEADLINE_SECONDS)


class PrimeP5DevelopmentSdkProviderError(ValueError):
    """Body-free P5 development SDK provider failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P5 development SDK provider is unavailable")


class PrimeP5DevelopmentSdkProvider:
    """Translate only the captured four-call P5 SDK conversation."""

    __slots__ = (
        "_calls",
        "_cancelled",
        "_child_pid",
        "_closed",
        "_cleanup_task",
        "_config",
        "_deadline",
        "_failure",
        "_issued",
        "_provisional",
        "_terminal",
        "_uncertain",
    )

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeP5DevelopmentSdkProviderError()
        self._calls = 0
        self._cancelled = False
        self._child_pid: int | None = None
        self._closed = False
        self._cleanup_task: asyncio.Task[None] | None = None
        self._config = config
        self._deadline: float | None = None
        self._failure: _ProviderFailure | None = None
        self._issued: list[tuple[dict[str, object], dict[str, object]]] = []
        self._provisional = PrimeModelBrokerTokenUsage(0, 0, 0)
        self._terminal: PrimeModelBrokerTokenUsage | None = None
        self._uncertain = False

    def __repr__(self) -> str:
        return "PrimeP5DevelopmentSdkProvider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if (
            self._closed
            or self._cancelled
            or self._child_pid is not None
            or type(body) is not bytes
            or not body
            or len(body) > _INPUT_CAP
            or self._calls >= _MAX_REQUESTS
        ):
            raise PrimeP5DevelopmentSdkProviderError()
        try:
            request = _decode_request(body, self._calls, self._issued)
        except BaseException:
            raise PrimeP5DevelopmentSdkProviderError() from None
        if self._deadline is None:
            self._deadline = time.monotonic() + _DEADLINE_SECONDS
        remaining = self._deadline - time.monotonic()
        if (
            remaining <= 0
            or self._provisional.input_tokens >= _TOTAL_INPUT_TOKENS
            or self._provisional.cost_microunits + _REQUEST_COST_RESERVATION
            > _TOTAL_COST_MICROUNITS
        ):
            raise PrimeP5DevelopmentSdkProviderError()
        turn = self._calls
        self._calls += 1
        self._uncertain = True
        self._failure = None
        request_read = request_write = result_read = result_write = None
        failed = False
        try:
            request_read, request_write = os.pipe()
            result_read, result_write = os.pipe()
            pid = os.fork()
            if pid == 0:
                _provider_child(
                    self._config,
                    request,
                    turn,
                    _OUTPUT_LIMITS[turn],
                    remaining,
                    request_read,
                    request_write,
                    result_read,
                    result_write,
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
                self._provisional.input_tokens + usage.input_tokens,
                self._provisional.output_tokens + usage.output_tokens,
                self._provisional.cost_microunits + usage.cost_microunits,
            )
            if (
                next_usage.input_tokens > _TOTAL_INPUT_TOKENS
                or next_usage.output_tokens > _TOTAL_OUTPUT_TOKENS
                or next_usage.cost_microunits > _TOTAL_COST_MICROUNITS
            ):
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
        except BaseException as error:
            if type(error) is _ProviderFailure:
                self._failure = error
            self._terminal = None
            await self._reap_shielded()
            failed = True
        finally:
            _close_quietly(request_read)
            _close_quietly(request_write)
            _close_quietly(result_read)
            _close_quietly(result_write)
        if failed:
            raise PrimeP5DevelopmentSdkProviderError() from None
        raise PrimeP5DevelopmentSdkProviderError()

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if self._uncertain or self._terminal is None:
            raise PrimeP5DevelopmentSdkProviderError()
        return self._terminal

    async def close(self) -> None:
        self._closed = True
        self._cancelled = True
        self._terminal = None
        self._uncertain = True
        await self._reap_shielded()

    async def cancel(self) -> None:
        await self.close()

    async def _receive_result(
        self, result_read: int
    ) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
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
                _drain(result_read, chunks)
                raw = b"".join(chunks)
                if not os.WIFEXITED(status):
                    raise ValueError
                if os.WEXITSTATUS(status) == 1:
                    raise _decode_provider_failure(raw)
                if os.WEXITSTATUS(status) != 0:
                    raise ValueError
                return _decode_result(raw)
            if self._deadline is None or time.monotonic() >= self._deadline:
                raise TimeoutError
            await asyncio.sleep(_POLL_SECONDS)

    async def _reap_shielded(self) -> None:
        task = self._cleanup_task
        if task is None:
            task = asyncio.create_task(self._kill_and_reap())
            self._cleanup_task = task
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
        raise PrimeP5DevelopmentSdkProviderError()


def create_prime_p5_development_sdk_provider(
    operator_config: Mapping[str, object],
) -> PrimeP5DevelopmentSdkProvider:
    try:
        return PrimeP5DevelopmentSdkProvider(
            _private_config_from_values(operator_config)
        )
    except BaseException:
        raise PrimeP5DevelopmentSdkProviderError() from None


def _provider_child(
    config: _PrivatePrimeModelConfig,
    request: dict[str, object],
    turn: int,
    max_output: int,
    timeout: float,
    request_read: int,
    request_write: int,
    result_read: int,
    result_write: int,
) -> None:
    try:
        _close_quietly(request_write)
        _close_quietly(result_read)
        _close_unneeded_child_fds(request_read, result_write)
        _read_exact(request_read, _INPUT_CAP)
        _close_quietly(request_read)
        payload = _deepseek_payload(request, config.model_id, max_output, turn=turn)
        raw = _post_chat_completion(config, payload, timeout)
        try:
            response, usage = _assistant_response(request, raw, turn, max_output)
        except ValueError:
            raise _ProviderFailure("response") from None
        _write_all(
            result_write,
            b"S"
            + struct.pack("!I", len(response))
            + response
            + struct.pack(
                "!QQQ", usage.input_tokens, usage.output_tokens, usage.cost_microunits
            ),
        )
        os._exit(0)
    except _ProviderFailure as error:
        try:
            _write_all(result_write, _encode_provider_failure(error))
        except BaseException:
            pass
        os._exit(1)
    except BaseException:
        os._exit(2)
    finally:
        _close_quietly(request_read)
        _close_quietly(request_write)
        _close_quietly(result_read)
        _close_quietly(result_write)


def _decode_request(
    body: bytes, turn: int, issued: list[tuple[dict[str, object], dict[str, object]]]
) -> dict[str, object]:
    value = json.loads(body.decode("utf-8", "strict"))
    if type(value) is not dict or _canonical_json(value).encode() != body:
        raise ValueError
    _validate_request(value, turn, issued)
    return value


def _validate_request(
    value: dict[str, object],
    turn: int,
    issued: list[tuple[dict[str, object], dict[str, object]]],
) -> None:
    if (
        set(value) != {"model", "context", "options"}
        or type(value["model"]) is not dict
        or type(value["context"]) is not dict
        or type(value["options"]) is not dict
    ):
        raise ValueError
    model, context, options = value["model"], value["context"], value["options"]
    _validate_model(model)
    if (
        set(context) != {"messages", "systemPrompt", "tools"}
        or type(context["systemPrompt"]) is not str
        or not context["systemPrompt"]
        or type(context["messages"]) is not list
    ):
        raise ValueError
    _validate_normal_options(options, model)
    _validate_tool(context["tools"])
    if turn and _canonical_json(options) != _canonical_json(issued[0][0]["options"]):
        raise ValueError
    messages = context["messages"]
    if turn == 0:
        if not messages or any(
            type(item) is not dict
            or item.get("role") != "user"
            or not _text(item.get("content"))
            for item in messages
        ):
            raise ValueError
        return
    if len(issued) != turn or _canonical_json(model) != _canonical_json(
        issued[0][0]["model"]
    ):
        raise ValueError
    if turn == 1:
        previous, answer = issued[0]
        if (
            _canonical_json(context["systemPrompt"])
            != _canonical_json(previous["context"]["systemPrompt"])
            or _canonical_json(context["tools"])
            != _canonical_json(previous["context"]["tools"])
            or _canonical_json(messages[:-2])
            != _canonical_json(previous["context"]["messages"])
            or _canonical_json(messages[-2]) != _canonical_json(answer)
        ):
            raise ValueError
        _validate_tool_pair(answer, messages[-1])
    elif turn == 2:
        initial_context = issued[0][0]["context"]
        if (
            _canonical_json(context["systemPrompt"])
            != _canonical_json(initial_context["systemPrompt"])
            or _canonical_json(context["tools"])
            != _canonical_json(initial_context["tools"])
            or not messages
            or type(messages[-1]) is not dict
            or messages[-1].get("role") != "user"
            or not _text(messages[-1].get("content"))
            or _canonical_json(issued[0][1]) not in _canonical_json(messages)
            or _canonical_json(issued[1][1]) not in _canonical_json(messages)
        ):
            raise ValueError
    else:
        previous, answer = issued[2]
        prior_context = previous["context"]
        if (
            _canonical_json(context["systemPrompt"])
            != _canonical_json(prior_context["systemPrompt"])
            or _canonical_json(context["tools"])
            != _canonical_json(prior_context["tools"])
            or _canonical_json(messages[:-2])
            != _canonical_json(prior_context["messages"])
            or _canonical_json(messages[-2]) != _canonical_json(answer)
        ):
            raise ValueError
        _validate_tool_pair(answer, messages[-1])


def _validate_normal_options(
    options: dict[str, object], model: dict[str, object]
) -> None:
    if (
        set(options) != _NORMAL_OPTION_KEYS
        or options.get("apiKey") != "in-memory-development-provider"
        or _canonical_json(options.get("model")) != _canonical_json(model)
        or options.get("maxRetries") != 0
        or options.get("maxRetryDelayMs") != 60_000
        or options.get("serviceTier") != "default"
        or options.get("signal") != {}
        or options.get("toolExecution") != "parallel"
        or options.get("transport") != "auto"
        or type(options.get("sessionId")) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", options["sessionId"]) is None
    ):
        raise ValueError


def _validate_model(model: dict[str, object]) -> None:
    if set(model) != _MODEL_KEYS:
        raise ValueError
    if any(
        type(model[key]) is not str or not model[key]
        for key in ("api", "baseUrl", "id", "name", "provider")
    ):
        raise ValueError
    if any(
        type(model[key]) is not int or not 0 < model[key] <= 2_147_483_647
        for key in ("contextWindow", "maxTokens")
    ):
        raise ValueError
    if (
        model["reasoning"] not in (True, False)
        or type(model["reasoning"]) is not bool
        or model["input"] != ["text"]
    ):
        raise ValueError
    cost = model["cost"]
    if type(cost) is not dict or set(cost) != {
        "input",
        "output",
        "cacheRead",
        "cacheWrite",
    }:
        raise ValueError
    if any(
        type(cost[key]) not in (int, float)
        or isinstance(cost[key], bool)
        or not math.isfinite(cost[key])
        or cost[key] < 0
        for key in cost
    ):
        raise ValueError


def _validate_tool(value: object) -> None:
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise ValueError
    tool = value[0]
    if (
        tool.get("name") != "ipython"
        or type(tool.get("description")) is not str
        or type(tool.get("parameters")) is not dict
        or tool["parameters"].get("type") != "object"
        or tool["parameters"].get("required") != ["code"]
        or tool["parameters"].get("properties") != {"code": {"type": "string"}}
    ):
        raise ValueError


def _validate_tool_pair(answer: dict[str, object], result: object) -> None:
    if (
        type(result) is not dict
        or answer.get("role") != "assistant"
        or answer.get("stopReason") != "toolUse"
        or type(answer.get("content")) is not list
        or len(answer["content"]) != 1
    ):
        raise ValueError
    call = answer["content"][0]
    if (
        type(call) is not dict
        or call.get("type") != "toolCall"
        or call.get("name") != "ipython"
        or type(call.get("id")) is not str
        or type(call.get("arguments")) is not dict
        or set(call["arguments"]) != {"code"}
        or type(call["arguments"].get("code")) is not str
        or result.get("role") != "toolResult"
        or result.get("toolCallId") != call["id"]
        or result.get("toolName") != "ipython"
        or type(result.get("isError")) is not bool
        or not _text(result.get("content"))
    ):
        raise ValueError


def _compaction_source(
    issued: list[tuple[dict[str, object], dict[str, object]]],
) -> list[dict[str, str]]:
    """Render the pinned SDK's sole compaction input from the first tool turn."""
    first_context = issued[0][0]["context"]
    second_context = issued[1][0]["context"]
    initial = first_context["messages"]
    continued = second_context["messages"]
    answer = issued[0][1]
    if (
        type(initial) is not list
        or len(initial) != 1
        or type(initial[0]) is not dict
        or initial[0].get("role") != "user"
        or type(continued) is not list
        or len(continued) != 3
        or _canonical_json(continued[0]) != _canonical_json(initial[0])
        or _canonical_json(continued[1]) != _canonical_json(answer)
    ):
        raise ValueError
    call = answer.get("content")
    if type(call) is not list or len(call) != 1 or type(call[0]) is not dict:
        raise ValueError
    code = call[0].get("arguments")
    if type(code) is not dict or type(code.get("code")) is not str:
        raise ValueError
    tool_result = continued[2]
    if type(tool_result) is not dict:
        raise ValueError
    source = (
        "<conversation>\n[User]: "
        + _text(initial[0].get("content"))
        + "\n\n[Assistant tool calls]: ipython(code="
        + json.dumps(code["code"], ensure_ascii=False)
        + ")\n\n[Tool result]: "
        + _text(tool_result.get("content"))
        + "\n</conversation>\n\nThis is the PREFIX of a turn that was too large to keep. "
        + "The SUFFIX (recent work) is retained.\n\nSummarize the prefix to provide context for the retained suffix:\n\n"
        + "## Original Request\n[What did the user ask for in this turn?]\n\n## Early Progress\n"
        + "- [Key decisions and work done in the prefix]\n\n## Context for Suffix\n"
        + "- [Information needed to understand the retained recent work]\n\n"
        + "Be concise. Focus on what's needed to understand the kept suffix."
    )
    return [{"type": "text", "text": source}]


def _compaction_wrapper(
    request: dict[str, object], summary: dict[str, object]
) -> list[dict[str, str]]:
    context = request["context"]
    if type(context) is not dict or type(context.get("messages")) is not list:
        raise ValueError
    source = context["messages"]
    if len(source) != 1 or type(source[0]) is not dict:
        raise ValueError
    return [
        {
            "type": "text",
            "text": "The conversation history before this point was compacted into the following summary:\n\n<summary>\nNo prior history.\n\n---\n\n**Turn Context (split turn):**\n\n"
            + _text(summary.get("content"))
            + "\n</summary>",
        }
    ]


def _text(value: object) -> str:
    if type(value) is str and value:
        return value
    if type(value) is not list or not value:
        return ""
    texts = [
        item.get("text")
        for item in value
        if type(item) is dict
        and set(item) == {"type", "text"}
        and item.get("type") == "text"
        and type(item.get("text")) is str
    ]
    return "".join(texts) if len(texts) == len(value) else ""


def _deepseek_payload(
    request: dict[str, object],
    model_id: str,
    max_output: int,
    *,
    turn: int,
) -> dict[str, object]:
    if type(turn) is not int or turn not in range(4):
        raise ValueError
    context = request.get("context")
    if type(context) is not dict or "tools" not in context:
        raise ValueError
    payload_messages: list[dict[str, object]] = [
        {"role": "system", "content": context["systemPrompt"]}
    ]
    for item in context["messages"]:
        role = item["role"]
        if role == "user":
            payload_messages.append({"role": "user", "content": _text(item["content"])})
        elif role == "assistant" and item.get("stopReason") == "toolUse":
            call = item["content"][0]
            payload_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": "ipython",
                                "arguments": _canonical_json(call["arguments"]),
                            },
                        }
                    ],
                }
            )
        elif role == "assistant":
            payload_messages.append(
                {"role": "assistant", "content": _text(item["content"])}
            )
        else:
            payload_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item["toolCallId"],
                    "content": _text(item["content"]),
                }
            )
    payload: dict[str, object] = {
        "max_tokens": max_output,
        "messages": payload_messages,
        "model": model_id,
        "stream": False,
        "thinking": {"type": "disabled"},
    }
    tool = context["tools"][0]
    payload.update(
        {
            "tool_choice": (
                {"type": "function", "function": {"name": "ipython"}}
                if turn in (0, 2)
                else "none"
            ),
            "tools": [{"type": "function", "function": {"name": "ipython", "description": tool["description"], "parameters": tool["parameters"]}}],
        }
    )
    return payload


def _assistant_response(
    request: dict[str, object], raw: object, turn: int, max_output: int
) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if (
        type(raw) is not dict
        or type(raw.get("choices")) is not list
        or len(raw["choices"]) != 1
        or type(raw.get("usage")) is not dict
        or type(raw["choices"][0]) is not dict
    ):
        raise ValueError
    choice, usage = raw["choices"][0], raw["usage"]
    if (
        type(choice.get("message")) is not dict
        or type(usage.get("prompt_tokens")) is not int
        or usage["prompt_tokens"] < 0
        or type(usage.get("completion_tokens")) is not int
        or not 0 <= usage["completion_tokens"] <= max_output
    ):
        raise ValueError
    message, model = choice["message"], request["model"]
    base: dict[str, object] = {
        "api": model["api"],
        "model": model["id"],
        "provider": model["provider"],
        "role": "assistant",
        "timestamp": int(time.time() * 1000),
        "usage": {
            "cacheRead": 0,
            "cacheWrite": 0,
            "cost": {
                "cacheRead": 0,
                "cacheWrite": 0,
                "input": 0,
                "output": 0,
                "total": 0,
            },
            "input": usage["prompt_tokens"],
            "output": usage["completion_tokens"],
            "totalTokens": usage["prompt_tokens"] + usage["completion_tokens"],
        },
    }
    if turn in (0, 2):
        calls = message.get("tool_calls")
        if (
            choice.get("finish_reason") != "tool_calls"
            or message.get("content") not in (None, "")
            or type(calls) is not list
            or len(calls) != 1
            or type(calls[0]) is not dict
            or calls[0].get("type") != "function"
            or type(calls[0].get("id")) is not str
            or type(calls[0].get("function")) is not dict
            or calls[0]["function"].get("name") != "ipython"
            or type(calls[0]["function"].get("arguments")) is not str
        ):
            raise ValueError
        arguments = json.loads(calls[0]["function"]["arguments"])
        if (
            type(arguments) is not dict
            or set(arguments) != {"code"}
            or type(arguments.get("code")) is not str
        ):
            raise ValueError
        base.update(
            {
                "content": [
                    {
                        "arguments": arguments,
                        "id": calls[0]["id"],
                        "name": "ipython",
                        "type": "toolCall",
                    }
                ],
                "stopReason": "toolUse",
            }
        )
    else:
        if (
            choice.get("finish_reason") != "stop"
            or message.get("tool_calls") is not None
            or type(message.get("content")) is not str
            or not message["content"]
        ):
            raise ValueError
        base.update(
            {
                "content": [{"text": message["content"], "type": "text"}],
                "stopReason": "stop",
            }
        )
    return _canonical_json(base).encode(), PrimeModelBrokerTokenUsage(
        usage["prompt_tokens"], usage["completion_tokens"], _REQUEST_COST_RESERVATION
    )


__all__ = (
    "PrimeP5DevelopmentSdkProvider",
    "PrimeP5DevelopmentSdkProviderError",
    "create_prime_p5_development_sdk_provider",
)
