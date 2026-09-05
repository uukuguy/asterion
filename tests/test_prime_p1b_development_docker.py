from __future__ import annotations

import unittest
from time import monotonic
import asyncio

from asterion.applications.prime_agent.operator.docker_worker import DockerWorkerLauncherSelfCheck
from asterion.applications.prime_agent.operator.p1b_development_docker import (
    P1BDockerCompletion, P1BDockerPersistentWorkerService, P1BDockerCliTransport, _reap_process,
)
from asterion.applications.prime_agent.operator.docker_cli import DockerCliResult
from asterion.applications.prime_agent.operator.docker_worker import _LifecycleCallControl
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
    def __init__(self) -> None: self.calls: list[str] = []; self.channel_value = _Channel(); self.inspect_error = False; self.remove_error = False
    async def create(self, **_: object) -> str: self.calls.append("create"); return "d" * 64
    async def inspect(self, *_: object, **__: object) -> None:
        self.calls.append("inspect")
        if self.inspect_error: raise ValueError
    async def start(self, *_: object, **__: object) -> None: self.calls.append("start")
    async def channel(self, *_: object, **__: object) -> _Channel: self.calls.append("attach"); return self.channel_value
    async def snapshot(self, *_: object, **__: object) -> bytes: self.calls.append("snapshot"); return b"p1b continuity fixture\n"
    async def initial_snapshot(self, *_: object, **__: object) -> bytes: self.calls.append("initial_snapshot"); return b"def answer() -> int:\n    return 0\n"
    async def force_remove(self, *_: object, **__: object) -> None:
        self.calls.append("remove")
        if self.remove_error: raise ValueError
    async def assert_absent(self, *_: object, **__: object) -> None: self.calls.append("absent")


class TestP1BDockerPersistentWorkerService(unittest.IsolatedAsyncioTestCase):
    async def test_reap_completes_wait_before_propagating_cancellation(self) -> None:
        released = asyncio.Event()
        class Process:
            returncode = None
            killed = False
            def kill(self) -> None: self.killed = True
            async def wait(self) -> int:
                await released.wait(); return 0
        process = Process()
        task = asyncio.create_task(_reap_process(process))
        await asyncio.sleep(0)
        task.cancel(); await asyncio.sleep(0)
        self.assertTrue(process.killed)
        self.assertFalse(task.done())
        released.set()
        with self.assertRaises(asyncio.CancelledError): await task

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

    async def test_inspect_rejection_after_create_still_removes_and_proves_absence(self) -> None:
        transport = _Transport(); transport.inspect_error = True
        service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        with self.assertRaises(Exception):
            await service.acquire()
        self.assertEqual(transport.calls, ["create", "inspect", "remove", "absent"])

    async def test_cleanup_failure_retains_owner_for_retry(self) -> None:
        transport = _Transport(); service = P1BDockerPersistentWorkerService(image_digest="sha256:" + "a" * 64, transport=transport, run_id="run", session_id="session")
        await service.acquire(); transport.remove_error = True
        with self.assertRaises(ValueError): await service.cleanup()
        transport.remove_error = False; await service.cleanup()
        self.assertEqual(transport.calls[-3:], ["remove", "remove", "absent"])

    async def test_uncertain_create_compensation_removes_provisional_name_then_asserts_absence(self) -> None:
        class Runner:
            def __init__(self) -> None: self.argv: list[tuple[str, ...]] = []
            async def run(self, *, argv: tuple[str, ...], **_: object) -> DockerCliResult:
                self.argv.append(argv)
                if "rm" in argv: return DockerCliResult(0, b"prime-p1b-provisional\n", b"")
                return DockerCliResult(1, b"", b"Error: No such object: prime-p1b-provisional\n")
        runner = Runner()
        subject = object.__new__(P1BDockerCliTransport)
        subject._prefix = ("/operator/docker", "--host", "unix:///operator/docker.sock")
        subject._runner = runner
        await subject._compensate_provisional("prime-p1b-provisional")
        self.assertEqual(runner.argv[0][-4:], ("container", "rm", "--force", "prime-p1b-provisional"))
        self.assertEqual(runner.argv[1][-5:], ("container", "inspect", "--format", "{{.Id}}", "prime-p1b-provisional"))
