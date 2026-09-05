"""Focused checks for the five-stage structured P1-B SDK provider."""

from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from unittest import mock


_MODEL = {
    "api": "asterion-p1-development",
    "baseUrl": "https://development.invalid/v1",
    "contextWindow": 32_768,
    "cost": {"cacheRead": 0, "cacheWrite": 0, "input": 0, "output": 0},
    "id": "p1-development",
    "input": ["text"],
    "maxTokens": 1_024,
    "name": "P1 development",
    "provider": "asterion-development",
    "reasoning": False,
}
_NORMAL_OPTIONS = {
    "apiKey": "in-memory-development-provider",
    "maxRetries": 0,
    "maxRetryDelayMs": 60_000,
    "model": _MODEL,
    "serviceTier": "default",
    "sessionId": "session-1",
    "signal": {},
    "toolExecution": "parallel",
    "transport": "auto",
}


def _tool() -> dict[str, object]:
    return {"description": "IPython bridge", "name": "ipython", "parameters": {"additionalProperties": False, "properties": {"code": {"type": "string"}}, "required": ["code"], "type": "object"}}


def _request(messages: list[object], *, compact: bool = False) -> bytes:
    context: dict[str, object] = {"messages": messages, "systemPrompt": "system"}
    if not compact:
        context["tools"] = [_tool()]
    options: dict[str, object] = {"apiKey": "in-memory-development-provider", "maxTokens": 768, "signal": {}} if compact else dict(_NORMAL_OPTIONS)
    return json.dumps({"context": context, "model": _MODEL, "options": options}, separators=(",", ":"), sort_keys=True).encode()


def _tool_reply(call_id: str, code: str) -> dict[str, object]:
    return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [{"function": {"arguments": json.dumps({"code": code}), "name": "ipython"}, "id": call_id, "type": "function"}]}}], "usage": {"completion_tokens": 1, "prompt_tokens": 2}}


def _text_reply(text: str) -> dict[str, object]:
    return {"choices": [{"finish_reason": "stop", "message": {"content": text, "tool_calls": None}}], "usage": {"completion_tokens": 1, "prompt_tokens": 2}}


class TestPrimeP1BDevelopmentSdkProvider(unittest.IsolatedAsyncioTestCase):
    async def test_runs_exact_five_stage_sequence_and_exposes_terminal_usage(self) -> None:
        from asterion.applications.prime_agent.operator import p1b_development_sdk_provider as subject

        provider = subject.create_prime_p1b_development_sdk_provider({"DEEPSEEK_API_KEY": "private-key", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        def post(_: object, payload: object, __: object) -> object:
            self.assertIsInstance(payload, dict)
            messages = payload["messages"]  # type: ignore[index]
            if "tools" not in payload:
                self.assertNotIn("tool_choice", payload)
                self.assertEqual([item["role"] for item in messages], ["system", "user"])
                return _text_reply("summary")
            if messages[-1]["role"] == "tool":
                self.assertEqual([item["role"] for item in messages[-2:]], ["assistant", "tool"])
                return _text_reply("final done" if messages[-2]["tool_calls"][0]["id"] == "call-2" else "first done")
            if messages[-1]["content"] == "continue":
                self.assertEqual([item["role"] for item in messages[-2:]], ["assistant", "user"])
            return _tool_reply("call-2" if messages[-1]["content"] == "continue" else "call-1", "print(2)")

        initial = [{"content": "solve", "role": "user"}]
        with mock.patch.object(subject, "_post_chat_completion", side_effect=post):
            one = json.loads(await provider(_request(initial)))
            two = json.loads(await provider(_request(initial + [one, {"content": [{"text": "ok", "type": "text"}], "isError": False, "role": "toolResult", "toolCallId": "call-1", "toolName": "ipython"}])))
            compact_input = [{"content": "compact source", "role": "user"}]
            three = json.loads(await provider(_request(compact_input, compact=True)))
            four_input = [{"content": "solve", "role": "user"}, three, {"content": "continue", "role": "user"}]
            four = json.loads(await provider(_request(four_input)))
            five = json.loads(await provider(_request(four_input + [four, {"content": [{"text": "ok", "type": "text"}], "isError": False, "role": "toolResult", "toolCallId": "call-2", "toolName": "ipython"}])) )
        self.assertEqual((one["stopReason"], two["stopReason"], three["stopReason"], four["stopReason"], five["stopReason"]), ("toolUse", "stop", "stop", "toolUse", "stop"))
        self.assertEqual(provider.terminal_usage().cost_microunits, 25_000)

    async def test_rejects_forged_stage_two_or_compact_association_before_network(self) -> None:
        from asterion.applications.prime_agent.operator import p1b_development_sdk_provider as subject

        provider = subject.create_prime_p1b_development_sdk_provider({"DEEPSEEK_API_KEY": "private-key", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        with mock.patch.object(subject, "_post_chat_completion", return_value=_tool_reply("call-1", "x")) as post:
            first = json.loads(await provider(_request([{"content": "solve", "role": "user"}])))
            forged = dict(first)
            forged["content"] = [{"arguments": {"code": "x"}, "id": "wrong", "name": "ipython", "type": "toolCall"}]
            with self.assertRaises(subject.PrimeP1BDevelopmentSdkProviderError):
                await provider(_request([{"content": "solve", "role": "user"}, forged, {"content": [{"text": "ok", "type": "text"}], "isError": False, "role": "toolResult", "toolCallId": "wrong", "toolName": "ipython"}]))
        self.assertEqual(post.call_count, 0)

    async def test_cancellation_reaps_child_and_hides_terminal_usage(self) -> None:
        from asterion.applications.prime_agent.operator import p1b_development_sdk_provider as subject

        provider = subject.create_prime_p1b_development_sdk_provider({"DEEPSEEK_API_KEY": "private-key", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        with mock.patch.object(subject, "_post_chat_completion", side_effect=lambda *_: time.sleep(10)):
            task = asyncio.create_task(provider(_request([{"content": "solve", "role": "user"}])))
            for _ in range(100):
                if provider._child_pid is not None:  # noqa: SLF001
                    break
                await asyncio.sleep(0.01)
            pid = provider._child_pid  # noqa: SLF001
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(provider._child_pid)  # noqa: SLF001
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)  # type: ignore[arg-type]
        with self.assertRaises(subject.PrimeP1BDevelopmentSdkProviderError):
            provider.terminal_usage()
