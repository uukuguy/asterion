from __future__ import annotations

import unittest


class TestP5DevelopmentSdkProvider(unittest.TestCase):
    def test_turn_two_keeps_ipython_tools_and_forces_the_function(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_sdk_provider import _deepseek_payload

        request = {"context": {"systemPrompt": "system", "messages": [{"role": "user", "content": [{"type": "text", "text": "repair"}]}], "tools": [{"description": "ipython", "parameters": {"type": "object"}}]}}
        payload = _deepseek_payload(request, "model", 1024, turn=2)
        self.assertEqual(payload["tool_choice"], {"type": "function", "function": {"name": "ipython"}})
        self.assertEqual(payload["tools"][0]["function"]["name"], "ipython")

    def test_exposes_the_fixed_finite_budget(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p5_development_sdk_provider as subject,
        )

        self.assertEqual(
            (
                subject.P5_PROVIDER_CALLBACK_LIMIT,
                subject.P5_PROVIDER_INPUT_LIMIT,
                subject.P5_PROVIDER_OUTPUT_LIMIT,
                subject.P5_PROVIDER_COST_LIMIT,
                subject.P5_PROVIDER_DEADLINE_SECONDS,
            ),
            (4, 32768, 2304, 20000, 180),
        )
