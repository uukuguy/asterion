"""P2 worker adapter: identity, corpus, lifecycle, idempotent close."""

from __future__ import annotations

import asyncio
import unittest

from asterion.applications.prime.p2.context_service import P2ContextService
from asterion.applications.prime.p2.worker import (
    P2ContextServiceWorker,
    P2WorkerCleanupReceipt,
    digest,
)


CORPUS = (
    __file__.rsplit("/", 1)[0] + "/fixtures/prime_p2/small_corpus.json"
)


class P2WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = P2ContextService(CORPUS)
        self.worker = P2ContextServiceWorker(self.service)

    def test_identity_is_digest_of_corpus_path(self) -> None:
        expected = digest({"corpus_path": self.service.corpus_path})
        self.assertEqual(self.worker.identity_sha256, expected)
        self.assertEqual(len(self.worker.identity_sha256), 64)

    def test_corpus_digest_is_digest_of_records(self) -> None:
        expected = digest(list(self.service._records))  # type: ignore[attr-defined]
        self.assertEqual(self.worker.corpus_sha256, expected)

    def test_validate_lifecycle_returns_same_object_before_close(self) -> None:
        first = self.worker.validate_lifecycle()
        second = self.worker.validate_lifecycle()
        self.assertIs(first, second)

    def test_retrieve_delegates_to_service(self) -> None:
        slice_ = self.worker.retrieve(bounds=(0, 1))
        self.assertEqual(slice_.operation, "retrieve")
        self.assertEqual(slice_.bounds, (0, 1))

    def test_transform_delegates_to_service(self) -> None:
        slice_ = self.worker.transform(select_keys=("id",), bounds=(0, 1))
        self.assertEqual(slice_.operation, "transform")
        self.assertEqual(len(slice_.payload), 1)

    def test_close_marks_closed_and_returns_receipt(self) -> None:
        async def go() -> P2WorkerCleanupReceipt:
            return await self.worker.close()

        receipt = asyncio.run(go())
        self.assertIsInstance(receipt, P2WorkerCleanupReceipt)
        self.assertEqual(receipt.worker_identity_sha256, self.worker.identity_sha256)
        self.assertTrue(receipt.reaped)
        self.assertTrue(receipt.pipes_closed)
        self.assertTrue(receipt.root_removed)

    def test_close_is_idempotent(self) -> None:
        async def go() -> tuple[P2WorkerCleanupReceipt, P2WorkerCleanupReceipt]:
            first = await self.worker.close()
            second = await self.worker.close()
            return first, second

        first, second = asyncio.run(go())
        self.assertIs(first, second)

    def test_close_then_retrieve_raises(self) -> None:
        async def go() -> None:
            await self.worker.close()

        asyncio.run(go())
        with self.assertRaises(ValueError):
            self.worker.retrieve(bounds=(0, 1))

    def test_close_then_validate_lifecycle_raises(self) -> None:
        async def go() -> None:
            await self.worker.close()

        asyncio.run(go())
        with self.assertRaises(ValueError):
            self.worker.validate_lifecycle()


if __name__ == "__main__":
    unittest.main()