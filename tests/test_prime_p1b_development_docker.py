from __future__ import annotations

import unittest

from asterion.applications.prime_agent.operator.docker_worker import DockerWorkerLauncherSelfCheck
from asterion.applications.prime_agent.operator.p1b_development_docker import (
    P1BDockerCompletion, P1BDockerPersistentWorkerService,
)
from asterion.applications.prime_agent.operator.p1b_workload import PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST


class _Channel:
    async def self_check(self, **_: object) -> DockerWorkerLauncherSelfCheck:
        return DockerWorkerLauncherSelfCheck(True, True, True, True, 0, 1, 2, 65534)
    async def execute_cell(self, cell: str, **_: object) -> dict[str, object]:
        if cell == "one": return {"cell_count": 1, "kernel_generation": 1, "probe_count": 6, "baseline_recorded": True}
        return {"cell_count": 2, "kernel_generation": 1, "probe_count": 12}
    async def finish(self, **_: object) -> P1BDockerCompletion:
        return P1BDockerCompletion(PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST, 1, 2, 12)
    async def close(self, **_: object) -> None: pass


class _Transport:
    def __init__(self) -> None: self.calls: list[str] = []; self.channel_value = _Channel()
    async def create(self, **_: object) -> str: self.calls.append("create"); return "d" * 64
    async def inspect(self, *_: object, **__: object) -> None: self.calls.append("inspect")
    async def start(self, *_: object, **__: object) -> None: self.calls.append("start")
    async def channel(self, *_: object, **__: object) -> _Channel: self.calls.append("attach"); return self.channel_value
    async def snapshot(self, *_: object, **__: object) -> bytes: self.calls.append("snapshot"); return b"p1b continuity fixture\n"
    async def initial_snapshot(self, *_: object, **__: object) -> bytes: self.calls.append("initial_snapshot"); return b"def answer() -> int:\n    return 0\n"
    async def force_remove(self, *_: object, **__: object) -> None: self.calls.append("remove")
    async def assert_absent(self, *_: object, **__: object) -> None: self.calls.append("absent")


class TestP1BDockerPersistentWorkerService(unittest.IsolatedAsyncioTestCase):
    async def test_two_cells_finish_snapshot_and_cleanup_are_ordered(self) -> None:
        transport = _Transport()
        service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        await service.acquire()
        self.assertIn(b"return 0", await service.initial_snapshot())
        self.assertEqual((await service.execute_cell("one"))["cell_count"], 1)
        self.assertEqual((await service.execute_cell("two"))["probe_count"], 12)
        self.assertEqual(await service.finish(), P1BDockerCompletion(PRIME_IPYTHON_CODING_P1B_DEVELOPMENT_WORKLOAD_DIGEST, 1, 2, 12))
        self.assertEqual(await service.snapshot(), b"p1b continuity fixture\n")
        await service.cleanup()
        self.assertEqual(transport.calls, ["create", "inspect", "start", "attach", "initial_snapshot", "snapshot", "remove", "absent"])
