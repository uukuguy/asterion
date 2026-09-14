"""Static contracts for public Prime Make presets."""

from __future__ import annotations

import unittest
from pathlib import Path


class TestPrimeMakePresets(unittest.TestCase):
    def test_native_p1_builds_installed_wheel_in_shared_mount(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        self.assertIn("asterion-prime-p1-run:\n", makefile)
        recipe = makefile.split("asterion-prime-p1-run:\n", 1)[1].split("\n\n", 1)[0]
        for literal in (
            '$(CURDIR)/.asterion-prime-p1-wheel.XXXXXX',
            "trap",
            "build --wheel --out-dir",
            'orb -m "$(PRIME_ORB_MACHINE)"',
            "unset PYTHONPATH",
            "ASTERION_PRIME_OPERATOR_ROOT",
            "ASTERION_PRIME_NODE",
            "npm exec --offline --yes --package=node@22",
            "--isolated --with",
            '--with "ipython==9.17.1"',
            "python -I -m asterion.applications.prime.p1.operator",
        ):
            self.assertIn(literal, recipe)
        for option in (
            "--provider",
            "--model",
            "--cost",
            "--deadline",
            "PYTHONPATH=src",
            "ASTERION_PRIME_WORKER_PYTHON",
            "unset PYTHONPATH ASTERION_PRIME_NODE",
        ):
            self.assertNotIn(option, recipe)


if __name__ == "__main__":
    unittest.main()
