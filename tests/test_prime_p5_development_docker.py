from __future__ import annotations

import unittest
import asyncio
from pathlib import Path
import subprocess
import sys
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

    def test_deployed_read_program_rejects_unexpected_files_and_symlinks(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            _READ_PROGRAM,
        )

        def run(root: str) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                (
                    sys.executable,
                    "-I",
                    "-c",
                    _READ_PROGRAM,
                    root,
                    "solution.py",
                    "solution.py",
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        with TemporaryDirectory() as root:
            path = Path(root)
            (path / "solution.py").write_bytes(b"source")
            self.assertEqual(run(root).stdout, b"source")
            (path / "extra").write_text("x")
            self.assertNotEqual(run(root).returncode, 0)
            (path / "extra").unlink()
            (path / "solution.py").unlink()
            (path / "solution.py").symlink_to("/etc/passwd")
            self.assertNotEqual(run(root).returncode, 0)
