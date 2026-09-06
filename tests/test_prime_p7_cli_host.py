from __future__ import annotations

import asyncio
from pathlib import Path
import unittest

from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest


class TestPrimeP7CliHost(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
