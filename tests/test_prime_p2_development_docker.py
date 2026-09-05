"""Critical command and cleanup boundaries for the P2 Docker adapter."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from asterion.applications.prime_agent.operator.docker_cli import DockerCliResult
from asterion.applications.prime_agent.operator.p2_development_docker import (
    P2DevelopmentContainer,
    PrimeP2DevelopmentDockerError,
    PrimeP2DevelopmentDockerTransport,
)


class TestPrimeP2DevelopmentDocker(unittest.IsolatedAsyncioTestCase):
    async def test_cell_uses_fixed_ipython_entrypoint(self) -> None:
        transport = object.__new__(PrimeP2DevelopmentDockerTransport)
        transport._prefix = ("/usr/bin/docker",)  # type: ignore[attr-defined]
        transport._call = AsyncMock(return_value=DockerCliResult())  # type: ignore[method-assign]
        container = P2DevelopmentContainer("a" * 64, "run", "session")

        await transport.execute_cell(container, "x = 1", object())  # type: ignore[arg-type]

        argv = transport._call.await_args.args[0]  # type: ignore[attr-defined]
        self.assertIn("/usr/local/bin/ipython", argv)
        self.assertIn("HOME=/workspace", argv)
        self.assertNotIn("sh", argv)
        self.assertNotIn("bash", argv)
        self.assertEqual(
            transport._call.await_args.kwargs["max_output_bytes"], 4096  # type: ignore[attr-defined]
        )

    async def test_absence_requires_exact_daemon_missing_response(self) -> None:
        transport = object.__new__(PrimeP2DevelopmentDockerTransport)
        transport._prefix = ("/usr/bin/docker",)  # type: ignore[attr-defined]
        container = P2DevelopmentContainer("b" * 64, "run", "session")
        missing = (
            "Error: No such object: " + container.container_id + "\n"
        ).encode()
        transport._call_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=DockerCliResult(returncode=1, stderr=missing)
        )
        await transport.assert_absent(container, object())  # type: ignore[arg-type]

        transport._call_raw = AsyncMock(  # type: ignore[method-assign]
            return_value=DockerCliResult(returncode=1, stderr=b"permission denied\n")
        )
        with self.assertRaises(PrimeP2DevelopmentDockerError):
            await transport.assert_absent(container, object())  # type: ignore[arg-type]

    async def test_remove_rejects_unexpected_daemon_output(self) -> None:
        transport = object.__new__(PrimeP2DevelopmentDockerTransport)
        transport._prefix = ("/usr/bin/docker",)  # type: ignore[attr-defined]
        container = P2DevelopmentContainer("c" * 64, "run", "session")
        transport._call = AsyncMock(  # type: ignore[method-assign]
            return_value=DockerCliResult(stdout=b"unexpected\n")
        )
        with self.assertRaises(PrimeP2DevelopmentDockerError):
            await transport.remove(container, object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
