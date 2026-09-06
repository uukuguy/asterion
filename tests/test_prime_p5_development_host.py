from __future__ import annotations

import unittest
import asyncio


def _digest(char: str) -> str:
    return "sha256:" + char * 64


class _Provider:
    async def __call__(self, _: bytes) -> bytes:
        return b"{}"

    def terminal_usage(self) -> object:
        return type("Usage", (), {"input_tokens": 1, "output_tokens": 1, "cost_microunits": 1})()

    async def close(self) -> None:
        return None


class _Worker:
    def __init__(self) -> None:
        self.cells = self.results = self.qualities = 0

    async def acquire(self) -> None:
        return None

    async def snapshot(self) -> object:
        source = b"def clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n" if self.cells == 2 else b"def clamp(value, lower, upper):\n    return min(max(value, lower), lower)\n"
        return {"solution.py": source}

    async def execute_cell(self, _: str) -> dict[str, int]:
        self.cells += 1
        return {"cell_count": self.cells}

    async def result_gate(self) -> dict[str, object]:
        self.results += 1
        return {"passed": True, "result_sha256": _digest(str(self.results))}

    async def quality_gate(self) -> dict[str, object]:
        self.qualities += 1
        return {"passed": self.qualities == 2, "result_sha256": _digest(str(self.qualities + 2))}

    async def artifact(self) -> bytes:
        return b'{"passed":true,"result":"clamp"}'

    async def cleanup(self) -> None:
        return None


class _Gateway:
    def bind(self, *, model_hook: object, tool_hook: object) -> None:
        self.model, self.tool = model_hook, tool_hook
        self.prompts = 0

    async def open(self, **_: object) -> None:
        return None

    async def prompt(self, _: str) -> dict[str, object]:
        self.prompts += 1
        for index in range(2):
            await self.model({"turn": index})  # type: ignore[misc]
        await self.tool({"tool_call_id": str(self.prompts), "code": "repair"})  # type: ignore[misc]
        return {"lifecycle": "completed", "model_callback_count": self.prompts * 2, "tool_callback_count": self.prompts}

    async def feedback(self, value: str) -> dict[str, object]:
        assert value == "quality gate failed; repair clamp defect"
        return {}

    async def close(self) -> None:
        return None

    async def cancel(self) -> object:
        return {"lifecycle": "cancelled"}


class TestP5DevelopmentHost(unittest.TestCase):
    def test_runs_the_fixed_fail_then_repair_chain(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import run_p5_development_lifecycle
        trace = asyncio.run(run_p5_development_lifecycle(gateway=_Gateway(), provider=_Provider(), worker=_Worker(), run_id="run", session_id="session", container_id="container", goal_id="goal"))
        self.assertRegex(trace.trace_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertNotIn("goal", repr(trace))
    def test_snapshot_accepts_only_the_clamp_inventory_and_narrow_function_ast(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import validate_p5_development_snapshot
        valid = b"def clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n"
        validate_p5_development_snapshot(valid, repaired=True)
        for source in (b"import os\n", b"def clamp(x, y, z):\n return x + y\n", b"def other(x):\n return x\n"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError): validate_p5_development_snapshot(source, repaired=True)

    def test_artifact_is_independently_validated(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import validate_p5_development_artifact
        validate_p5_development_artifact(b'{"passed":true,"result":"clamp"}')
        with self.assertRaises(ValueError): validate_p5_development_artifact(b'{"passed":false}')
