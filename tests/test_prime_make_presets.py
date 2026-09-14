"""Static contracts for public Prime Make presets."""

from __future__ import annotations

import unittest
from pathlib import Path


def _recipe(makefile: str, target: str) -> str:
    """Return one target's recipe block, ending at the first blank line."""

    marker = f"{target}:\n"
    if marker not in makefile:
        raise AssertionError(f"preset {target} is missing")
    return makefile.split(marker, 1)[1].split("\n\n", 1)[0]


class TestPrimeMakePresets(unittest.TestCase):
    def test_native_p1_builds_installed_wheel_in_shared_mount(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        recipe = _recipe(makefile, "asterion-prime-p1-run")
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

    def test_native_p7_solves_from_an_installed_wheel(self) -> None:
        """The P7 preset is the P1 shape, with operator-owned ARC and Pi values.

        The preset must reach the installed route and nothing else: no source
        tree on ``PYTHONPATH``, no interpreter from outside the distribution,
        and no literal for the ARC checkout layout, which the operator supplies
        as a value.
        """

        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text()
        recipe = _recipe(makefile, "asterion-prime-p7-solve")
        for literal in (
            '$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX',
            "trap",
            "build --wheel --out-dir",
            'orb -m "$(PRIME_ORB_MACHINE)"',
            "unset PYTHONPATH",
            "ASTERION_PRIME_OPERATOR_ROOT",
            "ASTERION_PRIME_NODE",
            "ASTERION_PRIME_ARC_ROOT",
            "ASTERION_PRIME_PI_ENTRY",
            "npm exec --offline --yes --package=node@22",
            "--isolated --with",
            '--with "ipython==9.17.1"',
            "arc_agi-0.9.9-py3-none-any.whl",
            "arcengine-0.9.3-py3-none-any.whl",
            "python -I -m asterion.applications.prime.p7.operator",
        ):
            self.assertIn(literal, recipe)
        for option in (
            "--provider",
            "--model",
            "--cost",
            "--deadline",
            "PYTHONPATH=src",
            "ASTERION_PRIME_WORKER_PYTHON",
            "external-prime",
            "venv/bin/python",
            "unset PYTHONPATH ASTERION_PRIME_NODE",
        ):
            self.assertNotIn(option, recipe)


if __name__ == "__main__":
    unittest.main()
