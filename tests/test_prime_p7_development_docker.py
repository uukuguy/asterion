from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class _Transport:
    def __init__(self) -> None:
        self.removed = self.absent = False

    async def create_p7(self, **_: object) -> str:
        return "a" * 64

    async def execute_p7(self, *_: object) -> None:
        return None

    async def read_p7(
        self, _: str, name: str, expected: tuple[str, ...], __: object
    ) -> bytes:
        if name not in expected:
            raise ValueError
        return (
            b"_PATH='/broker/model.sock'" if name == "p7_client.py" else name.encode()
        )

    async def remove_p7(self, *_: object) -> None:
        self.removed = True

    async def assert_p7_absent(self, *_: object) -> None:
        self.absent = True


class TestP7DevelopmentDocker(unittest.TestCase):
    def test_stages_exact_inventory_and_preserves_broker_client(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_docker import (
            P7DevelopmentDockerWorkerService,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace, broker = root / "workspace", root / "broker"
            workspace.mkdir()
            broker.mkdir()
            worker = P7DevelopmentDockerWorkerService(
                image_digest="sha256:" + "a" * 64,
                transport=_Transport(),
                run_id="run",
                session_id="session",
                goal_id="goal",
                workspace=str(workspace),
                broker_private_dir=str(broker),
                broker_model_socket=str(broker / "model.sock"),
                client_module=b"_PATH='/broker/model.sock'",
            )

            async def exercise() -> None:
                await worker.acquire()
                self.assertEqual(worker.container_digest, "sha256:" + "a" * 64)
                self.assertEqual(
                    (workspace / "p7_client.py").read_bytes(),
                    b"_PATH='/broker/model.sock'",
                )
                self.assertEqual(
                    await worker.snapshot(),
                    {"p7_client.py": b"_PATH='/broker/model.sock'"},
                )
                for count in range(1, 4):
                    self.assertEqual(
                        await worker.execute_cell("x"), {"cell_count": count}
                    )
                self.assertEqual(
                    set(await worker.snapshot()),
                    {"p7_client.py", "initial.json", "actions.json", "status.json"},
                )
                await worker.cleanup()

            with patch(
                "asterion.applications.prime_agent.operator.p7_development_docker.os.fchown"
            ) as transfer:
                asyncio.run(exercise())
            transfer.assert_called_once_with(unittest.mock.ANY, 65534, 65534)

    def test_rejects_client_that_does_not_target_container_socket(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_docker import (
            P7DevelopmentDockerWorkerService,
            PrimeP7DevelopmentDockerError,
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "workspace").mkdir()
            (root / "broker").mkdir()
            with self.assertRaises(PrimeP7DevelopmentDockerError):
                P7DevelopmentDockerWorkerService(
                    image_digest="sha256:" + "a" * 64,
                    transport=_Transport(),
                    run_id="run",
                    session_id="session",
                    goal_id="goal",
                    workspace=str(root / "workspace"),
                    broker_private_dir=str(root / "broker"),
                    broker_model_socket=str(root / "broker" / "model.sock"),
                    client_module=b"host.sock",
                )
