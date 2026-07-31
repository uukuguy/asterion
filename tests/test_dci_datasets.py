from __future__ import annotations

import json
import unittest

from asterion.capabilities.dci.implementation.datasets import (
    load_bright_benchmark_rows_bytes,
)


class TestBrightDatasetRows(unittest.TestCase):
    def test_bright_loader_canonicalizes_crlf_in_query_text(self) -> None:
        row = {
            "query_id": "one",
            "query": "first line\r\nsecond line",
            "answer": "answer",
            "gold_ids": ["doc-1"],
            "gold_ids_long": ["doc-long-1"],
            "excluded_ids": ["doc-excluded-1"],
            "id": "one",
            "reasoning": "reasoning",
        }

        rows = load_bright_benchmark_rows_bytes(
            (json.dumps(row) + "\n").encode("utf-8"), expected_count=1
        )

        self.assertEqual(rows[0].query, "first line\nsecond line")
