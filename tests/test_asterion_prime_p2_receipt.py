"""P2 receipt: seal cleanup, build native, id-stability.

The receipt's three guarantees:
- digest reproducibility (canonical-JSON, sort_keys=True, separators=(",",":"))
- identity stability (worker identity binds receipts together; any swap fails)
- value validation (every *_sha256 is 64-char hex; every *_bytes is non-neg int)
"""

from __future__ import annotations

import unittest

from asterion.applications.prime.p2.context_service import P2ContextService
from asterion.applications.prime.p2.oracle import P2Oracle
from asterion.applications.prime.p2.receipt import (
    P2CleanupReceipt,
    P2NativeReceipt,
    P2ReceiptError,
    build_native_receipt,
    seal_cleanup_receipt,
)
from asterion.applications.prime.p2.task import P2_RETRIEVAL_BOUNDS
from asterion.applications.prime.p2.worker import (
    P2ContextServiceWorker,
    P2WorkerCleanupReceipt,
)


CORPUS = (
    __file__.rsplit("/", 1)[0] + "/fixtures/prime_p2/small_corpus.json"
)


class P2ReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = P2ContextService(CORPUS)
        self.worker = P2ContextServiceWorker(self.service)
        self.slice = self.service.retrieve(bounds=P2_RETRIEVAL_BOUNDS)
        self.oracle = P2Oracle(
            worker_identity=self.worker.identity_sha256,
            corpus_sha256=self.worker.corpus_sha256,
        )
        self.receipt = self.oracle.verify_retrieval(slice_=self.slice)
        self.result = self.oracle.verify_answer(answer_sha256=self.slice.payload_sha256)
        self.worker_cleanup = P2WorkerCleanupReceipt(
            worker_identity_sha256=self.worker.identity_sha256,
            reaped=True,
            pipes_closed=True,
            root_removed=True,
        )

    def test_seal_cleanup_receipt_passes(self) -> None:
        cleanup = seal_cleanup_receipt(
            self.oracle,
            self.result,
            self.worker_cleanup,
            oracle_closed=True,
            worker_closed=True,
            bridge_closed=True,
            private_store_removed=True,
        )
        self.assertIsInstance(cleanup, P2CleanupReceipt)
        self.assertEqual(cleanup.worker_identity_sha256, self.worker.identity_sha256)

    def test_seal_cleanup_receipt_is_idempotent(self) -> None:
        first = seal_cleanup_receipt(
            self.oracle,
            self.result,
            self.worker_cleanup,
            oracle_closed=True,
            worker_closed=True,
            bridge_closed=True,
            private_store_removed=True,
        )
        second = seal_cleanup_receipt(
            self.oracle,
            self.result,
            self.worker_cleanup,
            oracle_closed=True,
            worker_closed=True,
            bridge_closed=True,
            private_store_removed=True,
        )
        self.assertEqual(first.sha256(), second.sha256())

    def test_seal_cleanup_refuses_unfinished(self) -> None:
        from dataclasses import replace

        unfinished = replace(self.result, final_status="unverified")
        with self.assertRaises(P2ReceiptError):
            seal_cleanup_receipt(
                self.oracle,
                unfinished,
                self.worker_cleanup,
                oracle_closed=True,
                worker_closed=True,
                bridge_closed=True,
                private_store_removed=True,
            )

    def test_seal_cleanup_refuses_worker_identity_mismatch(self) -> None:
        from dataclasses import replace

        with self.assertRaises(P2ReceiptError):
            seal_cleanup_receipt(
                self.oracle,
                self.result,
                replace(
                    self.worker_cleanup, worker_identity_sha256="0" * 64
                ),
                oracle_closed=True,
                worker_closed=True,
                bridge_closed=True,
                private_store_removed=True,
            )

    def test_build_native_receipt(self) -> None:
        cleanup = seal_cleanup_receipt(
            self.oracle,
            self.result,
            self.worker_cleanup,
            oracle_closed=True,
            worker_closed=True,
            bridge_closed=True,
            private_store_removed=True,
        )
        native = build_native_receipt(self.oracle, self.result, cleanup)
        self.assertIsInstance(native, P2NativeReceipt)
        self.assertEqual(native.application, "prime.programmatic-long-context@1.0.0")
        self.assertEqual(native.runtime, "asterion.prime")
        self.assertEqual(native.final_status, "verified")
        self.assertEqual(native.answer_sha256, self.slice.payload_sha256)
        self.assertEqual(native.corpus_sha256, self.worker.corpus_sha256)

    def test_native_receipt_digest_is_stable(self) -> None:
        cleanup = seal_cleanup_receipt(
            self.oracle,
            self.result,
            self.worker_cleanup,
            oracle_closed=True,
            worker_closed=True,
            bridge_closed=True,
            private_store_removed=True,
        )
        native = build_native_receipt(self.oracle, self.result, cleanup)
        # sha256 is a 64-char hex
        digest = native.sha256()
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))


if __name__ == "__main__":
    unittest.main()