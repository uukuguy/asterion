from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_prime_p5_development_gateway import _CHILD as _P5_CHILD


_CHILD = _P5_CHILD.replace("p5-development", "p7-development")


class TestPrimeP7DevelopmentGateway(unittest.TestCase):
    def test_three_prompts_have_one_terminal_six_by_three_witness(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_gateway import PrimeP7DevelopmentGateway

        with tempfile.TemporaryDirectory() as temporary:
            entrypoint = Path(temporary) / "bridge.js"
            entrypoint.write_text(_CHILD, encoding="utf-8")
            gateway = PrimeP7DevelopmentGateway(node_bin="node", entrypoint=entrypoint)
            gateway.bind(model_hook=lambda _: {"role": "assistant"}, tool_hook=lambda _: {})
            gateway.open_sync(run_id="run", session_id="session", generation=1, prime_source_root="/tmp/prime", workspace="/tmp/workspace")
            for prompt, callbacks, tools in (("one", 2, 1), ("two", 4, 2), ("three", 6, 3)):
                self.assertEqual(gateway.prompt_sync(prompt), {"lifecycle": "completed", "model_callback_count": callbacks, "tool_callback_count": tools})
            witness = gateway.terminal_witness()
            self.assertEqual(dict(witness["cumulative"]), {"model_callback_count": 6, "tool_callback_count": 3})
            gateway.close_sync()

