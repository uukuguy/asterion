"""Read and write the DOCX spans needed for a citation anchor."""

from __future__ import annotations

import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


def write_docx(
    path: Path,
    paragraphs: Sequence[tuple[str, tuple[int, int] | None]],
    tables: Sequence[Sequence[Sequence[str]]] = (),
) -> None:
    """Write a document whose paragraphs and cells round-trip as anchors."""

    body = ["<w:body>"]
    for text, numbering in paragraphs:
        body.append("<w:p>")
        if numbering is not None:
            level, number_id = numbering
            body.append(
                "<w:pPr><w:numPr>"
                f'<w:ilvl w:val="{level}"/>'
                f'<w:numId w:val="{number_id}"/>'
                "</w:numPr></w:pPr>"
            )
        body.append(f"<w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
    for table in tables:
        body.append("<w:tbl>")
        for row in table:
            body.append("<w:tr>")
            for cell in row:
                body.append(
                    f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>"
                )
            body.append("</w:tr>")
        body.append("</w:tbl>")
    body.append("</w:body>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + "".join(body)
        + "</w:document>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _CONTENT_TYPES)
        package.writestr("_rels/.rels", _RELS)
        package.writestr("word/document.xml", document)


def docx_spans(
    path: Path,
) -> tuple[tuple[str, Mapping[str, int], str], ...]:
    """Return paragraph and cell spans in document order."""

    try:
        with zipfile.ZipFile(path) as package:
            payload = package.read("word/document.xml")
    except (KeyError, OSError, zipfile.BadZipFile):
        raise DocumentFormatError("document tool is unavailable") from None
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        raise DocumentFormatError("document tool is unavailable") from None
    body = root.find(f"{_W}body")
    if body is None:
        raise DocumentFormatError("document tool is unavailable")
    spans: list[tuple[str, Mapping[str, int], str]] = []
    paragraph_index = 0
    table_index = 0
    for child in list(body):
        if child.tag == f"{_W}p":
            spans.append(
                (
                    "docx-paragraph",
                    _paragraph_position(child, paragraph_index),
                    _text(child),
                )
            )
            paragraph_index += 1
        elif child.tag == f"{_W}tbl":
            for row_index, row in enumerate(child.findall(f"{_W}tr")):
                for cell_index, cell in enumerate(row.findall(f"{_W}tc")):
                    spans.append(
                        (
                            "docx-cell",
                            {
                                "table": table_index,
                                "row": row_index,
                                "cell": cell_index,
                            },
                            _text(cell),
                        )
                    )
            table_index += 1
    return tuple(spans)


def _paragraph_position(
    paragraph: ElementTree.Element, index: int
) -> Mapping[str, int]:
    position: dict[str, int] = {"paragraph": index}
    numbering = paragraph.find(f"{_W}pPr/{_W}numPr")
    if numbering is None:
        return position
    level = numbering.find(f"{_W}ilvl")
    number_id = numbering.find(f"{_W}numId")
    if level is None or number_id is None:
        raise DocumentFormatError("document tool is unavailable")
    try:
        position["numbering_level"] = int(level.attrib[f"{_W}val"])
        position["numbering_id"] = int(number_id.attrib[f"{_W}val"])
    except (KeyError, ValueError):
        raise DocumentFormatError("document tool is unavailable") from None
    return position


def _text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_W}t"))


class DocumentFormatError(ValueError):
    """Raised when a document container cannot be read."""
