from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import json

from asterion.documents import (
    DocumentToolError,
    anchors_for_passage_read,
    document_spans,
    parse_document_tools,
    project_document,
    read_span,
    search_documents,
    write_docx,
    write_pdf,
)
from asterion.documents.tools import verify_public_anchor


class DocumentToolTests(unittest.TestCase):
    def test_default_configuration_enables_no_document_kind(self) -> None:
        self.assertEqual(parse_document_tools(None), ())
        self.assertEqual(parse_document_tools(""), ())
        with self.assertRaises(DocumentToolError):
            parse_document_tools("pdf,docx")
        with self.assertRaises(DocumentToolError):
            search_documents(Path("."), "clause", tools=None)

    def test_docx_and_pdf_anchors_round_trip_without_span_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "corpus"
            root.mkdir()
            write_docx(
                root / "rules.docx",
                (
                    ("4.1.2 限值 DL/T 1 不应大于4欧姆。SECRET-DOCX", (1, 1)),
                    ("4.1.3 其他 不规定限值。SECRET-NEIGHBOR", None),
                ),
                ((("4.2.1 屏蔽 DL/T 1 两端接地。SECRET-CELL",),),),
            )
            write_pdf(
                root / "patrol.pdf",
                (
                    (
                        (72, 700, "5.2 巡视 DL/T 1 每季度一次。SECRET-PDF"),
                        (72, 660, "5.3 记录 只要求记录。"),
                    ),
                ),
            )
            (root / "notes.md").write_text("4.1.2 SECRET-MARKDOWN\n", encoding="utf-8")
            external = Path(directory) / "secret.docx"
            external.write_bytes(b"SECRET-OUTSIDE")
            (root / "linked.docx").symlink_to(external)

            docx_hits = search_documents(root, "4.1.2", tools="docx")
            cell_hits = search_documents(root, "4.2.1", tools="docx,pdf")
            pdf_hits = search_documents(root, "5.2", tools="docx,pdf")

            self.assertEqual(len(docx_hits), 1)
            self.assertEqual(docx_hits[0]["document"], "rules.docx")
            self.assertEqual(docx_hits[0]["kind"], "docx-paragraph")
            self.assertEqual(
                docx_hits[0]["position"],
                {"paragraph": 0, "numbering_id": 1, "numbering_level": 1},
            )
            self.assertEqual(cell_hits[0]["kind"], "docx-cell")
            self.assertEqual(
                cell_hits[0]["position"], {"cell": 0, "row": 0, "table": 0}
            )
            self.assertEqual(pdf_hits[0]["document"], "patrol.pdf")
            self.assertEqual(
                pdf_hits[0]["position"], {"item": 0, "page": 1, "x": 72, "y": 700}
            )
            self.assertIn("SECRET-DOCX", read_span(root, docx_hits[0]))
            rendered = repr((docx_hits, cell_hits, pdf_hits))
            for secret in (
                "SECRET-DOCX",
                "SECRET-NEIGHBOR",
                "SECRET-CELL",
                "SECRET-PDF",
                "SECRET-MARKDOWN",
                "SECRET-OUTSIDE",
            ):
                self.assertNotIn(secret, rendered)
            forged = dict(docx_hits[0])
            forged["span_sha256"] = "0" * 64
            with self.assertRaises(DocumentToolError) as raised:
                verify_public_anchor(root, forged)
            self.assertNotIn("SECRET", str(raised.exception))
            with self.assertRaises(DocumentToolError):
                search_documents(
                    root, "4.1.2", tools="docx,pdf", path="../outside/secret.docx"
                )

    def test_docx_keeps_text_when_numbering_is_inactive(self) -> None:
        document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr></w:pPr>
<w:r><w:t>CLAUSE-ON</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="0"/></w:numPr></w:pPr>
<w:r><w:t>CLAUSE-OFF</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/></w:numPr></w:pPr>
<w:r><w:t>CLAUSE-HALF</w:t></w:r></w:p>
</w:body></w:document>
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "rules.docx", "w") as package:
                package.writestr("word/document.xml", document)
            on_hit = search_documents(root, "CLAUSE-ON", tools="docx")[0]
            off_hit = search_documents(root, "CLAUSE-OFF", tools="docx")[0]
            half_hit = search_documents(root, "CLAUSE-HALF", tools="docx")[0]
            self.assertEqual(
                on_hit["position"],
                {"numbering_id": 1, "numbering_level": 1, "paragraph": 0},
            )
            self.assertEqual(off_hit["position"], {"paragraph": 1})
            self.assertEqual(half_hit["position"], {"paragraph": 2})
            self.assertEqual(read_span(root, off_hit), "CLAUSE-OFF")

    def test_docx_outline_moves_clause_ids_onto_body_headings(self) -> None:
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
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _styled_docx(root / "outline.docx", paragraphs)
            spans = document_spans(root, tools="docx")
        texts = tuple(text for _anchor, text in spans)
        indexes = tuple(anchor["position"]["paragraph"] for anchor, _text in spans)
        self.assertEqual(
            texts,
            (
                "总则",
                "4.1.2 接地限值",
                "不应大于4欧姆。",
                "附注留在本条款内",
                "4.1.2.1 雨天复测",
                "4.2.1 其他条款",
            ),
        )
        self.assertEqual(indexes, (4, 5, 6, 7, 8, 9))
        self.assertEqual(set(spans[1][0]["position"]), {"paragraph"})
        self.assertNotIn("接地限值 9", "".join(texts))

    def test_docx_outline_stays_put_when_levels_do_not_line_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _styled_docx(
                root / "mismatch.docx",
                (
                    ("TOC2", "4.1.2. 接地限值 9"),
                    ("2", "接地限值"),
                    ("2", "其他条款"),
                ),
            )
            _styled_docx(
                root / "unnumbered.docx",
                (("TOC2", "接地限值"), ("2", "接地限值")),
            )
            mismatch = document_spans(root, tools="docx", path="mismatch.docx")
            unnumbered = document_spans(root, tools="docx", path="unnumbered.docx")
        self.assertEqual(
            tuple(text for _anchor, text in mismatch),
            ("4.1.2. 接地限值 9", "接地限值", "其他条款"),
        )
        self.assertEqual(
            tuple(anchor["position"]["paragraph"] for anchor, _text in mismatch),
            (0, 1, 2),
        )
        self.assertEqual(
            tuple(text for _anchor, text in unnumbered),
            ("接地限值", "接地限值"),
        )

    def test_pdf_tounicode_joins_a_baseline_and_keeps_a_distant_glyph(self) -> None:
        cmap = b"""begincmap
1 begincodespacerange
<0000> <FFFF>
endcodespacerange
4 beginbfchar
<0001> <6761>
<0002> <6B3E>
<0003> <7532>
<0004> <4E59>
endbfchar
1 beginbfrange
<0010> <0011> <0041>
endbfrange
1 beginbfrange
<0020> <0021> [<0043> <0044>]
endbfrange
endcmap
"""
        content = (
            b"BT /F1 200 Tf 0.05 0 0 -0.05 72 700 Tm "
            b"<0001> Tj 100 0 TD <00EE> Tj 100 0 TD <0002> Tj 100 0 TD <0003> Tj ET "
            b"BT /F1 200 Tf 0.05 0 0 -0.05 400 700 Tm <0004> Tj ET "
            b"BT /F1 200 Tf 0.05 0 0 -0.05 72 640 Tm <0010> Tj 100 0 TD <0011> Tj ET "
            b"BT /F1 200 Tf 0.05 0 0 -0.05 72 600 Tm <00200021> Tj ET"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clause.pdf").write_bytes(_identity_pdf(content, cmap))
            phrase = search_documents(root, "\u6761\u6b3e\u7532", tools="pdf")
            other = search_documents(root, "\u4e59", tools="pdf")
            letters = search_documents(root, "AB", tools="pdf")
            array_letters = search_documents(root, "CD", tools="pdf")
            self.assertEqual(len(phrase), 1)
            self.assertEqual(
                phrase[0]["position"], {"item": 0, "page": 1, "x": 72, "y": 700}
            )
            self.assertEqual(read_span(root, phrase[0]), "\u6761\u6b3e\u7532")
            self.assertNotIn("\u4e59", read_span(root, phrase[0]))
            self.assertEqual(other[0]["position"]["x"], 400)
            self.assertEqual(other[0]["position"]["item"], 1)
            self.assertEqual(
                letters[0]["position"], {"item": 2, "page": 1, "x": 72, "y": 640}
            )
            self.assertEqual(array_letters[0]["position"]["y"], 600)
            self.assertEqual(search_documents(root, "\u7532\u4e59", tools="pdf"), ())

    def test_document_spans_keeps_text_for_the_caller(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(root / "rules.docx", (("4.1.2 限值。SPAN-PRIVATE", None),))
            spans = document_spans(root, tools="docx")
            anchor, text = spans[0]
            self.assertEqual(text, "4.1.2 限值。SPAN-PRIVATE")
            self.assertNotIn("SPAN-PRIVATE", repr(anchor))
            self.assertEqual(search_documents(root, "4.1.2", tools="docx"), (anchor,))
            with self.assertRaises(DocumentToolError):
                document_spans(root, tools=None)


class DocumentProjectionTests(unittest.TestCase):
    def test_projects_a_table_row_without_dropping_other_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "corpus"
            source.mkdir()
            write_docx(
                source / "desk.docx",
                (("4.1.2 接地限值", None), ("5.2 随后的复测。", None)),
                ((("雨天", "不应大于4欧姆。见5.2。"),),),
            )
            destination = root / "view"
            destination.mkdir()
            index = project_document(source, "desk.docx", destination)
            written = json.loads(
                (destination / "passage-index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(written, index)
            self.assertEqual(index["origin"], "desk.docx")
            self.assertEqual(
                [item["id"] for item in index["passages"]],
                ["P000001", "P000002", "P000003"],
            )
            self.assertEqual(
                [item["unit"] for item in index["passages"]],
                ["paragraph", "paragraph", "table-row"],
            )
            self.assertEqual(len(index["passages"][2]["anchors"]), 2)
            self.assertNotIn("雨天", json.dumps(index))
            self.assertNotIn("接地限值", json.dumps(index))
            lines = (destination / "passages.txt").read_text(encoding="utf-8")
            self.assertIn("P000001\t4.1.2 接地限值\n", lines)
            self.assertIn("P000003\t雨天\t不应大于4欧姆。见5.2。\n", lines)
            row = lines.splitlines()[2]
            anchors = anchors_for_passage_read(
                destination, path="passages.txt", output=row + "\n", is_error=False
            )
            self.assertEqual(len(anchors), 2)
            self.assertEqual(anchors[0]["kind"], "docx-cell")
            self.assertEqual(anchors[0]["document"], "source/desk.docx")

    def test_marks_outline_depth_without_storing_it_on_the_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "corpus"
            source.mkdir()
            _styled_docx(source / "outline.docx", (("2", "接地限值"),))
            destination = root / "view"
            destination.mkdir()
            index = project_document(source, "outline.docx", destination)
            self.assertEqual(index["passages"][0]["depth"], 2)
            self.assertNotIn("depth", index["passages"][0]["anchors"][0])
            line = (destination / "passages.txt").read_text(encoding="utf-8")
            self.assertTrue(line.startswith("P000001\tH2\t接地限值\n"))

    def test_truncated_read_keeps_complete_lines_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "corpus"
            source.mkdir()
            write_docx(
                source / "desk.docx",
                (("4.1.2 接地限值", None), ("5.2 随后的复测。", None)),
            )
            destination = root / "view"
            destination.mkdir()
            project_document(source, "desk.docx", destination)
            shown = (
                "P000001\t4.1.2 接地限值\n"
                "P000002\t5.2 随后的复测。\n"
                "P000003\t被截断"
                "\n[tool result truncated]"
            )
            anchors = anchors_for_passage_read(
                destination, path="passages.txt", output=shown, is_error=False
            )
            self.assertEqual(len(anchors), 2)
            self.assertIsNone(
                anchors_for_passage_read(
                    source, path="passages.txt", output=shown, is_error=False
                )
            )
            self.assertEqual(
                anchors_for_passage_read(
                    destination, path="passages.txt", output="", is_error=True
                ),
                (),
            )

    def test_rejects_a_line_over_the_cap_and_a_nested_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "corpus"
            nested = source / "fold"
            nested.mkdir(parents=True)
            write_docx(nested / "desk.docx", (("短", None),))
            destination = root / "view"
            destination.mkdir()
            index = project_document(source, "fold/desk.docx", destination)
            self.assertEqual(index["origin"], "fold/desk.docx")
            self.assertTrue((destination / "source" / "fold" / "desk.docx").is_file())
            write_docx(source / "long.docx", (("甲" * 9000, None),))
            other = root / "other"
            other.mkdir()
            with self.assertRaises(DocumentToolError):
                project_document(source, "long.docx", other)


def _styled_docx(path: Path, paragraphs: tuple[tuple[str, str], ...]) -> None:
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


def _identity_pdf(content: bytes, cmap: bytes) -> bytes:
    def obj(object_id: int, body: bytes) -> bytes:
        return f"{object_id} 0 obj\n".encode() + body + b"\nendobj\n"

    def stream(object_id: int, payload: bytes) -> bytes:
        header = f"<< /Length {len(payload)} >>\nstream\n".encode()
        return obj(object_id, header + payload + b"\nendstream")

    parts = [
        b"%PDF-1.4\n",
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        obj(
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        stream(4, content),
        obj(
            5,
            b"<< /Type /Font /Subtype /Type0 /BaseFont /CID "
            b"/Encoding /Identity-H /ToUnicode 6 0 R >>",
        ),
        stream(6, cmap),
        b"%%EOF\n",
    ]
    return b"".join(parts)
