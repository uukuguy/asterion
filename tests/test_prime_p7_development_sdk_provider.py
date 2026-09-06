from __future__ import annotations

import unittest


class TestP7DevelopmentSdkProvider(unittest.TestCase):
    def test_six_turn_deterministic_tool_policy(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_sdk_provider import P7_PROVIDER_OUTPUT_LIMITS, _deepseek_payload

        request = {"context": {"systemPrompt": "s", "messages": [], "tools": [{"name": "ipython", "description": "d", "parameters": {"type": "object"}}]}}
        for turn, ceiling in enumerate(P7_PROVIDER_OUTPUT_LIMITS):
            with self.subTest(turn=turn):
                payload = _deepseek_payload(request, "model", ceiling, turn=turn)
                self.assertEqual(payload["temperature"], 0)
                self.assertEqual(payload["tool_choice"], {"type": "function", "function": {"name": "ipython"}} if turn % 2 == 0 else "none")

