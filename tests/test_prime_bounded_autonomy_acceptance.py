from __future__ import annotations

import unittest

from asterion.applications.prime_agent.bounded_autonomy_acceptance import (
    BoundedAutonomyAcceptanceError,
    accept_bounded_autonomy,
)


class TestBoundedAutonomyAcceptance(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_invalid_inputs_before_injected_services(self) -> None:
        with self.assertRaises(BoundedAutonomyAcceptanceError):
            await accept_bounded_autonomy(
                gate=object(), first_workspace=object(), second_workspace=object(),
                trace=object(), disposed=True, reaped=True,
            )
