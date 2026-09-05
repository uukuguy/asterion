"""Focused development-only subprocess provider checks."""

from __future__ import annotations

import asyncio
import os
import time
import unittest
from unittest import mock


class TestPrimeP1DevelopmentProvider(unittest.IsolatedAsyncioTestCase):
    async def test_one_call_returns_child_result_and_terminal_usage(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_provider as subject,
        )
        from asterion.applications.prime_agent.operator.model_broker import (
            PrimeModelBrokerTokenUsage,
        )

        provider = subject.create_prime_p1_development_provider(
            {
                "DEEPSEEK_API_KEY": "private-key",
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
            }
        )
        with mock.patch.object(
            subject,
            "_invoke_provider_sync",
            return_value=(b"answer = 42", PrimeModelBrokerTokenUsage(3, 4, 5)),
        ):
            self.assertEqual(await provider(b"request"), b"answer = 42")
        self.assertEqual(provider.terminal_usage(), PrimeModelBrokerTokenUsage(3, 4, 5))

    async def test_cancellation_kills_and_reaps_child_before_returning(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p1_development_provider as subject,
        )

        provider = subject.create_prime_p1_development_provider(
            {
                "DEEPSEEK_API_KEY": "private-key",
                "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash",
            }
        )

        def blocked(_: object, __: bytes) -> object:
            time.sleep(10)
            raise AssertionError("child should have been killed")

        with mock.patch.object(subject, "_invoke_provider_sync", side_effect=blocked):
            task = asyncio.create_task(provider(b"request"))
            for _ in range(100):
                if provider._child_pid is not None:  # noqa: SLF001 - reap boundary
                    break
                await asyncio.sleep(0.01)
            pid = provider._child_pid  # noqa: SLF001 - reap boundary
            self.assertIsInstance(pid, int)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(provider._child_pid)  # noqa: SLF001 - reap boundary
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)  # type: ignore[arg-type]
