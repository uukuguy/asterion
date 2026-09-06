"""Static contracts for public Prime Make presets."""

from __future__ import annotations

import unittest
from pathlib import Path


class TestPrimeMakePresets(unittest.TestCase):
    def test_p2_self_prepares_then_runs_with_progress_in_one_orb_shell(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        recipe = makefile.split("prime-p2-run:\n", 1)[1].split("\nprime-p3-run:", 1)[0]
        self.assertIn(
            "[prime-p2] Programmatic long context: use the fixed corpus, execute one cell, and validate the answer",
            recipe,
        )
        self.assertEqual(recipe.count("orb -m \"$(PRIME_ORB_MACHINE)\" -u root -w \"$(CURDIR)\""), 1)
        self.assertLess(recipe.index("tools/prepare_prime_development.py --scenario p2"), recipe.index("asterion run --progress"))
        for required in (
            "--extra prime",
            "--python /usr/bin/python3",
            "--isolated",
            "--provider prime-agent",
            "--application prime.programmatic-long-context@1.0.0",
            "--runtime prime.agent",
            "--input fixed-small-verification",
        ):
            with self.subTest(required=required):
                self.assertIn(required, recipe)


if __name__ == "__main__":
    unittest.main()
