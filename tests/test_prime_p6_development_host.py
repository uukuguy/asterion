from __future__ import annotations

import asyncio
import json
import unittest


def _canonical(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


class _Provider:
    def __init__(self) -> None:
        self.closed = False

    async def __call__(self, _: bytes) -> bytes:
        return b'{"accepted":true}'

    def terminal_usage(self) -> object:
        return type("Usage", (), {"input_tokens": 1, "output_tokens": 1, "cost_microunits": 1})()

    async def close(self) -> None:
        self.closed = True


class _Worker:
    def __init__(self, *, candidate: bytes | None = None) -> None:
        from asterion.applications.prime_agent.operator import p6_development_host as host

        self.cells = 0
        self.cleaned = False
        self.candidate = candidate or host._CANDIDATE_SOURCE
        self._host = host

    @property
    def image_digest(self) -> str:
        return "sha256:" + "a" * 64

    @property
    def daemon_id(self) -> str:
        return "b" * 64

    async def acquire(self) -> None:
        return None

    async def snapshot(self) -> object:
        values = {"baseline.py": self._host._BASELINE_SOURCE}
        if self.cells >= 1:
            values["task-a.json"] = self._host._task_a_artifact("run", "session")
        if self.cells >= 2:
            values["candidate.py"] = self.candidate
        if self.cells >= 3:
            values["task-b.json"] = self._host._task_b_artifact("run", "session", self.candidate)
        return values

    async def execute_cell(self, _: str) -> dict[str, int]:
        self.cells += 1
        return {"cell_count": self.cells}

    async def restore_baseline(self) -> None:
        self.cells = 0

    async def cleanup(self) -> None:
        self.cleaned = True


class _Gateway:
    def __init__(self) -> None:
        self.prompts = 0
        self.closed = False

    def bind(self, *, model_hook: object, tool_hook: object) -> None:
        self.model, self.tool = model_hook, tool_hook

    async def open(self, **_: object) -> None:
        return None

    async def prompt(self, _: str) -> dict[str, object]:
        self.prompts += 1
        self.assert_reply(await self.model({"turn": self.prompts * 2 - 1}))
        self.assert_reply(await self.model({"turn": self.prompts * 2}))
        await self.tool({"tool_call_id": str(self.prompts), "code": "complete"})
        return {"lifecycle": "completed", "model_callback_count": self.prompts * 2, "tool_callback_count": self.prompts}

    @staticmethod
    def assert_reply(reply: object) -> None:
        if reply != {"accepted": True}:
            raise ValueError("model reply was discarded")

    def terminal_witness(self) -> dict[str, object]:
        return {"identity": {"run_id": "run", "session_id": "session", "runtime_id": "prime.agent", "generation": 1}, "cumulative": {"model_callback_count": 6, "tool_callback_count": 3}}

    async def close(self) -> None:
        self.closed = True

    async def cancel(self) -> None:
        return None


class TestP6DevelopmentHost(unittest.TestCase):
    def _run(self, worker: object) -> object:
        from asterion.applications.prime_agent.operator.p6_development_host import run_p6_development_lifecycle

        return asyncio.run(run_p6_development_lifecycle(gateway=_Gateway(), provider=_Provider(), worker=worker, run_id="run", session_id="session"))

    def test_runs_staged_preserve_chain_and_cleans_up(self) -> None:
        worker = _Worker()
        receipt = self._run(worker)
        self.assertEqual(receipt.outcome, "preserved")
        self.assertEqual(receipt.rollback_count, 0)
        self.assertTrue(worker.cleaned)

    def test_rolls_back_the_exact_candidate_after_failed_holdout(self) -> None:
        from asterion.applications.prime_agent.operator import p6_development_host as host

        receipt = self._run(_Worker(candidate=host._BAD_CANDIDATE_SOURCE))
        self.assertEqual(receipt.outcome, "rolled-back")
        self.assertEqual(receipt.rollback_count, 1)
        self.assertIsNotNone(receipt.rollback_revision_sha256)

    def test_rejects_mutated_candidate_before_receipt(self) -> None:
        class Mutated(_Worker):
            async def snapshot(self):
                value = await super().snapshot()
                if self.cells >= 2:
                    value["candidate.py"] = b"def clamp(value, lower, upper):\n return value\n"
                return value

        from asterion.applications.prime_agent.operator.p6_development_host import PrimeP6DevelopmentHostError

        with self.assertRaises(PrimeP6DevelopmentHostError):
            self._run(Mutated())

    def test_rejects_forged_passed_result(self) -> None:
        class Forged(_Worker):
            async def snapshot(self):
                value = await super().snapshot()
                if self.cells == 1:
                    item = json.loads(value["task-a.json"])
                    item["passed"] = True
                    value["task-a.json"] = _canonical(item)
                return value

        from asterion.applications.prime_agent.operator.p6_development_host import PrimeP6DevelopmentHostError

        with self.assertRaises(PrimeP6DevelopmentHostError):
            self._run(Forged())


if __name__ == "__main__":
    unittest.main()
