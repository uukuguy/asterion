"""Bounded DeepSeek conversation adapter for one autonomous P7 solve."""

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
from typing import cast

from .model_broker import PrimeModelBrokerTokenUsage
from .model_session_host import _PrivatePrimeModelConfig, _private_config_from_values
from .p1_development_sdk_provider import (
    _POLL_SECONDS,
    _REAP_GRACE_SECONDS,
    _ProviderFailure,
    _canonical_json,
    _close_quietly,
    _close_unneeded_child_fds,
    _decode_provider_failure,
    _decode_result,
    _drain,
    _encode_provider_failure,
    _post_chat_completion,
    _read_exact,
    _write_all,
)

P7_SOLVING_PROVIDER_REQUEST_BYTES = 8_388_608
P7_SOLVING_PROVIDER_CALLBACK_LIMIT = 128
P7_SOLVING_PROVIDER_INPUT_LIMIT = 2_000_000
P7_SOLVING_PROVIDER_OUTPUT_LIMIT = 200_000
P7_SOLVING_PROVIDER_COST_LIMIT = 5_000_000
P7_SOLVING_PROVIDER_DEADLINE_SECONDS = 3_600
P7_SOLVING_PROVIDER_CALLBACK_OUTPUT_LIMIT = 4_096
_REQUEST_COST_RESERVATION = 39_062
_NORMAL_OPTION_KEYS = frozenset(
    {"apiKey", "maxRetries", "maxRetryDelayMs", "model", "serviceTier", "sessionId", "signal", "toolExecution", "transport"}
)
_MODEL_KEYS = frozenset(
    {"api", "baseUrl", "contextWindow", "cost", "id", "input", "maxTokens", "name", "provider", "reasoning"}
)
_SUMMARY_OPTION_KEYS = frozenset({"apiKey", "maxTokens", "signal"})
_COMPACTION_PREFIX = "The conversation history before this point was compacted into the following summary:\n\n<summary>\n"
_COMPACTION_SUFFIX = "\n</summary>"
_TURN_PREFIX_MARKER = "This is the PREFIX of a turn that was too large to keep."


class PrimeP7SolvingSdkProviderError(ValueError):
    """Body-free provider failure."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P7 solving SDK provider is unavailable")


class PrimeP7SolvingSdkProvider:
    """Serialize and account all normal and compaction callbacks for one solve."""

    __slots__ = (
        "_calls", "_normal_calls", "_summary_calls", "_inflight", "_lock",
        "_cancelled", "_child_pid", "_closed", "_cleanup_task", "_config",
        "_deadline", "_failure", "_issued", "_last_normal", "_pending_summaries",
        "_accepted_compaction", "_provisional", "_terminal", "_finalized", "_uncertain",
    )

    def __init__(self, config: _PrivatePrimeModelConfig) -> None:
        if type(config) is not _PrivatePrimeModelConfig:
            raise PrimeP7SolvingSdkProviderError()
        self._calls = self._normal_calls = self._summary_calls = self._inflight = 0
        self._lock = asyncio.Lock()
        self._cancelled = self._closed = self._finalized = self._uncertain = False
        self._child_pid: int | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._config = config
        self._deadline: float | None = None
        self._failure: _ProviderFailure | None = None
        self._issued: list[tuple[dict[str, object], dict[str, object], str]] = []
        self._last_normal: tuple[dict[str, object], dict[str, object]] | None = None
        self._pending_summaries: list[tuple[dict[str, object], dict[str, object], str, str, str | None]] = []
        self._accepted_compaction: tuple[str, str] | None = None
        self._provisional = PrimeModelBrokerTokenUsage(0, 0, 0)
        self._terminal: PrimeModelBrokerTokenUsage | None = None

    def __repr__(self) -> str:
        return "PrimeP7SolvingSdkProvider(redacted)"

    async def __call__(self, body: bytes) -> bytes:
        if (
            type(body) is not bytes or not body
            or len(body) > P7_SOLVING_PROVIDER_REQUEST_BYTES
            or self._closed or self._cancelled or self._finalized
        ):
            raise PrimeP7SolvingSdkProviderError()
        self._inflight += 1
        try:
            async with self._lock:
                return await self._call_serial(body)
        finally:
            self._inflight -= 1

    async def _call_serial(self, body: bytes) -> bytes:
        if (
            self._closed or self._cancelled or self._finalized
            or self._child_pid is not None
            or self._calls >= P7_SOLVING_PROVIDER_CALLBACK_LIMIT
        ):
            raise PrimeP7SolvingSdkProviderError()
        try:
            request, callback_kind = _decode_request(
                body, self._last_normal, self._pending_summaries,
                self._accepted_compaction,
            )
        except BaseException:
            raise PrimeP7SolvingSdkProviderError() from None
        if self._deadline is None:
            self._deadline = time.monotonic() + P7_SOLVING_PROVIDER_DEADLINE_SECONDS
        remaining = self._deadline - time.monotonic()
        if (
            remaining <= 0
            or self._provisional.input_tokens >= P7_SOLVING_PROVIDER_INPUT_LIMIT
            or self._provisional.output_tokens >= P7_SOLVING_PROVIDER_OUTPUT_LIMIT
            or self._provisional.cost_microunits + _REQUEST_COST_RESERVATION > P7_SOLVING_PROVIDER_COST_LIMIT
        ):
            raise PrimeP7SolvingSdkProviderError()
        self._calls += 1
        if callback_kind == "normal":
            self._normal_calls += 1
        else:
            self._summary_calls += 1
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
                    self._config, request, callback_kind, remaining,
                    request_read, request_write, result_read, result_write,
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
                next_usage.input_tokens > P7_SOLVING_PROVIDER_INPUT_LIMIT
                or next_usage.output_tokens > P7_SOLVING_PROVIDER_OUTPUT_LIMIT
                or next_usage.cost_microunits > P7_SOLVING_PROVIDER_COST_LIMIT
            ):
                raise ValueError
            reply = json.loads(response.decode("utf-8", "strict"))
            if type(reply) is not dict:
                raise ValueError
            self._issued.append((request, reply, callback_kind))
            if callback_kind == "normal":
                self._last_normal = (request, reply)
                self._pending_summaries.clear()
                self._accepted_compaction = None
            else:
                summary_kind, transcript, previous_summary = _summary_span(request)
                self._pending_summaries.append(
                    (request, reply, summary_kind, transcript, previous_summary)
                )
            self._provisional = next_usage
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
            raise PrimeP7SolvingSdkProviderError() from None
        raise PrimeP7SolvingSdkProviderError()

    def accept_compaction(
        self, *, replaced_messages: object, replacement_messages: object,
        summary_spans: object | None = None,
    ) -> None:
        """Validate an explicit SDK compaction transition before the next callback."""
        try:
            if (
                self._inflight or self._finalized or not self._pending_summaries
                or self._accepted_compaction is not None
            ):
                raise ValueError
            if type(replaced_messages) is not list or type(replacement_messages) is not list:
                raise ValueError
            if summary_spans is not None:
                _validate_summary_spans(summary_spans, self._pending_summaries)
            _validate_normal_history(replaced_messages, self._last_normal, [], None)
            expected = _compaction_transition(
                replaced_messages, replacement_messages, self._pending_summaries
            )
            self._accepted_compaction = (
                _canonical_json(replaced_messages), _canonical_json(expected)
            )
        except BaseException:
            raise PrimeP7SolvingSdkProviderError() from None

    def finalize(self) -> PrimeModelBrokerTokenUsage:
        if (
            self._closed or self._cancelled or self._finalized or self._inflight
            or self._child_pid is not None or self._uncertain
        ):
            raise PrimeP7SolvingSdkProviderError()
        self._finalized = True
        self._terminal = self._provisional
        return self._terminal

    def terminal_usage(self) -> PrimeModelBrokerTokenUsage:
        if self._terminal is None or not self._finalized:
            raise PrimeP7SolvingSdkProviderError()
        return self._terminal

    def callback_counts(self) -> dict[str, int]:
        return {"normal": self._normal_calls, "summary": self._summary_calls}

    async def close(self) -> None:
        self._closed = True
        self._cancelled = True
        self._terminal = None
        self._uncertain = True
        await self._reap_shielded()

    async def cancel(self) -> None:
        await self.close()

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
        if task is None or task.done():
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
        raise PrimeP7SolvingSdkProviderError()


def create_prime_p7_solving_sdk_provider(
    operator_config: Mapping[str, object],
) -> PrimeP7SolvingSdkProvider:
    try:
        return PrimeP7SolvingSdkProvider(_private_config_from_values(operator_config))
    except BaseException:
        raise PrimeP7SolvingSdkProviderError() from None


def _provider_child(
    config: _PrivatePrimeModelConfig,
    request: dict[str, object],
    callback_kind: str,
    timeout: float,
    request_read: int,
    request_write: int,
    result_read: int,
    result_write: int,
) -> None:
    try:
        os.environ.clear()
        _close_quietly(request_write)
        _close_quietly(result_read)
        _close_unneeded_child_fds(request_read, result_write)
        _read_exact(request_read, P7_SOLVING_PROVIDER_REQUEST_BYTES)
        _close_quietly(request_read)
        payload = _deepseek_payload(request, config.model_id, callback_kind)
        raw = _post_chat_completion(config, payload, timeout)
        try:
            response, usage = _assistant_response(request, raw, callback_kind)
        except ValueError:
            raise _ProviderFailure("response") from None
        _write_all(
            result_write,
            b"S" + struct.pack("!I", len(response)) + response
            + struct.pack("!QQQ", usage.input_tokens, usage.output_tokens, usage.cost_microunits),
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
    body: bytes,
    last_normal: tuple[dict[str, object], dict[str, object]] | None,
    summaries: list[tuple[dict[str, object], dict[str, object], str, str, str | None]],
    accepted_compaction: tuple[str, str] | None,
) -> tuple[dict[str, object], str]:
    value = json.loads(body.decode("utf-8", "strict"))
    if type(value) is not dict or _canonical_json(value).encode() != body:
        raise ValueError
    kind = _validate_request(value, last_normal, summaries, accepted_compaction)
    return value, kind


def _validate_request(
    value: dict[str, object],
    last_normal: tuple[dict[str, object], dict[str, object]] | None,
    summaries: list[tuple[dict[str, object], dict[str, object], str, str, str | None]],
    accepted_compaction: tuple[str, str] | None,
) -> str:
    if set(value) != {"model", "context", "options"} or type(value["model"]) is not dict or type(value["context"]) is not dict or type(value["options"]) is not dict:
        raise ValueError
    model, context, options = value["model"], value["context"], value["options"]
    _validate_model(model)
    if type(context.get("systemPrompt")) is not str or not context["systemPrompt"] or type(context.get("messages")) is not list:
        raise ValueError
    if "tools" not in context:
        if accepted_compaction is not None or set(context) != {"messages", "systemPrompt"} or set(options) != _SUMMARY_OPTION_KEYS or options.get("apiKey") != "in-memory-solving-provider" or options.get("signal") != {} or type(options.get("maxTokens")) is not int or not 0 < options["maxTokens"] <= P7_SOLVING_PROVIDER_CALLBACK_OUTPUT_LIMIT:
            raise ValueError
        _validate_summary_source(context["messages"])
        return "summary"
    if set(context) != {"messages", "systemPrompt", "tools"}:
        raise ValueError
    _validate_normal_options(options, model)
    _validate_tool(context["tools"])
    _validate_normal_history(
        context["messages"], last_normal, summaries, accepted_compaction
    )
    return "normal"


def _validate_model(model: dict[str, object]) -> None:
    if set(model) != _MODEL_KEYS or any(type(model[key]) is not str or not model[key] for key in ("api", "baseUrl", "id", "name", "provider")):
        raise ValueError
    if model["contextWindow"] != 131_072 or model["maxTokens"] != 4_096 or model["reasoning"] is not False or model["input"] != ["text"]:
        raise ValueError
    provider = model["provider"]
    if type(provider) is not str or re.fullmatch(r"asterion-p7-solving-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", provider) is None:
        raise ValueError
    suffix = provider.removeprefix("asterion-p7-solving-")
    if model["api"] != provider or model["id"] != f"p7-solving-{suffix}" or model["name"] != model["id"] or model["baseUrl"] != "http://127.0.0.1:0":
        raise ValueError
    cost = model["cost"]
    if type(cost) is not dict or set(cost) != {"input", "output", "cacheRead", "cacheWrite"} or any(type(cost[key]) not in (int, float) or isinstance(cost[key], bool) or not math.isfinite(cost[key]) or cost[key] < 0 for key in cost):
        raise ValueError


def _validate_normal_options(options: dict[str, object], model: dict[str, object]) -> None:
    session_id = options.get("sessionId")
    if (
        set(options) != _NORMAL_OPTION_KEYS
        or options.get("apiKey") != "in-memory-solving-provider"
        or _canonical_json(options.get("model")) != _canonical_json(model)
        or options.get("maxRetries") != 0 or options.get("maxRetryDelayMs") != 60_000
        or options.get("serviceTier") != "default" or options.get("signal") != {}
        or options.get("toolExecution") != "parallel" or options.get("transport") != "auto"
        or type(session_id) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id) is None
    ):
        raise ValueError


def _validate_tool(value: object) -> None:
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise ValueError
    tool = value[0]
    if tool.get("name") != "ipython" or type(tool.get("description")) is not str or not tool["description"] or type(tool.get("parameters")) is not dict or tool["parameters"].get("type") != "object" or tool["parameters"].get("required") != ["code"] or tool["parameters"].get("properties") != {"code": {"type": "string"}}:
        raise ValueError


def _validate_normal_history(
    messages: object,
    last_normal: tuple[dict[str, object], dict[str, object]] | None,
    summaries: list[tuple[dict[str, object], dict[str, object], str, str, str | None]],
    accepted_compaction: tuple[str, str] | None,
) -> None:
    if type(messages) is not list or not messages or any(type(item) is not dict for item in messages):
        raise ValueError
    if accepted_compaction is not None:
        if _canonical_json(messages) != accepted_compaction[1]:
            raise ValueError
        return
    if last_normal is None:
        if any(item.get("role") != "user" or not _text(item.get("content")) for item in messages):
            raise ValueError
        return
    previous, answer = last_normal
    context = previous["context"]
    if type(context) is not dict or type(context.get("messages")) is not list:
        raise ValueError
    old = context["messages"]
    if len(messages) >= len(old) + 2 and _canonical_json(messages[: len(old)]) == _canonical_json(old) and _canonical_json(messages[len(old)]) == _canonical_json(answer):
        results = messages[len(old) + 1 :]
        _validate_tool_results(answer, results)
        return
    if summaries:
        raise ValueError
    raise ValueError


def _validate_tool_results(answer: dict[str, object], results: list[object]) -> None:
    calls = answer.get("content")
    if type(calls) is not list:
        raise ValueError
    calls = [item for item in calls if type(item) is dict and item.get("type") == "toolCall"]
    if not calls or len(results) != len(calls):
        raise ValueError
    for call, result in zip(calls, results, strict=True):
        if type(result) is not dict or result.get("role") != "toolResult" or result.get("toolCallId") != call.get("id") or result.get("toolName") != "ipython" or type(result.get("isError")) is not bool or not _text(result.get("content")):
            raise ValueError


def _validate_summary_source(messages: object) -> None:
    if type(messages) is not list or len(messages) != 1 or type(messages[0]) is not dict or messages[0].get("role") != "user":
        raise ValueError
    source = _text(messages[0].get("content"))
    if not source:
        raise ValueError
    _parse_summary_source(source)


def _summary_span(
    request: dict[str, object],
) -> tuple[str, str, str | None]:
    context = request.get("context")
    if type(context) is not dict or type(context.get("messages")) is not list:
        raise ValueError
    messages = context["messages"]
    if len(messages) != 1 or type(messages[0]) is not dict:
        raise ValueError
    return _parse_summary_source(_text(messages[0].get("content")))


def _parse_summary_source(source: str) -> tuple[str, str, str | None]:
    opening = "<conversation>\n"
    closing = "\n</conversation>\n\n"
    if not source.startswith(opening):
        raise ValueError
    close_at = source.rfind(closing)
    if close_at <= len(opening):
        raise ValueError
    transcript = source[len(opening):close_at]
    instructions = source[close_at + len(closing):]
    previous_summary: str | None = None
    previous_open = "<previous-summary>\n"
    previous_close = "\n</previous-summary>\n\n"
    if instructions.startswith(previous_open):
        previous_end = instructions.find(previous_close, len(previous_open))
        if previous_end <= len(previous_open):
            raise ValueError
        previous_summary = instructions[len(previous_open):previous_end]
        instructions = instructions[previous_end + len(previous_close):]
    if not instructions:
        raise ValueError
    kind = "turn-prefix" if instructions.startswith(_TURN_PREFIX_MARKER) else "history"
    if kind == "turn-prefix" and previous_summary is not None:
        raise ValueError
    return kind, transcript, previous_summary


def _compaction_transition(
    replaced_messages: list[object],
    replacement_messages: list[object],
    summaries: list[tuple[dict[str, object], dict[str, object], str, str, str | None]],
) -> list[object]:
    if not 0 < len(summaries) <= 2:
        raise ValueError
    by_kind = {summary[2]: summary for summary in summaries}
    if len(by_kind) != len(summaries) or any(kind not in {"history", "turn-prefix"} for kind in by_kind):
        raise ValueError
    ordered = [by_kind[kind] for kind in ("history", "turn-prefix") if kind in by_kind]
    cursor = 0
    history = by_kind.get("history")
    if history is not None and history[4] is not None:
        previous_wrapper = _compaction_wrapper(history[4])
        if not replaced_messages or _canonical_json(replaced_messages[0]) != _canonical_json(previous_wrapper):
            raise ValueError
        cursor = 1
    for _, _, _, transcript, _ in ordered:
        matches = [
            end for end in range(cursor + 1, len(replaced_messages) + 1)
            if _serialize_compaction_messages(replaced_messages[cursor:end]) == transcript
        ]
        if len(matches) != 1:
            raise ValueError
        cursor = matches[0]
    history_text = _text(history[1].get("content")) if history is not None else "No prior history."
    turn = by_kind.get("turn-prefix")
    if turn is None:
        merged = history_text
    else:
        turn_text = _text(turn[1].get("content"))
        if not history_text or not turn_text:
            raise ValueError
        merged = f"{history_text}\n\n---\n\n**Turn Context (split turn):**\n\n{turn_text}"
    expected: list[object] = [_compaction_wrapper(merged), *replaced_messages[cursor:]]
    if _canonical_json(replacement_messages) != _canonical_json(expected):
        raise ValueError
    return expected


def _validate_summary_spans(
    value: object,
    summaries: list[tuple[dict[str, object], dict[str, object], str, str, str | None]],
) -> None:
    if type(value) is not list or len(value) != len(summaries):
        raise ValueError
    expected = [
        {"kind": kind, "transcript": transcript, "previous_summary": previous}
        for _, _, kind, transcript, previous in summaries
    ]
    if _canonical_json(value) != _canonical_json(expected):
        raise ValueError


def _compaction_wrapper(summary: str) -> dict[str, object]:
    if not summary:
        raise ValueError
    return {
        "role": "user",
        "content": [{"type": "text", "text": _COMPACTION_PREFIX + summary + _COMPACTION_SUFFIX}],
    }


def _serialize_compaction_messages(messages: list[object]) -> str:
    if not messages:
        raise ValueError
    rendered: list[str] = []
    for message in messages:
        if type(message) is not dict:
            raise ValueError
        role = message.get("role")
        content = message.get("content")
        if role == "user":
            text = _text(content)
            if not text:
                raise ValueError
            rendered.append(f"[User]: {text}")
        elif role == "assistant":
            if type(content) is not list:
                raise ValueError
            texts: list[str] = []
            thinking: list[str] = []
            calls: list[str] = []
            for block in content:
                if type(block) is not dict:
                    raise ValueError
                if block.get("type") == "text" and type(block.get("text")) is str:
                    texts.append(block["text"])
                elif block.get("type") == "thinking" and type(block.get("thinking")) is str:
                    thinking.append(block["thinking"])
                elif block.get("type") == "toolCall" and type(block.get("name")) is str and type(block.get("arguments")) is dict:
                    arguments = ", ".join(
                        f"{key}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))}"
                        for key, value in block["arguments"].items()
                    )
                    calls.append(f"{block['name']}({arguments})")
                else:
                    raise ValueError
            if thinking:
                rendered.append("[Assistant thinking]: " + "\n".join(thinking))
            if texts:
                rendered.append("[Assistant]: " + "\n".join(texts))
            if calls:
                rendered.append(f"[Assistant tool calls]: {'; '.join(calls)}")
            if not thinking and not texts and not calls:
                raise ValueError
        elif role == "toolResult":
            text = _text(content)
            if not text:
                raise ValueError
            if len(text) > 2_000:
                text = f"{text[:2_000]}\n\n[... {len(text) - 2_000} more characters truncated]"
            rendered.append(f"[Tool result]: {text}")
        else:
            raise ValueError
    return "\n\n".join(rendered)


def _deepseek_payload(
    request: dict[str, object], model_id: str, callback_kind: str
) -> dict[str, object]:
    context = request["context"]
    if type(context) is not dict or callback_kind not in {"normal", "summary"}:
        raise ValueError
    payload_messages: list[dict[str, object]] = [{"role": "system", "content": context["systemPrompt"]}]
    for item in context["messages"]:
        if type(item) is not dict:
            raise ValueError
        role = item.get("role")
        if role == "user":
            payload_messages.append({"role": "user", "content": _text(item.get("content"))})
        elif role == "assistant":
            content = item.get("content")
            if type(content) is not list:
                raise ValueError
            calls = [part for part in content if type(part) is dict and part.get("type") == "toolCall"]
            texts = [part["text"] for part in content if type(part) is dict and part.get("type") == "text" and type(part.get("text")) is str]
            converted: dict[str, object] = {"role": "assistant", "content": "".join(texts) or None}
            if calls:
                converted["tool_calls"] = [{"id": call["id"], "type": "function", "function": {"name": "ipython", "arguments": _canonical_json(call["arguments"])}} for call in calls]
            payload_messages.append(converted)
        elif role == "toolResult":
            payload_messages.append({"role": "tool", "tool_call_id": item["toolCallId"], "content": _text(item.get("content"))})
        else:
            raise ValueError
    options = request["options"]
    if type(options) is not dict:
        raise ValueError
    max_tokens = options.get("maxTokens", P7_SOLVING_PROVIDER_CALLBACK_OUTPUT_LIMIT)
    payload: dict[str, object] = {"max_tokens": max_tokens, "messages": payload_messages, "model": model_id, "stream": False, "temperature": 0, "thinking": {"type": "disabled"}}
    if callback_kind == "normal":
        tools = context["tools"]
        if type(tools) is not list or not tools or type(tools[0]) is not dict:
            raise ValueError
        tool = tools[0]
        payload.update({"tool_choice": "auto", "tools": [{"type": "function", "function": {"name": "ipython", "description": tool["description"], "parameters": tool["parameters"]}}]})
    return payload


def _assistant_response(
    request: dict[str, object], raw: object, callback_kind: str
) -> tuple[bytes, PrimeModelBrokerTokenUsage]:
    if type(raw) is not dict or type(raw.get("choices")) is not list or len(raw["choices"]) != 1 or type(raw.get("usage")) is not dict or type(raw["choices"][0]) is not dict:
        raise ValueError
    choice, usage = raw["choices"][0], raw["usage"]
    if type(choice.get("message")) is not dict or type(usage.get("prompt_tokens")) is not int or usage["prompt_tokens"] < 0 or type(usage.get("completion_tokens")) is not int or not 0 <= usage["completion_tokens"] <= P7_SOLVING_PROVIDER_CALLBACK_OUTPUT_LIMIT:
        raise ValueError
    message = cast(dict[str, object], choice["message"])
    model_value = request["model"]
    if type(model_value) is not dict:
        raise ValueError
    model = model_value
    base: dict[str, object] = {
        "api": model["api"], "model": model["id"], "provider": model["provider"], "role": "assistant", "timestamp": int(time.time() * 1000),
        "usage": {"cacheRead": 0, "cacheWrite": 0, "cost": {"cacheRead": 0, "cacheWrite": 0, "input": 0, "output": 0, "total": 0}, "input": usage["prompt_tokens"], "output": usage["completion_tokens"], "totalTokens": usage["prompt_tokens"] + usage["completion_tokens"]},
    }
    text = message.get("content")
    calls = message.get("tool_calls")
    content: list[dict[str, object]] = []
    if type(text) is str and text:
        content.append({"text": text, "type": "text"})
    if callback_kind == "summary":
        if choice.get("finish_reason") != "stop" or calls is not None or not content:
            raise ValueError
        base.update({"content": content, "stopReason": "stop"})
    elif calls is not None:
        if choice.get("finish_reason") != "tool_calls" or type(calls) is not list or not calls:
            raise ValueError
        seen: set[str] = set()
        for call in calls:
            if type(call) is not dict or call.get("type") != "function" or type(call.get("id")) is not str or not call["id"] or call["id"] in seen or type(call.get("function")) is not dict or call["function"].get("name") != "ipython" or type(call["function"].get("arguments")) is not str:
                raise ValueError
            arguments = json.loads(call["function"]["arguments"])
            if type(arguments) is not dict or set(arguments) != {"code"} or type(arguments.get("code")) is not str or not arguments["code"]:
                raise ValueError
            seen.add(call["id"])
            content.append({"arguments": arguments, "id": call["id"], "name": "ipython", "type": "toolCall"})
        base.update({"content": content, "stopReason": "toolUse"})
    else:
        if choice.get("finish_reason") not in {"stop", "length"} or not content:
            raise ValueError
        base.update({"content": content, "stopReason": choice["finish_reason"]})
    return _canonical_json(base).encode(), PrimeModelBrokerTokenUsage(usage["prompt_tokens"], usage["completion_tokens"], _REQUEST_COST_RESERVATION)


def _text(value: object) -> str:
    if type(value) is str and value:
        return value
    if type(value) is not list or not value:
        return ""
    texts: list[str] = []
    for item in value:
        if type(item) is not dict or set(item) != {"type", "text"} or item.get("type") != "text":
            return ""
        text = item.get("text")
        if type(text) is not str:
            return ""
        texts.append(text)
    return "".join(texts)


__all__ = (
    "PrimeP7SolvingSdkProvider", "PrimeP7SolvingSdkProviderError",
    "create_prime_p7_solving_sdk_provider", "P7_SOLVING_PROVIDER_REQUEST_BYTES",
    "P7_SOLVING_PROVIDER_CALLBACK_LIMIT", "P7_SOLVING_PROVIDER_INPUT_LIMIT",
    "P7_SOLVING_PROVIDER_OUTPUT_LIMIT", "P7_SOLVING_PROVIDER_COST_LIMIT",
    "P7_SOLVING_PROVIDER_DEADLINE_SECONDS", "P7_SOLVING_PROVIDER_CALLBACK_OUTPUT_LIMIT",
)
