"""Focused checks for the structured P1 development SDK provider."""

from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from unittest import mock


def _request(*, messages: list[object], tools: list[object]) -> bytes:
    return json.dumps(
        {
            "context": {"messages": messages, "tools": tools},
            "model": {
                "api": "asterion-p1-development",
                "id": "p1-development",
                "provider": "asterion-development",
            },
            "options": {},
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _ipython_tool() -> dict[str, object]:
    return {
        "description": "Caller-owned IPython execution bridge.",
        "name": "ipython",
        "parameters": {
            "additionalProperties": False,
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
            "type": "object",
        },
    }


class TestPrimeP1DevelopmentSdkProvider(unittest.IsolatedAsyncioTestCase):
    async def test_two_turn_tool_then_text_returns_prime_messages_and_usage(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_sdk_provider as subject,
        )

        provider = subject.create_prime_p1_development_sdk_provider(
            {"DEEPSEEK_API_KEY": "private-key", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}
        )
        first_reply = {
                "choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [{"function": {"arguments": '{"code":"print(42)"}', "name": "ipython"}, "id": "call-1", "type": "function"}]}}],
                "usage": {"completion_tokens": 7, "prompt_tokens": 11},
            }
        second_reply = {
                "choices": [{"finish_reason": "stop", "message": {"content": "done", "tool_calls": None}}],
                "usage": {"completion_tokens": 5, "prompt_tokens": 13},
            }

        def reply(_: object, payload: object, __: object) -> object:
            self.assertIsInstance(payload, dict)
            messages = payload["messages"]  # type: ignore[index]
            self.assertEqual(payload["thinking"], {"type": "disabled"})  # type: ignore[index]
            self.assertEqual(payload["tools"][0]["function"]["name"], "ipython")  # type: ignore[index]
            self.assertEqual(payload["tool_choice"], "auto")  # type: ignore[index]
            if messages[-1]["role"] == "tool":
                self.assertEqual(messages[-2]["tool_calls"][0]["id"], "call-1")
                self.assertEqual(messages[-1]["tool_call_id"], "call-1")
            return second_reply if messages[-1]["role"] == "tool" else first_reply

        with mock.patch.object(subject, "_post_chat_completion", side_effect=reply):
            first = json.loads(
                await provider(
                    _request(
                        messages=[{"content": "solve it", "role": "user", "timestamp": 1}],
                        tools=[_ipython_tool()],
                    )
                )
            )
            second = json.loads(
                await provider(
                    _request(
                        messages=[
                            {"content": "solve it", "role": "user", "timestamp": 1},
                            {"api": "asterion-p1-development", "content": [{"arguments": {"code": "print(42)"}, "id": "call-1", "name": "ipython", "type": "toolCall"}], "model": "p1-development", "provider": "asterion-development", "role": "assistant", "stopReason": "toolUse", "timestamp": 2, "usage": {"cacheRead": 0, "cacheWrite": 0, "cost": {"cacheRead": 0, "cacheWrite": 0, "input": 0, "output": 0, "total": 0}, "input": 11, "output": 7, "totalTokens": 18}},
                            {"content": [{"text": "ok", "type": "text"}], "isError": False, "role": "toolResult", "timestamp": 3, "toolCallId": "call-1", "toolName": "ipython"},
                        ],
                        tools=[_ipython_tool()],
                    )
                )
            )
        self.assertEqual(first["content"], [{"arguments": {"code": "print(42)"}, "id": "call-1", "name": "ipython", "type": "toolCall"}])
        self.assertEqual(first["stopReason"], "toolUse")
        self.assertEqual(second["content"], [{"text": "done", "type": "text"}])
        self.assertEqual(second["stopReason"], "stop")
        self.assertEqual(provider.terminal_usage().input_tokens, 24)
        self.assertEqual(provider.terminal_usage().output_tokens, 12)

    async def test_cancellation_kills_and_reaps_active_child(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_sdk_provider as subject,
        )

        provider = subject.create_prime_p1_development_sdk_provider(
            {"DEEPSEEK_API_KEY": "private-key", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}
        )

        def blocked(_: object, __: object) -> object:
            time.sleep(10)
            raise AssertionError("child should have been killed")

        with mock.patch.object(subject, "_post_chat_completion", side_effect=blocked):
            task = asyncio.create_task(provider(_request(messages=[{"content": "x", "role": "user", "timestamp": 1}], tools=[_ipython_tool()])))
            for _ in range(100):
                if provider._child_pid is not None:  # noqa: SLF001
                    break
                await asyncio.sleep(0.01)
            pid = provider._child_pid  # noqa: SLF001
            self.assertIsInstance(pid, int)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(provider._child_pid)  # noqa: SLF001
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)  # type: ignore[arg-type]

    async def test_private_values_do_not_escape_errors_or_terminal_projection(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_sdk_provider as subject,
        )

        sentinel = "SENTINEL_SECRET"
        provider = subject.create_prime_p1_development_sdk_provider(
            {"DEEPSEEK_API_KEY": sentinel, "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}
        )
        with mock.patch.object(subject, "_post_chat_completion", side_effect=ValueError(sentinel)):
            with self.assertRaises(subject.PrimeP1DevelopmentSdkProviderError) as raised:
                await provider(_request(messages=[{"content": sentinel, "role": "user", "timestamp": 1}], tools=[_ipython_tool()]))
        projection = repr(provider) + repr(raised.exception) + str(raised.exception)
        self.assertNotIn(sentinel, projection)
        self.assertEqual(str(raised.exception), "prime development SDK provider is unavailable")
