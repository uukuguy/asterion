"""Read and write the DOCX spans needed for a citation anchor."""

from __future__ import annotations

import re
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# The outline number lives on the TOC entry. Heading styles 1–3 carry the title.
_TOC_LEVEL = re.compile(r"^TOC([123])$")
_HEADING_LEVEL = re.compile(r"^([123])$")
_OUTLINE_ID = re.compile(r"^([0-9]{1,2}(?:\.[0-9]{1,2}){1,4})(?!\d|\.[0-9])")
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


def docx_outline_depths(path: Path) -> dict[int, int]:
    """Return paragraph index to outline depth for styles 1, 2, and 3.

    The depth is not a public anchor field. Empty paragraphs are omitted.
    """

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
    depths: dict[int, int] = {}
    paragraph_index = 0
    for child in list(body):
        if child.tag != f"{_W}p":
            continue
        match = _HEADING_LEVEL.fullmatch(_paragraph_style(child))
        if match is not None and _text(child).strip():
            depths[paragraph_index] = int(match.group(1))
        paragraph_index += 1
    return depths


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
    blocks: list[tuple[str, int, ElementTree.Element]] = []
    paragraph_index = 0
    table_index = 0
    for child in list(body):
        if child.tag == f"{_W}p":
            blocks.append(("p", paragraph_index, child))
            paragraph_index += 1
        elif child.tag == f"{_W}tbl":
            blocks.append(("t", table_index, child))
            table_index += 1
    omit, labels = _outline_labels(
        [(index, element) for kind, index, element in blocks if kind == "p"]
    )
    spans: list[tuple[str, Mapping[str, int], str]] = []
    for kind, index, element in blocks:
        if kind == "p":
            if index in omit:
                continue
            text = _text(element)
            label = labels.get(index)
            if label is not None and _OUTLINE_ID.match(text.strip()) is None:
                text = f"{label} {text.strip()}"
            spans.append(("docx-paragraph", _paragraph_position(element, index), text))
            continue
        for row_index, row in enumerate(element.findall(f"{_W}tr")):
            for cell_index, cell in enumerate(row.findall(f"{_W}tc")):
                spans.append(
                    (
                        "docx-cell",
                        {"table": index, "row": row_index, "cell": cell_index},
                        _text(cell),
                    )
                )
    return tuple(spans)


def _outline_labels(
    paragraphs: Sequence[tuple[int, ElementTree.Element]],
) -> tuple[set[int], dict[int, str]]:
    """Move TOC clause numbers onto the matching headings, or change nothing.

    TOC entries are omitted only when every level-1–3 entry lines up with a
    heading of the same level. A deeper entry without a dotted number keeps
    the original paragraphs, so the number is not dropped.
    """

    toc: list[tuple[int, int, str]] = []
    headings: list[tuple[int, int]] = []
    for index, paragraph in paragraphs:
        style = _paragraph_style(paragraph)
        text = _text(paragraph).strip()
        if not text:
            continue
        toc_match = _TOC_LEVEL.fullmatch(style)
        if toc_match is not None:
            toc.append((index, int(toc_match.group(1)), text))
            continue
        heading_match = _HEADING_LEVEL.fullmatch(style)
        if heading_match is not None:
            headings.append((index, int(heading_match.group(1))))
    if not toc or [level for _index, level, _text in toc] != [
        level for _index, level in headings
    ]:
        return set(), {}
    labels: dict[int, str] = {}
    paired = zip(toc, headings, strict=True)
    for (_toc_index, level, text), (heading_index, _level) in paired:
        found = _OUTLINE_ID.match(text)
        if found is None:
            if level > 1:
                return set(), {}
            continue
        labels[heading_index] = found.group(1)
    return {index for index, _level, _text in toc}, labels


def _paragraph_style(paragraph: ElementTree.Element) -> str:
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    if style is None:
        return ""
    return style.attrib.get(f"{_W}val", "")


def _paragraph_position(
    paragraph: ElementTree.Element, index: int
) -> Mapping[str, int]:
    position: dict[str, int] = {"paragraph": index}
    numbering = paragraph.find(f"{_W}pPr/{_W}numPr")
    if numbering is None:
        return position
    level = numbering.find(f"{_W}ilvl")
    number_id = numbering.find(f"{_W}numId")
    # numId 0 and a half-present numPr mean the paragraph is not numbered.
    if level is None or number_id is None:
        return position
    try:
        level_number = int(level.attrib[f"{_W}val"])
        id_number = int(number_id.attrib[f"{_W}val"])
    except (KeyError, ValueError):
        return position
    if level_number < 0 or id_number < 1:
        return position
    position["numbering_level"] = level_number
    position["numbering_id"] = id_number
    return position


def _text(element: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{_W}t"))


class DocumentFormatError(ValueError):
    """Raised when a document container cannot be read."""
