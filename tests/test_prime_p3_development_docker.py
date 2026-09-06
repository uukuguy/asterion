"""Focused lifecycle and isolation boundaries for P3 Docker workers."""

from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

from asterion.applications.prime_agent.operator.docker_cli import DockerCliResult
from asterion.applications.prime_agent.operator.p3_development_docker import (
    P3DevelopmentContainer,
    PrimeP3DevelopmentDockerTransport,
)


class TestPrimeP3DevelopmentDocker(unittest.IsolatedAsyncioTestCase):
    def _transport(self) -> PrimeP3DevelopmentDockerTransport:
        transport = object.__new__(PrimeP3DevelopmentDockerTransport)
        transport._prefix = ("/usr/bin/docker",)  # type: ignore[attr-defined]
        transport._platform = type("Platform", (), {"os": "linux", "architecture": "amd64", "variant": None})()  # type: ignore[attr-defined]
        transport._seccomp_profile_fd = 31  # type: ignore[attr-defined]
        transport._preflight = AsyncMock()  # type: ignore[method-assign]
        transport._call = AsyncMock(return_value=DockerCliResult(stdout=b"a" * 64 + b"\n"))  # type: ignore[method-assign]
        transport._call_raw = AsyncMock(return_value=DockerCliResult())  # type: ignore[method-assign]
        transport._close_fd = lambda _: None  # type: ignore[method-assign]
        transport._claim_seccomp_fds = lambda _: (31, 32, 33)  # type: ignore[method-assign]
        return transport

    async def test_create_uses_exact_roles_and_root_only_socket_mount(self) -> None:
        transport = self._transport()
        transport._call = AsyncMock(  # type: ignore[method-assign]
            side_effect=[DockerCliResult(stdout=(character * 64 + "\n").encode()) for character in ("a", "b", "c")]
        )

        workers = await transport.create_workers(
            image_digest="sha256:" + "a" * 64,
            run_id="run",
            workspace="/host/workspace",
            rlm_socket_directory="/host/rlm",
            control=object(),  # type: ignore[arg-type]
        )

        self.assertEqual([worker.role for worker in workers], ["root", "implementation", "review"])
        commands = [call.args[0] for call in transport._call.await_args_list]  # type: ignore[attr-defined]
        self.assertEqual(len(commands), 3)
        self.assertIn("/host/workspace:/workspace:rw,rprivate", commands[0])
        self.assertNotIn("/workspace:rw,nodev,noexec,nosuid,size=67108864,uid=65534,gid=65534,mode=0700", commands[0])
        self.assertIn("/tmp:rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700", commands[0])
        self.assertIn("/host/rlm:/run/asterion-rlm:ro,rprivate", commands[0])
        for command in commands[1:]:
            self.assertIn("/host/workspace:/workspace:rw,rprivate", command)
            self.assertNotIn("/host/rlm:/run/asterion-rlm:ro,rprivate", command)
            self.assertNotIn("asterion_rlm", " ".join(command))

    async def test_execute_uses_ipython_without_shell(self) -> None:
        transport = self._transport()
        container = P3DevelopmentContainer("root", "a" * 64)

        await transport.execute(container, "x = 1", object())  # type: ignore[arg-type]

        command = transport._call.await_args.args[0]  # type: ignore[attr-defined]
        self.assertIn("/usr/local/bin/ipython", command)
        self.assertNotIn("sh", command)
        self.assertNotIn("bash", command)
        self.assertEqual(transport._call.await_args.kwargs["max_output_bytes"], 4096)  # type: ignore[attr-defined]

    async def test_cleanup_removes_reverse_order_and_rejects_unknown_worker(self) -> None:
        transport = self._transport()
        workers = tuple(P3DevelopmentContainer(role, char * 64) for role, char in (("root", "a"), ("implementation", "b"), ("review", "c")))
        transport._call = AsyncMock(  # type: ignore[method-assign]
            side_effect=[DockerCliResult(stdout=(container.container_id + "\n").encode()) for container in reversed(workers)]
        )

        await transport.cleanup(workers, object())  # type: ignore[arg-type]

        commands = [call.args[0] for call in transport._call.await_args_list]  # type: ignore[attr-defined]
        self.assertEqual([command[-1] for command in commands], ["c" * 64, "b" * 64, "a" * 64])
        with self.assertRaises(ValueError):
            P3DevelopmentContainer("other", "d" * 64)

    async def test_absence_requires_all_three_daemon_identities_missing(self) -> None:
        transport = self._transport()
        workers = tuple(P3DevelopmentContainer(role, char * 64) for role, char in (("root", "a"), ("implementation", "b"), ("review", "c")))
        transport._call_raw = AsyncMock(  # type: ignore[method-assign]
            side_effect=[
                DockerCliResult(returncode=1, stderr=("Error: No such object: " + worker.container_id + "\n").encode())
                for worker in workers
            ]
        )

        await transport.assert_absent(workers, object())  # type: ignore[arg-type]

        self.assertEqual(transport._call_raw.await_count, 3)  # type: ignore[attr-defined]

    async def test_start_failure_forces_reverse_cleanup(self) -> None:
        transport = self._transport()
        workers = tuple(P3DevelopmentContainer(role, char * 64) for role, char in (("root", "a"), ("implementation", "b"), ("review", "c")))
        transport._call = AsyncMock(side_effect=[DockerCliResult(), RuntimeError("private")])  # type: ignore[method-assign]

        with self.assertRaisesRegex(ValueError, "prime P3 development docker worker is unavailable"):
            await transport.start_workers(workers, object())  # type: ignore[arg-type]

        commands = [call.args[0] for call in transport._call_raw.await_args_list]  # type: ignore[attr-defined]
        self.assertEqual([command[-1] for command in commands], ["c" * 64, "b" * 64, "a" * 64])

    async def test_create_rejects_duplicate_daemon_identity(self) -> None:
        transport = self._transport()
        transport._call = AsyncMock(  # type: ignore[method-assign]
            return_value=DockerCliResult(stdout=b"a" * 64 + b"\n")
        )

        with self.assertRaisesRegex(ValueError, "prime P3 development docker worker is unavailable"):
            await transport.create_workers(
                image_digest="sha256:" + "a" * 64,
                run_id="run",
                workspace="/host/workspace",
                rlm_socket_directory="/host/rlm",
                control=object(),  # type: ignore[arg-type]
            )


class TestP3DevelopmentDockerDescriptors(unittest.TestCase):
    def test_seccomp_duplicate_is_closed_when_inheritable_marking_fails(self) -> None:
        transport = object.__new__(PrimeP3DevelopmentDockerTransport)
        transport._seccomp_profile_fd = 10  # type: ignore[attr-defined]
        transport._close_fd = Mock()  # type: ignore[method-assign]

        with patch("asterion.applications.prime_agent.operator.p3_development_docker.os.dup", return_value=20), patch(
            "asterion.applications.prime_agent.operator.p3_development_docker.os.set_inheritable",
            side_effect=OSError("denied"),
        ), self.assertRaisesRegex(ValueError, "prime P3 development docker worker is unavailable"):
            transport._claim_seccomp_fds(3)  # type: ignore[attr-defined]

        self.assertEqual(transport._close_fd.call_args_list, [call(20), call(10)])  # type: ignore[attr-defined]


class TestP3RootRlmSchema(unittest.TestCase):
    def test_rejects_role_or_selector_outside_closed_schema(self) -> None:
        path = Path(__file__).parents[1] / "src/asterion/applications/prime_agent/operator/p3_development_image/asterion_rlm.py"
        specification = importlib.util.spec_from_file_location("p3_root_rlm_test", path)
        assert specification is not None and specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)

        with self.assertRaises(module.RlmRequestError):
            module.spawn("root")
        with self.assertRaises(module.RlmRequestError):
            module.delete({"provider": "untrusted"})
