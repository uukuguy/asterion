from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from asterion.applications.grid_regulation import (
    RegulationCitationError,
    RegulationQuery,
    cite_regulation,
    write_demo_corpus,
)

PROJECT = Path(__file__).resolve().parents[1]


class GridRegulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_citation_uses_document_anchors_and_hides_span_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_demo_corpus(root)
            citation = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx,pdf",
            )
            patrol = await cite_regulation(
                root,
                RegulationQuery("5.2", "DL/T 9000-2024", "每季度一次"),
                document_tools="docx,pdf",
            )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="pdf",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.3", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx,pdf",
                )

        self.assertEqual(citation.calls, ("document-read",))
        self.assertEqual(citation.anchors[0]["document"], "grounding.docx")
        self.assertEqual(citation.anchors[0]["kind"], "docx-paragraph")
        self.assertEqual(patrol.anchors[0]["document"], "patrol.pdf")
        self.assertEqual(patrol.anchors[0]["position"]["page"], 1)
        rendered = repr((citation, patrol))
        for secret in ("SECRET-SPAN-BODY", "SECRET-MARKDOWN", "SECRET-OTHER-PAGE"):
            self.assertNotIn(secret, rendered)

    def test_example_prints_anchors_without_a_model(self) -> None:
        completed = subprocess.run(
            [sys.executable, "examples/applications/grid_regulation.py"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["clause_id"], "4.1.2")
        self.assertEqual(payload["anchors"][0]["document"], "grounding.docx")
        self.assertNotIn("SECRET-SPAN-BODY", completed.stdout)
        self.assertNotIn("SECRET-SPAN-BODY", completed.stderr)
