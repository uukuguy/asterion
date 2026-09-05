"""Provider-free contracts for the private P2 development workload."""

from __future__ import annotations

import unittest


class TestPrimeP2DevelopmentWorkload(unittest.TestCase):
    def test_corpus_is_canonical_and_private(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_workload import (
            P2_DEVELOPMENT_CORPUS_DIGEST,
            canonical_p2_development_corpus_bytes,
            p2_development_aggregate,
        )

        corpus = canonical_p2_development_corpus_bytes()
        self.assertEqual(len(corpus.splitlines()), 8)
        self.assertIn(b"P2_PRIVATE_SENTINEL", corpus)
        self.assertRegex(P2_DEVELOPMENT_CORPUS_DIGEST, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(p2_development_aggregate(corpus), {"count": 3, "sum": 23})

    def test_aggregate_rejects_noncanonical_or_wrong_answer(self) -> None:
        from asterion.applications.prime_agent.operator.p2_development_workload import (
            PrimeP2DevelopmentWorkloadError,
            p2_development_aggregate,
        )

        with self.assertRaises(PrimeP2DevelopmentWorkloadError):
            p2_development_aggregate(b'{"include":true,"value":5}\n')
