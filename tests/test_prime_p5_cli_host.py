from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch


class TestP5CliHost(unittest.TestCase):
    def test_sets_the_finite_outer_deadline(self) -> None:
        from asterion.applications.prime_agent.operator.p5_cli_host import (
            P5_CLI_DEADLINE_SECONDS,
        )

        self.assertEqual(P5_CLI_DEADLINE_SECONDS, 300)

    def test_resolves_the_rehashed_prepared_p5_paths(self) -> None:
        from asterion.applications.prime_agent.operator import p5_cli_host as subject

        expected = object()
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "resolve_prepared_prime_development", return_value=expected) as resolve,
        ):
            self.assertIs(subject._prepared_paths(Path("/repo")), expected)
        resolve.assert_called_once_with(Path("/repo"), "p5")
