"""Focused boundary checks for the role-multiplexed P3 SDK provider."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock


_IDENTITY = "123e4567-e89b-12d3-a456-426614174000"


def _body(text: str, *, role: str = "root") -> bytes:
    return json.dumps(
        {
            "context": {
                "messages": [{"content": text, "role": "user"}],
                "tools": [
                    {
                        "description": "bound IPython",
                        "name": "ipython",
                        "parameters": {
                            "properties": {"code": {"type": "string"}},
                            "required": ["code"],
                            "type": "object",
                        },
                    }
                ],
            },
            "model": {
                "api": f"asterion-p3-{role}-{_IDENTITY}",
                "id": f"{role}-{_IDENTITY}",
                "provider": f"asterion-p3-{role}-{_IDENTITY}",
            },
            "options": {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _response(text: str, *, role: str = "root") -> bytes:
    return json.dumps(
        {
            "api": f"asterion-p3-{role}-{_IDENTITY}",
            "content": [{"text": text, "type": "text"}],
            "model": f"{role}-{_IDENTITY}",
            "provider": f"asterion-p3-{role}-{_IDENTITY}",
            "role": "assistant",
            "stopReason": "stop",
            "timestamp": 1,
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
                "input": 1,
                "output": 1,
                "totalTokens": 2,
            },
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _follow(previous: bytes, response: bytes, text: str) -> bytes:
    value = json.loads(previous)
    value["context"]["messages"].extend(
        [json.loads(response), {"content": text, "role": "user"}]
    )
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


class TestPrimeP3DevelopmentSdkProvider(unittest.IsolatedAsyncioTestCase):
    def test_tool_response_discards_nonempty_provider_preamble(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_sdk_provider as subject,
        )

        request = subject._decode_request(_body("root"), None, "root")
        response, _ = subject._assistant_response(
            request,
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "I will execute the requested fixed cell.",
                            "tool_calls": [
                                {
                                    "function": {
                                        "arguments": '{"code":"x = 1"}',
                                        "name": "ipython",
                                    },
                                    "id": "tool-1",
                                    "type": "function",
                                }
                            ],
                        },
                    }
                ],
                "usage": {"completion_tokens": 1, "prompt_tokens": 1},
            },
        )
        projected = json.loads(response)
        self.assertEqual(projected["stopReason"], "toolUse")
        self.assertEqual(len(projected["content"]), 1)

    def test_http_payload_uses_operator_model_and_redacts_terminal_child_notice(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_sdk_provider as subject,
        )

        request = subject._decode_request(
            _body("RLM child implementation (SENTINEL_CHILD_ID) completed"),
            None,
            "root",
        )  # noqa: SLF001
        payload = subject._payload(request, "deepseek-v4-flash", "root")  # noqa: SLF001
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(
            payload["messages"][-1]["content"],
            subject._TERMINAL_NOTICE["implementation"],
        )  # noqa: SLF001
        self.assertNotIn("SENTINEL_CHILD_ID", repr(payload))

    async def test_roles_keep_independent_histories_and_return_child_response(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_sdk_provider as subject,
        )

        provider = subject.create_prime_p3_development_sdk_provider(
            {
                "DEEPSEEK_API_KEY": "private-key",
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
            }
        )
        result, usage = (
            _response("private assistant answer"),
            subject.PrimeModelBrokerTokenUsage(1, 1, 1),
        )
        with mock.patch.object(
            type(provider), "_run_child", return_value=(result, usage)
        ) as child:
            self.assertEqual(
                await provider.callback("root", _body("root-only")), result
            )
            self.assertEqual(
                await provider.callback(
                    "implementation",
                    _body("implementation-only", role="implementation"),
                ),
                result,
            )
        self.assertEqual(provider.histories["root"], (_body("root-only"),))
        self.assertEqual(
            provider.histories["implementation"],
            (_body("implementation-only", role="implementation"),),
        )
        self.assertEqual(provider.histories["review"], ())
        self.assertEqual(child.call_count, 2)

    async def test_exact_role_caps_share_one_budget_and_terminal_usage_needs_ten_calls(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_sdk_provider as subject,
        )

        provider = subject.create_prime_p3_development_sdk_provider(
            {
                "DEEPSEEK_API_KEY": "private-key",
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
            }
        )
        usage = subject.PrimeModelBrokerTokenUsage(1, 1, 1)

        async def child(_: object, role: str, *__: object) -> tuple[bytes, object]:
            return _response("answer", role=role), usage

        with mock.patch.object(type(provider), "_run_child", side_effect=child):
            for role, count in (("root", 4), ("implementation", 2), ("review", 4)):
                result = _response("answer", role=role)
                body = _body(f"{role}-0", role=role)
                for index in range(count):
                    await provider.callback(role, body)
                    body = _follow(body, result, f"{role}-{index + 1}")
            with self.assertRaises(subject.PrimeP3DevelopmentSdkProviderError):
                await provider.callback("review", _body("too-many", role="review"))
        self.assertTrue(provider.terminal())
        self.assertEqual(
            provider.terminal_usage(), subject.PrimeModelBrokerTokenUsage(10, 10, 10)
        )

    async def test_accepts_only_usage_attribution_changes_in_issued_history(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_sdk_provider as subject,
        )

        provider = subject.create_prime_p3_development_sdk_provider(
            {
                "DEEPSEEK_API_KEY": "private-key",
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
            }
        )
        result = _response("answer")
        usage = subject.PrimeModelBrokerTokenUsage(1, 1, 1)
        with mock.patch.object(
            type(provider), "_run_child", return_value=(result, usage)
        ):
            first = _body("first")
            await provider.callback("root", first)
            attributed = json.loads(result)
            attributed["usage"]["input"] = 9
            attributed["usage"]["totalTokens"] = 10
            second = _follow(
                first,
                json.dumps(attributed, separators=(",", ":"), sort_keys=True).encode(),
                "next",
            )
            await provider.callback("root", second)
            forged = json.loads(second)
            forged["context"]["messages"][1]["content"][0]["text"] = "forged"
            with self.assertRaises(subject.PrimeP3DevelopmentSdkProviderError):
                await provider.callback(
                    "root",
                    json.dumps(forged, separators=(",", ":"), sort_keys=True).encode(),
                )

    async def test_cancellation_reaps_active_child_and_hides_usage(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p3_development_sdk_provider as subject,
        )

        provider = subject.create_prime_p3_development_sdk_provider(
            {
                "DEEPSEEK_API_KEY": "private-key",
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
            }
        )
        reaped = asyncio.Event()

        async def blocked(*_: object) -> tuple[bytes, object]:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def reap() -> None:
            reaped.set()

        with (
            mock.patch.object(type(provider), "_run_child", side_effect=blocked),
            mock.patch.object(type(provider), "_reap_shielded", side_effect=reap),
        ):
            task = asyncio.create_task(provider.callback("root", _body("cancel")))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(reaped.is_set())
        with self.assertRaises(subject.PrimeP3DevelopmentSdkProviderError):
            provider.terminal_usage()
