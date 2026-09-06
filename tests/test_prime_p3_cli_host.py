from __future__ import annotations
import asyncio
import unittest
from unittest.mock import patch


class TestPrimeP3CliHost(unittest.TestCase):
    def test_projection_is_digest_only(self) -> None:
        from asterion.applications.prime_agent.operator.p3_cli_host import (
            project_p3_development_trace,
        )
        from asterion.applications.prime_agent.operator.p3_development_host import (
            PrimeP3DevelopmentTrace,
        )

        self.assertEqual(
            set(
                project_p3_development_trace(
                    PrimeP3DevelopmentTrace("sha256:" + "0" * 64)
                )
            ),
            {"scope", "promotion", "trace_sha256"},
        )


class TestPrimeP3CliService(unittest.IsolatedAsyncioTestCase):
    async def test_verification_may_run_longer_than_poll_interval(self) -> None:
        from asterion.applications.prime_agent.operator import p3_cli_host as subject
        from asterion.applications.prime_agent.operator.p3_development_host import PrimeP3DevelopmentTrace
        from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest

        async def run(**_: object) -> PrimeP3DevelopmentTrace:
            await asyncio.sleep(0.1)
            return PrimeP3DevelopmentTrace("sha256:" + "1" * 64)

        resources = subject._Resources(object(), {}, "node", "entry", "/prime", -1)
        service = subject.PrimeP3SmallVerificationService(resources)
        with patch.object(subject, "run_prime_p3_development", run):
            result = await service.verify(PrimeSmallVerificationRequest("p3-delayed"))
        self.assertEqual(result.scope, "p3-development")

    async def test_cancellation_waits_for_run_cleanup(self) -> None:
        from asterion.applications.prime_agent.operator import p3_cli_host as subject
        from asterion.runtimes.prime_agent_host import (
            PrimeSmallVerificationCancelled,
            PrimeSmallVerificationRequest,
        )

        cleaned = asyncio.Event()

        async def run(**_: object) -> object:
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)
                cleaned.set()

        class Signal:
            cancelled = False

        signal = Signal()
        resources = subject._Resources(object(), {}, "node", "entry", "/prime", -1)
        service = subject.PrimeP3SmallVerificationService(resources)
        with patch.object(subject, "run_prime_p3_development", run):
            task = asyncio.create_task(
                service.verify(PrimeSmallVerificationRequest("p3-cancel"), signal=signal)
            )
            await asyncio.sleep(0.06)
            signal.cancelled = True
            with self.assertRaises(PrimeSmallVerificationCancelled):
                await task
        self.assertTrue(cleaned.is_set())
