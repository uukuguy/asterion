from __future__ import annotations

import unittest
import asyncio
import hashlib
import json


def _digest(char: str) -> str:
    return "sha256:" + char * 64


class _Provider:
    async def __call__(self, _: bytes) -> bytes:
        return b"{}"

    def terminal_usage(self) -> object:
        return type(
            "Usage", (), {"input_tokens": 1, "output_tokens": 1, "cost_microunits": 1}
        )()

    async def close(self) -> None:
        return None


class _Worker:
    def __init__(self) -> None:
        self.cells = self.results = self.qualities = 0

    @property
    def image_digest(self) -> str:
        return "sha256:" + "f" * 64

    @property
    def daemon_id(self) -> str:
        return "a" * 64

    async def acquire(self) -> None:
        return None

    async def snapshot(self) -> object:
        source = (
            b"def clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n"
            if self.cells == 2
            else b"def clamp(value, lower, upper):\n    return min(upper, value)\n"
        )
        return {"solution.py": source}

    async def execute_cell(self, _: str) -> dict[str, int]:
        self.cells += 1
        return {"cell_count": self.cells}

    async def artifact(self) -> bytes:
        source = await self.snapshot()
        raw = source["solution.py"]
        goal = "prime.bounded-autonomy/v1"
        goal_digest = hashlib.sha256(
            json.dumps(
                {
                    "format": "asterion.prime-p5-goal/v1",
                    "goal_id": goal,
                    "workload_sha256": __import__(
                        "asterion.applications.prime_agent.operator.p5_development_workload",
                        fromlist=["P5_DEVELOPMENT_WORKLOAD_DIGEST"],
                    ).P5_DEVELOPMENT_WORKLOAD_DIGEST,
                    "oracle_sha256": __import__(
                        "asterion.applications.prime_agent.operator.p5_development_workload",
                        fromlist=["P5_DEVELOPMENT_ORACLE_DIGEST"],
                    ).P5_DEVELOPMENT_ORACLE_DIGEST,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return json.dumps(
            {
                "goal_id": goal,
                "goal_sha256": "sha256:" + goal_digest,
                "marker": "clamp-result",
                "run_id": "run",
                "source_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "stage": 1 if self.cells == 1 else 2,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()

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
        # type: ignore[misc]
        await self.tool({"tool_call_id": str(self.prompts), "code": "repair"})
        return {
            "lifecycle": "completed",
            "model_callback_count": self.prompts * 2,
            "tool_callback_count": self.prompts,
        }

    async def feedback(self, value: str) -> dict[str, object]:
        assert value.startswith(
            "quality gate failed for run=run goal=prime.bounded-autonomy/v1 gate=sha256:"
        )
        return {}

    async def close(self) -> None:
        return None

    def terminal_witness(self) -> dict[str, object]:
        return {
            "identity": {
                "run_id": "run",
                "session_id": "session",
                "runtime_id": "prime.agent",
                "generation": 1,
            },
            "result": {},
            "cumulative": {"model_callback_count": 4, "tool_callback_count": 2},
        }

    async def cancel(self) -> object:
        return {"lifecycle": "cancelled"}


class TestP5DevelopmentHost(unittest.TestCase):
    def test_stage_prompts_require_the_sole_ipython_call_to_complete_the_artifact(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import (
            _prompt,
        )

        stage_one = _prompt("diagnose", "run", "prime.bounded-autonomy/v1", 1)
        stage_two = _prompt("repair", "run", "prime.bounded-autonomy/v1", 2)

        for prompt in (stage_one, stage_two):
            with self.subTest(prompt=prompt):
                self.assertIn("exactly one ipython call", prompt)
                self.assertIn("must complete", prompt)
                self.assertIn("atomically write", prompt)
                self.assertIn("Do not inspect", prompt)
                self.assertIn("print", prompt)
                self.assertIn("subprocess", prompt)
        self.assertIn("Do not edit /workspace/solution.py", stage_one)
        self.assertIn("repair /workspace/solution.py", stage_two)

    def test_runs_the_fixed_fail_then_repair_chain(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import (
            run_p5_development_lifecycle,
        )

        trace = asyncio.run(
            run_p5_development_lifecycle(
                gateway=_Gateway(),
                provider=_Provider(),
                worker=_Worker(),
                run_id="run",
                session_id="session",
                container_id="container",
                goal_id="prime.bounded-autonomy/v1",
            )
        )
        self.assertRegex(trace.trace_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertNotIn("goal", repr(trace))

    def test_snapshot_accepts_only_the_clamp_inventory_and_narrow_function_ast(
        self,
    ) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import (
            validate_p5_development_snapshot,
        )

        valid = b"def clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n"
        validate_p5_development_snapshot(valid, repaired=True)
        for source in (
            b"import os\n",
            b"def clamp(x, y, z):\n return x + y\n",
            b"def other(x):\n return x\n",
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    validate_p5_development_snapshot(source, repaired=True)

    def test_artifact_is_independently_validated(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_host import (
            validate_p5_development_artifact,
        )

        source = b"def clamp(value, lower, upper):\n    return min(max(value, lower), upper)\n"
        artifact = json.dumps(
            {
                "goal_id": "goal",
                "goal_sha256": "sha256:" + "0" * 64,
                "marker": "clamp-result",
                "run_id": "run",
                "source_sha256": "sha256:" + hashlib.sha256(source).hexdigest(),
                "stage": 2,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        validate_p5_development_artifact(artifact)
        with self.assertRaises(ValueError):
            validate_p5_development_artifact(b'{"passed":false}')
