from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.documents import (
    DocumentToolError,
    parse_document_tools,
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
