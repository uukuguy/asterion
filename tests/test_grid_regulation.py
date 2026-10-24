from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from asterion.applications.grid_regulation import (
    RegulationCitation,
    RegulationCitationError,
    RegulationQuery,
    cite_regulation,
    write_demo_corpus,
)
from asterion.documents import write_docx, write_pdf

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

    async def test_citation_assembles_a_dotted_clause_across_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "station.docx",
                (
                    ("封面 DL/T 9000-2024", None),
                    ("4.1.2 接地电阻", None),
                    ("（1）限值不应大于", None),
                    ("4欧姆。", None),
                    ("4.1.2.1 雨天复测", None),
                    ("4.1.3 其他条款", None),
                    ("2.10 编号不应大于4欧姆。", None),
                ),
            )
            write_pdf(
                root / "station.pdf",
                (
                    (
                        (72, 740, "封面 DL/T 9000-2024"),
                        (72, 700, "4.1.2 接地电阻"),
                        (72, 680, "限值不应大于4欧姆。"),
                        (72, 660, "4.1.3 其他条款"),
                    ),
                ),
            )
            split = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx",
            )
            child = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "雨天复测"),
                document_tools="docx",
            )
            numbered = await cite_regulation(
                root,
                RegulationQuery("2.10", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx",
            )
            pdf = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="pdf",
            )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2.1", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("2.1", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2", "  ", "不应大于4欧姆"),
                    document_tools="docx",
                )
        self.assertEqual(_paragraphs(split), (0, 1, 2, 3))
        self.assertEqual(_paragraphs(child), (0, 1, 4))
        self.assertEqual(_paragraphs(numbered), (0, 6))
        self.assertEqual(
            tuple(
                (anchor["position"]["item"], anchor["position"]["y"])
                for anchor in pdf.anchors
            ),
            ((0, 740), (1, 700), (2, 680)),
        )
        self.assertTrue(
            all(
                anchor["kind"] == "pdf-text" and anchor["position"]["page"] == 1
                for anchor in pdf.anchors
            )
        )
        for citation in (split, child, numbered, pdf):
            self.assertEqual(
                citation.calls,
                tuple("document-read" for _anchor in citation.anchors),
            )
            rendered = repr(citation)
            self.assertNotIn("不应大于4欧姆", rendered)
            self.assertNotIn("雨天复测", rendered)

    async def test_repeated_clause_id_does_not_keep_the_earlier_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "repeat.docx",
                (
                    ("封面 DL/T 9000-2024", None),
                    ("4.1.2 接地电阻", None),
                    ("本节只说明范围。", None),
                    ("4.1.3 其他条款", None),
                    ("4.1.2 接地电阻", None),
                    ("限值不应大于4欧姆。", None),
                ),
            )
            citation = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx",
            )
        self.assertEqual(
            tuple(
                (anchor["document"], anchor["position"]["paragraph"])
                for anchor in citation.anchors
            ),
            (("repeat.docx", 0), ("repeat.docx", 4), ("repeat.docx", 5)),
        )

    async def test_clause_without_a_version_span_is_not_cited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "bare.docx",
                (("4.1.2 接地电阻不应大于4欧姆。", None),),
            )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )


def _paragraphs(citation: RegulationCitation) -> tuple[int, ...]:
    return tuple(anchor["position"]["paragraph"] for anchor in citation.anchors)
