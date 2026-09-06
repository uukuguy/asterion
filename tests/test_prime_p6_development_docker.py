from __future__ import annotations

import asyncio
import unittest


class _Transport:
    def __init__(self) -> None:
        self.removed = self.absent = False
        self.stage = 0

    async def create_p6(self, **_: object) -> str:
        return "a" * 64

    async def execute_p6(self, *_: object) -> None:
        self.stage += 1

    async def read_p6(self, _: str, name: str, expected: tuple[str, ...], __: object) -> bytes:
        if name not in expected:
            raise ValueError
        return name.encode()

    async def restore_p6_baseline(self, *_: object) -> None:
        self.stage = 4

    async def remove_p6(self, *_: object) -> None:
        self.removed = True

    async def assert_p6_absent(self, *_: object) -> None:
        self.absent = True


class TestP6DevelopmentDocker(unittest.TestCase):
    def test_reads_exact_staged_inventories_and_cleans_up(self) -> None:
        from asterion.applications.prime_agent.operator.p6_development_docker import P6DevelopmentDockerWorkerService

        transport = _Transport()
        worker = P6DevelopmentDockerWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session", goal_id="goal")

        async def exercise() -> None:
            await worker.acquire()
            self.assertEqual(set(await worker.snapshot()), {"baseline.py"})
            for count in range(1, 4):
                self.assertEqual(await worker.execute_cell("x"), {"cell_count": count})
            self.assertEqual(set(await worker.snapshot()), {"baseline.py", "task-a.json", "candidate.py", "task-b.json"})
            await worker.restore_baseline()
            self.assertEqual(set(await worker.snapshot()), {"baseline.py"})
            await worker.cleanup()

        asyncio.run(exercise())
        self.assertTrue(transport.removed and transport.absent)

