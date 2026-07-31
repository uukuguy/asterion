from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from asterion.capabilities.dci.implementation.evaluation.benchmark import (
    _Directory,
    _RowAuthority,
    _publish_reproduction_evidence,
)


class DciBenchmarkReproductionEvidenceTests(unittest.TestCase):
    def test_partial_out_of_order_results_write_evidence_to_matching_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authorities = {}
            for index, query_id in enumerate(("q-1", "q-2")):
                path = root / query_id
                path.mkdir()
                authorities[query_id] = _RowAuthority(
                    _Directory(os.open(path, os.O_RDONLY | os.O_DIRECTORY))
                )
            results = [
                {
                    "query_id": "q-2",
                    "row_fingerprint": "a" * 64,
                    "status": "completed",
                    "agent_operation_performed": False,
                    "judge_operation_performed": False,
                    "is_correct": True,
                },
                {
                    "query_id": "q-1",
                    "row_fingerprint": "b" * 64,
                    "status": "completed",
                    "agent_operation_performed": False,
                    "judge_operation_performed": False,
                    "is_correct": True,
                },
            ]
            metrics = [
                {"query_id": "q-2", "is_correct": True},
                {"query_id": "q-1", "is_correct": True},
            ]
            try:
                _publish_reproduction_evidence(
                    rows=(object(), object()),
                    results=results,
                    metrics=metrics,
                    request=SimpleNamespace(mode="qa"),
                    authorities=authorities,
                )
                for query_id in ("q-1", "q-2"):
                    evidence = json.loads(
                        (root / query_id / "reproduction-evidence.json").read_text()
                    )
                    self.assertEqual(evidence["query_id"], query_id)
            finally:
                for authority in authorities.values():
                    authority.close()


if __name__ == "__main__":
    unittest.main()
