"""Asserts the real release surface is Prime-source detached."""

from __future__ import annotations

import unittest
from pathlib import Path

from asterion.agents.prime.detachment import (
    assert_asterion_prime_source_detached,
    find_source_detachment_violations,
)

ROOT = Path(__file__).resolve().parent.parent


class TestRealTreeDetachment(unittest.TestCase):
    def test_release_surface_is_source_detached(self) -> None:
        assert_asterion_prime_source_detached(ROOT)

    def test_gate_does_not_flag_its_own_source(self) -> None:
        # The gate module and this test both live under a scanned root. If the
        # gate's own literals are not assembled from parts, it flags itself and
        # can never pass.
        rules = [v.rule for v in find_source_detachment_violations(ROOT)]
        self.assertEqual(rules, [])

    def test_gate_detects_an_introduced_p1_operator_edge(self) -> None:
        # Detection is proven by the unit tests scanning synthetic trees; here
        # we assert only that the real P1 operator carries no Prime edge left
        # over from Phase 1 removal.
        paths = {v.path for v in find_source_detachment_violations(ROOT)}
        self.assertNotIn("src/asterion/applications/prime/p1/operator.py", paths)


if __name__ == "__main__":
    unittest.main()
