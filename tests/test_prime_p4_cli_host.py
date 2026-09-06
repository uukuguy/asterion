from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest


class TestPrimeP4CliHost(unittest.IsolatedAsyncioTestCase):
    async def test_service_projects_the_injected_lifecycle_trace(self) -> None:
        from asterion.applications.prime_agent.operator import p4_cli_host as subject

        observed: list[tuple[object, str]] = []

        async def lifecycle(resources: object, run_id: str) -> object:
            observed.append((resources, run_id))
            return SimpleNamespace(trace_sha256="sha256:" + "a" * 64)

        resources = subject._P4CliResources(
            "sha256:" + "b" * 64, object(), {}, "node", "entry", "/prime", -1
        )
        service = subject.PrimeP4SmallVerificationService(
            resources, lifecycle_runner=lifecycle
        )
        result = await service.verify(PrimeSmallVerificationRequest("p4-projection"))

        self.assertEqual(observed, [(resources, "p4-projection")])
        self.assertEqual(result.run_id, "p4-projection")
        self.assertEqual(result.scope, "p4-development")
        self.assertEqual(result.promotion, "unpromoted")
        self.assertEqual(result.trace_sha256, "sha256:" + "a" * 64)

    async def test_cancellation_waits_for_injected_lifecycle_cleanup(self) -> None:
        from asterion.applications.prime_agent.operator import p4_cli_host as subject
        from asterion.runtimes.prime_agent_host import PrimeSmallVerificationCancelled

        cleaned = asyncio.Event()

        async def lifecycle(_: object, __: str) -> object:
            try:
                await asyncio.Future()
            finally:
                cleaned.set()

        class Signal:
            cancelled = False

        signal = Signal()
        service = subject.PrimeP4SmallVerificationService(
            subject._P4CliResources(
                "sha256:" + "b" * 64, object(), {}, "node", "entry", "/prime", -1
            ),
            lifecycle_runner=lifecycle,
        )
        task = asyncio.create_task(
            service.verify(PrimeSmallVerificationRequest("p4-cancel"), signal=signal)
        )
        await asyncio.sleep(0.06)
        signal.cancelled = True
        with self.assertRaises(PrimeSmallVerificationCancelled):
            await task
        self.assertTrue(cleaned.is_set())

    async def test_preflight_redacts_and_closes_created_transport_on_failure(self) -> None:
        from asterion.applications.prime_agent.operator import p4_cli_host as subject

        transport = SimpleNamespace(close=Mock())
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(
                subject, "_regular_executable", side_effect=(Path("/docker"), Path("/node"))
            ),
            patch.object(subject.os, "lstat", return_value=SimpleNamespace(st_mode=0)),
            patch.object(subject.stat, "S_ISSOCK", return_value=True),
            patch.object(subject, "_regular_file", return_value=Path("/entry")),
            patch.object(subject, "_regular_directory", return_value=Path("/prime")),
            patch.object(subject, "_sealed_seccomp", return_value=73),
            patch.object(subject, "_inspect_image", return_value="sha256:" + "a" * 64),
            patch.object(subject, "_host_platform", return_value=object()),
            patch.object(subject, "P1BDevelopmentSnapshotTransport", return_value=transport),
            patch.object(subject, "_operator_config", side_effect=RuntimeError("SENTINEL")),
            patch.object(subject.os, "close"),
        ):
            with self.assertRaises(subject.PrimeP4CliHostError) as raised:
                subject._preflight(Path("/repo"))
        self.assertNotIn("SENTINEL", str(raised.exception))
        transport.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
