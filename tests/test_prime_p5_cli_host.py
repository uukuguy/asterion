from __future__ import annotations

import unittest


class TestP5CliHost(unittest.TestCase):
    def test_sets_the_finite_outer_deadline(self) -> None:
        from asterion.applications.prime_agent.operator.p5_cli_host import (
            P5_CLI_DEADLINE_SECONDS,
        )

        self.assertEqual(P5_CLI_DEADLINE_SECONDS, 300)
