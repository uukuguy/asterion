from __future__ import annotations

import asyncio
from pathlib import Path
import unittest
from unittest.mock import patch

from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest


class TestPrimeP7CliHost(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_verifies_external_locks_before_reading_config(self) -> None:
        from asterion.applications.prime_agent.operator import p7_cli_host as subject

        order: list[str] = []
        paths = type("Paths", (), {"node": Path("/node"), "gateway_root": Path("/gateway"), "source_root": Path("/source")})()
        with (
            patch.object(Path, "is_file", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(subject, "verify_p7_development_resources", side_effect=lambda _: order.append("resource")),
            patch.object(subject, "verify_p7_development_runtime", side_effect=lambda _: order.append("runtime")),
            patch.object(subject, "dotenv_values", side_effect=lambda _: order.append("config") or {"A": "B"}),
        ):
            subject._preflight(Path("/repo"), paths)
        self.assertEqual(order, ["resource", "runtime", "config"])

    async def test_resolves_the_rehashed_prepared_p7_paths(self) -> None:
        from asterion.applications.prime_agent.operator import p7_cli_host as subject

        expected = object()
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "resolve_prepared_prime_development", return_value=expected) as resolve,
        ):
            self.assertIs(subject._prepared_paths(Path("/repo")), expected)
        resolve.assert_called_once_with(Path("/repo"), "p7")

    async def test_running_signal_cancels_lifecycle_and_waits_for_cleanup(self) -> None:
        from asterion.applications.prime_agent.operator import p7_cli_host as subject
        from asterion.runtimes.prime_agent_host import PrimeSmallVerificationCancelled

        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def lifecycle(_: Path, __: str) -> object:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        class Signal:
            cancelled = False

        signal = Signal()
        service = subject.PrimeP7DevelopmentService(
            Path("/unavailable"), lifecycle_runner=lifecycle
        )
        task = asyncio.create_task(
            service.verify(PrimeSmallVerificationRequest("p7-cancel"), signal=signal)
        )
        await started.wait()
        signal.cancelled = True

        with self.assertRaises(PrimeSmallVerificationCancelled):
            await task
        self.assertTrue(cleaned.is_set())

    async def test_run_closes_original_seccomp_descriptor_after_transport_copy(self) -> None:
        from asterion.applications.prime_agent.operator import p7_cli_host as subject

        paths = type("Paths", (), {
            "node": Path("/node"), "gateway_root": Path("/gateway"),
            "source_root": Path("/source"), "seccomp": Path("/seccomp"),
        })()

        class Broker:
            private_dir = Path("/broker/private")
            model_socket = Path("/broker/model.sock")

            def close(self) -> None:
                return None

        class Transport:
            closed = False

            def __init__(self, **_: object) -> None:
                return None

            def close(self) -> None:
                self.closed = True

        transport = Transport()

        async def reject(**_: object) -> object:
            raise ValueError

        with (
            patch.object(subject, "_prepared_paths", return_value=paths),
            patch.object(subject, "verify_p7_development_resources"),
            patch.object(subject, "verify_p7_development_runtime", return_value=object()),
            patch.object(subject, "_inspect_image", return_value="sha256:" + "a" * 64),
            patch.object(subject, "_sealed_seccomp", return_value=31),
            patch.object(subject, "_host_platform", return_value="linux/arm64"),
            patch.object(subject, "P7BrokerService", return_value=Broker()),
            patch.object(subject, "P7DevelopmentDockerTransport", return_value=transport),
            patch.object(subject, "P7DevelopmentDockerWorkerService", return_value=object()),
            patch.object(subject, "PrimeP7DevelopmentGateway", return_value=object()),
            patch.object(subject, "create_prime_p7_development_sdk_provider", return_value=object()),
            patch.object(subject, "_cfg", return_value={}),
            patch.object(subject, "run_p7_development_lifecycle", reject),
            patch.object(subject.os, "chown"),
            patch.object(subject.os, "chmod"),
            patch.object(subject.os, "close") as close,
        ):
            with self.assertRaises(ValueError):
                await subject._run(Path("/repo"), "p7-run", paths=paths)
        self.assertTrue(transport.closed)
        self.assertTrue(any(record.args == (31,) for record in close.call_args_list))


if __name__ == "__main__":
    unittest.main()
