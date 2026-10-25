from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from asterion.applications.grid_regulation import (
    RegulationCitation,
    RegulationCitationError,
    RegulationQuery,
    cite_regulation,
    lookup_chain,
    lookup_measures,
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

    async def test_measures_keep_the_narrowest_matching_clause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _station(root)
            child = await lookup_measures(
                root,
                "雨天复测",
                document="station.docx",
                document_tools="docx",
            )
            parent = await lookup_measures(
                root,
                "限值 雨天复测",
                document="station.docx",
                document_tools="docx",
            )
            both = await lookup_measures(
                root,
                "不应大于4欧姆",
                document="station.docx",
                document_tools="docx",
            )
            opened = await lookup_measures(
                root,
                "不应大于4欧姆",
                document=None,
                document_tools="docx,pdf",
            )
            with self.assertRaises(RegulationCitationError):
                await lookup_measures(
                    root,
                    "应如何处置",
                    document="station.docx",
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await lookup_measures(
                    root,
                    "封面",
                    document="station.docx",
                    document_tools="docx",
                )
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in child.clauses),
            (("measure", "4.1.2.1"), ("parent", "4.1.2"), ("reference", "2.10")),
        )
        self.assertNotIn("雨天复测", child.clauses[1]["measures"])
        self.assertEqual(child.clauses[0]["basis"]["position"]["paragraph"], 4)
        self.assertEqual(
            child.calls, ("document-read", "document-read", "document-read")
        )
        self.assertNotIn("text", child.clauses[0]["basis"])
        self.assertNotIn("雨天复测", repr(child.clauses[0]["basis"]))
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in parent.clauses),
            (("measure", "4.1.2"), ("reference", "2.10")),
        )
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in both.clauses),
            (("measure", "4.1.2"), ("measure", "2.10"), ("child", "4.1.2.1")),
        )
        self.assertEqual(both.calls, ("document-read",) * 3)
        self.assertTrue(
            all(item["document"] == "station.docx" for item in both.clauses)
        )
        self.assertIn("station.pdf", {item["document"] for item in opened.clauses})
        self.assertNotIn("不应大于4欧姆", repr(both.clauses[0]["basis"]))

    async def test_measures_follow_body_headings_named_by_the_outline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _outline_docx(root / "outline.docx")
            found = await lookup_measures(
                root,
                "不应大于4欧姆",
                document="outline.docx",
                document_tools="docx",
            )
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in found.clauses),
            (("measure", "4.1.2"), ("child", "4.1.2.1")),
        )
        measure = found.clauses[0]
        self.assertEqual(measure["basis"]["position"], {"paragraph": 5})
        self.assertEqual(
            measure["measures"],
            "4.1.2 接地限值不应大于4欧姆。附注留在本条款内",
        )
        self.assertEqual(found.clauses[1]["measures"], "4.1.2.1 雨天复测")
        self.assertNotIn("接地限值 9", measure["measures"])
        self.assertFalse(found.limited)
        self.assertEqual(found.calls, ("document-read", "document-read"))

    async def test_a_bare_clause_number_does_not_start_a_clause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _bare_number_docx(root / "table.docx")
            kept = await lookup_measures(
                root,
                "不应大于4欧姆",
                document="table.docx",
                document_tools="docx",
            )
            titled = await lookup_measures(
                root,
                "两端接地",
                document="table.docx",
                document_tools="docx",
            )
        self.assertEqual(
            tuple(item["clause_id"] for item in kept.clauses),
            ("4.1.2",),
        )
        self.assertEqual(
            kept.clauses[0]["measures"],
            "4.1.2 接地限值不应大于4欧姆。5.82.10.后续仍属本条。",
        )
        self.assertEqual(titled.clauses[0]["clause_id"], "4.2.1")
        self.assertEqual(titled.clauses[0]["basis"]["kind"], "docx-cell")
        self.assertEqual(titled.clauses[0]["measures"], "4.2.1 两端接地。")

    async def test_chain_keeps_a_table_row_and_follows_its_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "desk.docx",
                (
                    ("4.1.2 接地限值", None),
                    ("5.2 随后的复测。", None),
                ),
                ((("雨天", "不应大于4欧姆。见5.2。"),),),
            )
            found = await lookup_chain(
                root,
                "不应大于4欧姆",
                document="desk.docx",
                document_tools="docx",
            )
        self.assertEqual(
            tuple(step["text"] for step in found.steps),
            ("雨天｜不应大于4欧姆。见5.2。", "5.2 随后的复测。"),
        )
        self.assertIsNone(found.steps[0]["label"])
        self.assertEqual(found.steps[1]["label"], "5.2")
        self.assertEqual(
            tuple(anchor["kind"] for anchor in found.steps[0]["anchors"]),
            ("docx-cell", "docx-cell"),
        )
        self.assertEqual(found.steps[1]["anchors"][0]["kind"], "docx-paragraph")
        self.assertEqual(found.calls, ("document-read",) * 3)
        self.assertFalse(found.limited)
        self.assertNotIn("4.1.2 接地限值", found.steps[0]["text"])


def _bare_number_docx(path: Path) -> None:
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>4.1.2 接地限值</w:t></w:r></w:p>
<w:p><w:r><w:t>不应大于4欧姆。</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>5.8</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>2.10.</w:t></w:r></w:p>
<w:p><w:r><w:t>后续仍属本条。</w:t></w:r></w:p>
<w:p><w:r><w:t>4.1.3 其他条款</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>4.2.1 两端接地。</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>
"""
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)


def _outline_docx(path: Path) -> None:
    paragraphs = (
        ("TOC1", "1. 总则 1"),
        ("TOC2", "4.1.2. 接地限值 9"),
        ("TOC3", "4.1.2.1. 雨天复测 2"),
        ("TOC2", "4.2.1. 其他条款 3"),
        ("1", "总则"),
        ("2", "接地限值"),
        ("", "不应大于4欧姆。"),
        ("4", "附注留在本条款内"),
        ("3", "雨天复测"),
        ("2", "其他条款"),
    )
    body: list[str] = []
    for style, text in paragraphs:
        properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body.append(f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)


def _station(root: Path) -> None:
    write_docx(
        root / "station.docx",
        (
            ("封面 DL/T 9000-2024", None),
            ("4.1.2 接地电阻", None),
            ("（1）限值不应大于", None),
            ("4欧姆。", None),
            ("4.1.2.1 雨天复测，见2.10。", None),
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


def _paragraphs(citation: RegulationCitation) -> tuple[int, ...]:
    return tuple(anchor["position"]["paragraph"] for anchor in citation.anchors)
