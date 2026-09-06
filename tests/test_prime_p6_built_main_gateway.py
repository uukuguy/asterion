"""Real P6 framed bridge against the pinned Prime SDK checkout."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime_agent.operator import (
    p6_development_sdk_provider as provider_contract,
)
from asterion.applications.prime_agent.operator.p6_development_gateway import (
    PrimeP6DevelopmentGateway,
)


_ROOT = Path(__file__).resolve().parents[1]
_PRIME = _ROOT / "3th-party" / "prime-agent"
_MAIN = _ROOT / "packages/typescript/prime-gateway/dist/src/p6-development-main.js"


class TestPrimeP6BuiltMainGateway(unittest.TestCase):
    def test_three_prompts_use_one_real_session_with_six_by_three_witness(self) -> None:
        issued: list[tuple[dict[str, object], dict[str, object]]] = []
        tool_calls: list[dict[str, object]] = []

        def model_hook(payload: object) -> dict[str, object]:
            self.assertIsInstance(payload, dict)
            request = provider_contract._decode_request(  # noqa: SLF001
                provider_contract._canonical_json(payload).encode(),  # noqa: SLF001
                len(issued),
                issued,
            )
            turn = len(issued)
            model = request["model"]
            self.assertIsInstance(model, dict)
            message: dict[str, object] = {
                "api": model["api"],
                "model": model["id"],
                "provider": model["provider"],
                "role": "assistant",
                "timestamp": 0,
                "usage": {
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "cost": {"cacheRead": 0, "cacheWrite": 0, "input": 0, "output": 0, "total": 0},
                    "input": 1,
                    "output": 1,
                    "totalTokens": 2,
                },
            }
            if turn % 2 == 0:
                message.update({
                    "content": [{"arguments": {"code": "pass"}, "id": f"call-{turn}", "name": "ipython", "type": "toolCall"}],
                    "stopReason": "toolUse",
                })
            else:
                message.update({"content": [{"text": "stage complete", "type": "text"}], "stopReason": "stop"})
            issued.append((request, message))
            return message

        def tool_hook(payload: object) -> dict[str, object]:
            self.assertIsInstance(payload, dict)
            self.assertEqual(set(payload), {"code", "tool_call_id"})
            self.assertEqual(payload["code"], "pass")
            tool_calls.append(payload)
            return {"content": [{"type": "text", "text": "IPython cell completed"}], "details": {}, "isError": False}

        with tempfile.TemporaryDirectory(prefix="asterion-p6-built-main-") as temporary:
            workspace = Path(temporary)
            gateway = PrimeP6DevelopmentGateway(
                node_bin="node", entrypoint=_MAIN, deadline_seconds=15,
            )
            gateway.bind(model_hook=model_hook, tool_hook=tool_hook)
            gateway.open_sync(
                run_id="run-p6-built-main",
                session_id="session-p6-built-main",
                generation=1,
                prime_source_root=str(_PRIME),
                workspace=str(workspace),
            )
            try:
                for prompt, models, tools in (("stage-1", 2, 1), ("stage-2", 4, 2), ("stage-3", 6, 3)):
                    self.assertEqual(
                        gateway.prompt_sync(prompt),
                        {"lifecycle": "completed", "model_callback_count": models, "tool_callback_count": tools},
                    )
                self.assertEqual(len(issued), 6)
                self.assertEqual(len(tool_calls), 3)
                self.assertEqual(dict(gateway.terminal_witness()["cumulative"]), {"model_callback_count": 6, "tool_callback_count": 3})
            finally:
                gateway.close_sync()
            self.assertIsNone(gateway.child_pid)
