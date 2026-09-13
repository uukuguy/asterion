"""Proves the gate fails on the real tree until Phase 1 removal completes."""

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

    def test_gate_detects_the_known_p1_operator_edges(self) -> None:
        paths = {v.path for v in find_source_detachment_violations(ROOT)}
        self.assertIn("src/asterion/applications/prime/p1/operator.py", paths)


if __name__ == "__main__":
    unittest.main()
