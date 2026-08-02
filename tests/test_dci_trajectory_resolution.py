from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from asterion.capabilities.dci.implementation.research.trajectory_resolution import (
    _parse_gold_manifest,
    validate_gold_manifest_bytes,
)


class DciCoverageOnlyTrajectoryTests(unittest.TestCase):
    def test_coverage_manifest_validates_without_inventing_evidence_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "corpus"
            corpus.mkdir()
            body = "alpha evidence\n"
            (corpus / "doc.txt").write_text(body, encoding="utf-8")
            manifest = {
                "schema": "dci.retrieval-coverage-manifest/v1",
                "dataset_id": "bright.biology",
                "query_id": "q-1",
                "documents": [
                    {
                        "id": "doc.txt",
                        "path": "doc.txt",
                        "sha256": hashlib.sha256(body.encode()).hexdigest(),
                    }
                ],
            }
            encoded = (
                json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode()

            dataset_id, query_id, gold_ids = validate_gold_manifest_bytes(
                encoded, corpus_dir=corpus
            )
            _dataset, _query, documents, _snapshots = _parse_gold_manifest(
                encoded, corpus
            )

            self.assertEqual((dataset_id, query_id, gold_ids), ("bright.biology", "q-1", ("doc.txt",)))
            self.assertIsNone(documents[0].evidence_spans)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
