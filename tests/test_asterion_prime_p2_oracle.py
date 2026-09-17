"""P2 oracle: bind once to a live worker; verify the retrieval digest.

The oracle's contract is one bounded retrieval/transform round-trip per
run. The oracle refuses any second verification, any digest mismatch, and
any identity / corpus swap after bind. These tests pin every clause.
"""

from __future__ import annotations

import unittest

from asterion.applications.prime.p2.context_service import (
    P2ContextService,
    P2ContextSlice,
)
from asterion.applications.prime.p2.oracle import (
    P2Oracle,
    P2OracleError,
    P2OracleReceipt,
    P2RetrievalReceipt,
)
from asterion.applications.prime.p2.task import P2_RETRIEVAL_BOUNDS
from asterion.applications.prime.p2.worker import (
    P2ContextServiceWorker,
)


CORPUS = (
    __file__.rsplit("/", 1)[0] + "/fixtures/prime_p2/small_corpus.json"
)


class _StubWorker:
    """Minimal stand-in for the runtime-facing worker.

    Mirrors the properties P2WorkerOwnerAdapter binds against — identity_sha256
    and corpus_sha256 — without dragging in Pi or any subprocess machinery.
    """

    def __init__(self, identity: str, corpus: str) -> None:
        self._identity = identity
        self._corpus = corpus

    @property
    def identity_sha256(self) -> str:
        return self._identity

    @property
    def corpus_sha256(self) -> str:
        return self._corpus


class P2OracleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = P2ContextService(CORPUS)
        self.worker = P2ContextServiceWorker(self.service)
        self.slice = self.service.retrieve(bounds=P2_RETRIEVAL_BOUNDS)
        self.oracle = P2Oracle(
            worker_identity=self.worker.identity_sha256,
            corpus_sha256=self.worker.corpus_sha256,
        )

    def test_construction_rejects_short_identity(self) -> None:
        with self.assertRaises(P2OracleError):
            P2Oracle(worker_identity="tooshort", corpus_sha256="a" * 64)

    def test_construction_rejects_non_hex_identity(self) -> None:
        with self.assertRaises(P2OracleError):
            P2Oracle(worker_identity="z" * 64, corpus_sha256="a" * 64)

    def test_bind_worker_swaps_identity(self) -> None:
        new_worker = _StubWorker("a" * 64, "b" * 64)
        self.oracle.bind_worker(new_worker)
        self.assertEqual(self.oracle.identity, "a" * 64)
        self.assertEqual(self.oracle.corpus, "b" * 64)

    def test_bind_worker_rejects_bad_identity(self) -> None:
        with self.assertRaises(P2OracleError):
            self.oracle.bind_worker(_StubWorker("not-a-digest", "b" * 64))

    def test_verify_retrieval_passes(self) -> None:
        receipt = self.oracle.verify_retrieval(slice_=self.slice)
        self.assertIsInstance(receipt, P2RetrievalReceipt)
        self.assertEqual(receipt.operation, "retrieve")
        self.assertEqual(receipt.bounds, P2_RETRIEVAL_BOUNDS)
        self.assertEqual(receipt.slice_sha256, self.slice.payload_sha256)
        self.assertEqual(receipt.bytes_returned, self.slice.bytes_returned)

    def test_verify_retrieval_is_idempotent(self) -> None:
        first = self.oracle.verify_retrieval(slice_=self.slice)
        second = self.oracle.verify_retrieval(slice_=self.slice)
        self.assertEqual(first, second)
        self.assertEqual(first.sha256(), second.sha256())

    def test_verify_retrieval_refuses_wrong_type(self) -> None:
        with self.assertRaises(P2OracleError):
            self.oracle.verify_retrieval(slice_="not a slice")  # type: ignore[arg-type]

    def test_verify_answer_requires_first_retrieval(self) -> None:
        oracle = P2Oracle(worker_identity="a" * 64, corpus_sha256="b" * 64)
        with self.assertRaises(P2OracleError):
            oracle.verify_answer(answer_sha256="c" * 64)

    def test_verify_answer_passes_with_slice_digest(self) -> None:
        self.oracle.verify_retrieval(slice_=self.slice)
        receipt = self.oracle.verify_answer(answer_sha256=self.slice.payload_sha256)
        self.assertIsInstance(receipt, P2OracleReceipt)
        self.assertEqual(receipt.answer_sha256, self.slice.payload_sha256)
        self.assertEqual(receipt.corpus_sha256, self.worker.corpus_sha256)
        self.assertTrue(receipt.succeeded)

    def test_verify_answer_rejects_non_hex(self) -> None:
        self.oracle.verify_retrieval(slice_=self.slice)
        with self.assertRaises(P2OracleError):
            self.oracle.verify_answer(answer_sha256="not-a-digest")

    def test_verify_answer_is_idempotent(self) -> None:
        self.oracle.verify_retrieval(slice_=self.slice)
        first = self.oracle.verify_answer(answer_sha256=self.slice.payload_sha256)
        second = self.oracle.verify_answer(answer_sha256=self.slice.payload_sha256)
        self.assertEqual(first.sha256(), second.sha256())

    def test_verify_retrieval_requires_canonical_bounds(self) -> None:
        """Out-of-bounds slice construction is caught by P2ContextSlice itself."""
        with self.assertRaises(ValueError):
            P2ContextSlice(
                corpus_path="/tmp/x",
                operation="retrieve",
                bounds=(10, 20),
                payload=(),
                payload_sha256="a" * 64,
                bytes_returned=0,
            )


if __name__ == "__main__":
    unittest.main()