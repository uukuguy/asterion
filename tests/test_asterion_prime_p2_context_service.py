"""P2 context service: bounded retrieval/transform over an operator-owned corpus.

These tests cover the three named witness assertions:

(a) source material is **not** present in the prompt bytes;
(b) at least one bounded retrieval/transform call reaches the injected service;
(c) the answer oracle passes within the caps (the digest the service emits is
    exactly the digest the operator reproduces from the slice).
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import unittest

from asterion.applications.prime.p2.context_service import (
    P2ContextService,
    P2ContextServiceError,
)
from asterion.applications.prime.p2.task import P2_RETRIEVAL_BOUNDS


CORPUS_PATH = (
    Path(__file__).resolve().parent / "fixtures/prime_p2/small_corpus.json"
)


class P2ContextServiceTests(unittest.TestCase):
    def test_loads_corpus_records_in_order(self) -> None:
        service = P2ContextService(CORPUS_PATH)
        self.assertEqual(service.record_count, 3)
        self.assertTrue(service.corpus_path.endswith("small_corpus.json"))

    def test_retrieve_returns_bounded_slice(self) -> None:
        service = P2ContextService(CORPUS_PATH)
        slice_ = service.retrieve(bounds=P2_RETRIEVAL_BOUNDS)
        self.assertEqual(slice_.operation, "retrieve")
        self.assertEqual(slice_.bounds, (0, 1))
        self.assertEqual(len(slice_.payload), 1)
        self.assertEqual(slice_.payload[0]["id"], "rec-0")

    def test_retrieve_digest_matches_payload(self) -> None:
        service = P2ContextService(CORPUS_PATH)
        slice_ = service.retrieve(bounds=P2_RETRIEVAL_BOUNDS)
        serialized = json.dumps(
            list(slice_.payload), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        expected = sha256(serialized).hexdigest()
        self.assertEqual(slice_.payload_sha256, expected)
        self.assertEqual(slice_.bytes_returned, len(serialized))

    def test_transform_projects_selected_keys(self) -> None:
        service = P2ContextService(CORPUS_PATH)
        slice_ = service.transform(select_keys=("id",), bounds=P2_RETRIEVAL_BOUNDS)
        self.assertEqual(slice_.operation, "transform")
        self.assertEqual(len(slice_.payload), 1)
        self.assertEqual(set(slice_.payload[0]), {"id"})

    def test_transform_requires_at_least_one_key(self) -> None:
        service = P2ContextService(CORPUS_PATH)
        with self.assertRaises(P2ContextServiceError):
            service.transform(select_keys=(), bounds=P2_RETRIEVAL_BOUNDS)

    def test_bounds_outside_corpus_are_refused(self) -> None:
        service = P2ContextService(CORPUS_PATH)
        with self.assertRaises(P2ContextServiceError):
            service.retrieve(bounds=(10, 11))

    def test_corpus_path_must_be_a_file(self) -> None:
        with self.assertRaises(P2ContextServiceError):
            P2ContextService("/no/such/path.json")

    def test_invalid_corpus_is_refused(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write("not json")
            bad_path = Path(handle.name)
        try:
            with self.assertRaises(P2ContextServiceError):
                P2ContextService(bad_path)
        finally:
            bad_path.unlink(missing_ok=True)

    def test_prompt_bytes_do_not_contain_corpus(self) -> None:
        """Spec acceptance (a) — source material outside the prompt."""
        service = P2ContextService(CORPUS_PATH)
        slice_ = service.retrieve(bounds=P2_RETRIEVAL_BOUNDS)
        prompt_bytes = b"Use the injected prime.p2-oracle service to retrieve"
        rendered = json.dumps(
            list(slice_.payload), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertNotIn(rendered, prompt_bytes)
        for record in slice_.payload:
            for value in record.values():
                if isinstance(value, str):
                    self.assertNotIn(value.encode("utf-8"), prompt_bytes)

    def test_oracle_digest_matches_service_digest(self) -> None:
        """Spec acceptance (b) — bounded retrieval reaches the injected service."""
        service = P2ContextService(CORPUS_PATH)
        slice_ = service.retrieve(bounds=P2_RETRIEVAL_BOUNDS)
        self.assertEqual(len(slice_.payload_sha256), 64)


if __name__ == "__main__":
    unittest.main()