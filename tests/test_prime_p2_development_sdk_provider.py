"""Focused P2 provider turn and redaction contracts."""
from __future__ import annotations
import json
import unittest
from unittest import mock


def _tool() -> dict[str, object]:
    return {"description": "cell", "name": "ipython", "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}


def _request(messages: list[object]) -> bytes:
    return json.dumps({"model": {"api": "asterion-p2-development", "provider": "asterion-development", "id": "p2-development"}, "context": {"messages": messages, "tools": [_tool()]}, "options": {}}, separators=(",", ":"), sort_keys=True).encode()


class TestPrimeP2DevelopmentSdkProvider(unittest.IsolatedAsyncioTestCase):
    async def test_strict_two_turn_history_and_third_rejection(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_sdk_provider as subject
        provider = subject.create_prime_p2_development_sdk_provider({"DEEPSEEK_API_KEY": "private", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        first_reply = {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "ipython", "arguments": '{"code":"x"}'}}]}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        second_reply = {"choices": [{"finish_reason": "stop", "message": {"content": "done", "tool_calls": None}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        def reply(_: object, payload: object, __: object) -> object:
            self.assertIsInstance(payload, dict)
            return second_reply if payload["messages"][-1]["role"] == "tool" else first_reply  # type: ignore[index]
        with mock.patch.object(subject, "_post_chat_completion", side_effect=reply):
            first = json.loads(await provider(_request([{"role": "user", "content": "private"}])))
            second = await provider(_request([{"role": "user", "content": "private"}, first, {"role": "toolResult", "toolCallId": "call-1", "toolName": "ipython", "isError": False, "content": [{"type": "text", "text": "ok"}]}]))
            with self.assertRaises(subject.PrimeP2DevelopmentSdkProviderError):
                await provider(_request([{"role": "user", "content": "private"}]))
        self.assertEqual(json.loads(second)["stopReason"], "stop")

    def test_payload_forces_tool_then_text_only(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_sdk_provider as subject
        request = json.loads(_request([{"role": "user", "content": "x"}]))
        self.assertEqual(
            subject._deepseek_payload(request, "model", 0, 1)["tool_choice"],  # noqa: SLF001
            "auto",
        )
        request["context"]["messages"].extend([{"role": "assistant", "content": [{"type": "toolCall", "id": "call-1", "name": "ipython", "arguments": {"code": "x"}}], "stopReason": "toolUse"}, {"role": "toolResult", "toolCallId": "call-1", "toolName": "ipython", "isError": False, "content": [{"type": "text", "text": "ok"}]}])  # type: ignore[index]
        self.assertEqual(subject._deepseek_payload(request, "model", 1, 1)["tool_choice"], "none")  # noqa: SLF001

    async def test_public_error_redacts_sentinel(self) -> None:
        from asterion.applications.prime_agent.operator import p2_development_sdk_provider as subject
        sentinel = "P2_PRIVATE_SENTINEL"
        provider = subject.create_prime_p2_development_sdk_provider({"DEEPSEEK_API_KEY": sentinel, "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
        with mock.patch.object(subject, "_post_chat_completion", side_effect=ValueError(sentinel)):
            with self.assertRaises(subject.PrimeP2DevelopmentSdkProviderError) as raised:
                await provider(_request([{"role": "user", "content": sentinel}]))
        self.assertNotIn(sentinel, str(raised.exception) + repr(raised.exception) + repr(provider))
