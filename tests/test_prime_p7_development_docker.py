from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import sys
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
    def test_admission_normalizes_docker_bind_mount_order(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_docker import (
            _normalized_bind_mounts,
            _normalized_mounts,
        )

        workspace = "/tmp/workspace"
        socket_path = "/tmp/broker/model.sock"
        expected_binds = tuple(
            sorted(
                (
                    (workspace + ":/workspace:rw,rprivate",),
                    (socket_path + ":/broker/model.sock:ro,rprivate",),
                )
            )
        )
        expected_mounts = tuple(
            sorted(
                (
                    ("bind", workspace, "/workspace", True, "rprivate"),
                    ("bind", socket_path, "/broker/model.sock", False, "rprivate"),
                )
            )
        )
        actual_mounts = [
            {
                "Type": "bind",
                "Source": socket_path,
                "Destination": "/broker/model.sock",
                "RW": False,
                "Propagation": "rprivate",
            },
            {
                "Type": "bind",
                "Source": workspace,
                "Destination": "/workspace",
                "RW": True,
                "Propagation": "rprivate",
            },
        ]

        self.assertEqual(
            _normalized_bind_mounts(
                [
                    socket_path + ":/broker/model.sock:ro,rprivate",
                    workspace + ":/workspace:rw,rprivate",
                ]
            ),
            expected_binds,
        )
        self.assertEqual(_normalized_mounts(actual_mounts), expected_mounts)

    def test_uncertain_create_cleanup_does_not_leak_p5_error(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            P5DevelopmentDockerTransport,
            PrimeP5DevelopmentDockerError,
        )
        from asterion.applications.prime_agent.operator.p7_development_docker import (
            P7DevelopmentDockerTransport,
            PrimeP7DevelopmentDockerError,
        )

        transport = object.__new__(P7DevelopmentDockerTransport)

        async def broken_cleanup(_: object, __: str) -> None:
            raise PrimeP5DevelopmentDockerError()

        with patch.object(P5DevelopmentDockerTransport, "_uncertain", broken_cleanup):
            with self.assertRaises(PrimeP7DevelopmentDockerError):
                asyncio.run(transport._uncertain("prime-p7-test"))

    def test_reader_admits_bounded_actions_larger_than_p5_cap(self) -> None:
        from asterion.applications.prime_agent.operator.p7_development_docker import (
            _READ_PROGRAM,
        )

        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            names = ("p7_client.py", "initial.json", "actions.json")
            for name in names:
                (workspace / name).write_bytes(
                    b"x" * (20 * 1024) if name == "actions.json" else b"x"
                )
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    _READ_PROGRAM,
                    str(workspace),
                    "actions.json",
                    *names,
                ],
                check=False,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout), 20 * 1024)

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
