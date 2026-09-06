from __future__ import annotations

import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory


class _Transport:
    def __init__(self) -> None:
        self.reads: list[str] = []
        self.removed = self.absent = False

    async def create_p5(self, **_: object) -> str:
        return "a" * 64

    async def execute_p5(self, *_: object) -> None:
        return None

    async def read_p5(self, _: str, name: str, __: bool, ___: object) -> bytes:
        self.reads.append(name)
        return b'{"actual":"worker-bytes"}' if name == "result.json" else b"source"

    async def remove_p5(self, *_: object) -> None:
        self.removed = True

    async def assert_p5_absent(self, *_: object) -> None:
        self.absent = True


class TestP5DevelopmentDocker(unittest.TestCase):
    def test_uses_the_single_admitted_p1b_worker_profile(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            P5DevelopmentDockerWorkerService,
        )

        self.assertEqual(
            P5DevelopmentDockerWorkerService.__name__,
            "P5DevelopmentDockerWorkerService",
        )

    def test_reads_actual_artifact_twice_and_requires_daemon_absence(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            P5DevelopmentDockerWorkerService,
        )

        transport = _Transport()
        worker = P5DevelopmentDockerWorkerService(
            image_digest="sha256:" + "a" * 64,
            transport=transport,
            run_id="run",
            session_id="session",
            goal_id="goal",
            workspace="/workspace",
        )

        async def exercise() -> bytes:
            await worker.acquire()
            await worker.execute_cell("diagnose")
            first = await worker.artifact()
            await worker.execute_cell("repair")
            second = await worker.artifact()
            await worker.cleanup()
            self.assertEqual(first, second)
            return second

        self.assertEqual(asyncio.run(exercise()), b'{"actual":"worker-bytes"}')
        self.assertEqual(transport.reads, ["result.json", "result.json"])
        self.assertTrue(transport.removed and transport.absent)

    def test_trusted_read_rejects_unexpected_files_and_symlinks(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            PrimeP5DevelopmentDockerError,
            _trusted_workspace_read,
        )

        with TemporaryDirectory() as root:
            path = Path(root)
            (path / "solution.py").write_bytes(b"source")
            self.assertEqual(
                _trusted_workspace_read(root, "solution.py", ("solution.py",)),
                b"source",
            )
            (path / "extra").write_text("x")
            with self.assertRaises(PrimeP5DevelopmentDockerError):
                _trusted_workspace_read(root, "solution.py", ("solution.py",))
            (path / "extra").unlink()
            (path / "solution.py").unlink()
            (path / "solution.py").symlink_to("/etc/passwd")
            with self.assertRaises(PrimeP5DevelopmentDockerError):
                _trusted_workspace_read(root, "solution.py", ("solution.py",))
