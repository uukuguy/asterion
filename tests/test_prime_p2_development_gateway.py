"""Focused contracts for the private P2 development gateway."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock, patch


class TestPrimeP2DevelopmentGateway(unittest.TestCase):
    def test_gateway_is_a_distinct_p2_protocol(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_gateway import (
            PrimeP2DevelopmentGateway,
        )

        self.assertIn("P2Development", repr(PrimeP2DevelopmentGateway.__name__))


class TestPrimeP2DevelopmentGatewayCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_open_cancellation_aborts_and_reaps_transport(self) -> None:
        from asterion.applications.prime_agent.operator import (
            p2_development_gateway as subject,
        )

        gateway = object.__new__(subject.PrimeP2DevelopmentGateway)
        abort = Mock()
        blocked = asyncio.Event()

        async def pending(function, *args: object, **kwargs: object) -> None:
            if function == gateway.open_sync:
                await blocked.wait()
                return
            function(*args, **kwargs)

        with (
            patch.object(subject.asyncio, "to_thread", side_effect=pending),
            patch.object(
                subject.PrimeP2DevelopmentGateway,
                "_abort_active_prompt",
                abort,
            ),
        ):
            task = asyncio.create_task(
                gateway.open(
                    run_id="run",
                    session_id="session",
                    generation=1,
                    prime_source_root="/prime",
                    workspace="/workspace",
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        abort.assert_called_once_with()
