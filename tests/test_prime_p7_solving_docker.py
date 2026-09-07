from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _Transport:
    def __init__(self) -> None:
        self.removed = self.absent = False

    async def create_solving(self, **_: object) -> str:
        return "a" * 64

    async def execute_solving(self, *_: object) -> dict[str, object]:
        return {"cell_count": 2, "output": "", "is_error": False}

    async def remove_solving(self, *_: object) -> None:
        self.removed = True

    async def assert_solving_absent(self, *_: object) -> None:
        self.absent = True


class TestP7SolvingDocker(unittest.TestCase):
    def test_admission_is_closed_and_cancellation_cleans_uncertain_create(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_docker import (
            P7SolvingDockerTransport,
        )

        source = Path(__file__).resolve().parents[1] / "src/asterion/applications/prime_agent/operator/p7_solving_docker.py"
        text = source.read_text(encoding="utf-8")
        for required in ("\"none\"", "\"--read-only\"", "\"65534:65534\"", "\"--cap-drop\"", "\"ALL\"", "no-new-privileges:true", "seccomp=/proc/self/fd/", "workspace + \":/workspace:rw,rprivate\"", "socket_path + \":/broker/model.sock:ro,rprivate\"", "_CLEARED_BASE_IMAGE_ENVIRONMENT", "\"--pids-limit\"", "\"--memory\"", "\"--cpus\"", "image_digest"):
            self.assertIn(required, text)

        transport = object.__new__(P7SolvingDockerTransport)
        calls: list[str] = []

        async def cleanup(_: object, identity: str) -> None:
            calls.append(identity)

        with patch.object(P7SolvingDockerTransport, "_uncertain", cleanup):
            async def cancelled() -> None:
                with self.assertRaises(asyncio.CancelledError):
                    await transport._cleanup_cancelled("prime-p7-solving-test")
            asyncio.run(cancelled())
        self.assertEqual(calls, ["prime-p7-solving-test"])

    def test_worker_rejects_bad_results_and_redacts_public_errors(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_docker import (
            P7SolvingDockerError,
            P7SolvingDockerWorker,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, broker = root / "workspace", root / "broker"
            workspace.mkdir()
            broker.mkdir()
            worker = P7SolvingDockerWorker(
                image_digest="sha256:" + "a" * 64,
                transport=_Transport(),
                workspace=str(workspace),
                broker_private_dir=str(broker),
                broker_model_socket=str(broker / "model.sock"),
            )
            self.assertNotIn(str(root), repr(worker))
            async def exercise() -> None:
                await worker.acquire(b"# client")
                with self.assertRaises(P7SolvingDockerError):
                    await worker.execute_cell("x = 1")
                await worker.cleanup()
            with patch(
                "asterion.applications.prime_agent.operator.p7_solving_docker.os.fchown"
            ):
                asyncio.run(exercise())
            self.assertNotIn(str(root), str(P7SolvingDockerError()))
