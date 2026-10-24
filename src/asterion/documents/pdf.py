"""Read and write PDF text anchors with a page and a text position."""

from __future__ import annotations

import re
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path

_OBJECT = re.compile(rb"(\d+) 0 obj")
_LENGTH = re.compile(rb"/Length\s+(\d+)")
_CONTENTS = re.compile(rb"/Contents\s+(\d+)\s+0\s+R")
_OPERATOR = re.compile(r"^(?:BT|ET|Tf|Tj|TJ|Tm|Td|TD|T\*)$")


class DocumentFormatError(ValueError):
    """Raised when a PDF container cannot be read."""


def write_pdf(path: Path, pages: Sequence[Sequence[tuple[int, int, str]]]) -> None:
    """Write one text item per anchor. Coordinates are PDF points."""

    if not pages:
        raise DocumentFormatError("document tool is unavailable")
    objects: list[bytes] = []
    page_ids: list[int] = []
    next_id = 3
    content_ids: list[tuple[int, bytes]] = []
    for page in pages:
        content = _content(page)
        compressed = zlib.compress(content)
        content_id = next_id
        next_id += 1
        page_id = next_id
        next_id += 1
        content_ids.append((content_id, compressed))
        page_ids.append(page_id)
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(
        f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>\nendobj\n".encode()
    )
    for (content_id, compressed), page_id in zip(content_ids, page_ids, strict=True):
        objects.append(
            (
                f"{content_id} 0 obj\n<< /Length {len(compressed)} /Filter /FlateDecode >>\nstream\n"
            ).encode()
            + compressed
            + b"\nendstream\nendobj\n"
        )
        objects.append(
            (
                f"{page_id} 0 obj\n<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 612 792] /Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {next_id} 0 R >> >> >>\nendobj\n"
            ).encode()
        )
    objects.append(
        f"{next_id} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n".encode()
    )
    payload = b"%PDF-1.4\n" + b"".join(objects) + b"%%EOF\n"
    path.write_bytes(payload)


def pdf_spans(path: Path) -> tuple[tuple[str, Mapping[str, int], str], ...]:
    """Return text items in page order. Item numbers restart on each page."""

    try:
        data = path.read_bytes()
        objects = _objects(data)
        pages = _pages(objects)
    except (OSError, ValueError, zlib.error):
        raise DocumentFormatError("document tool is unavailable") from None
    spans: list[tuple[str, Mapping[str, int], str]] = []
    for page_number, content in enumerate(pages, start=1):
        for item, (x_point, y_point, text) in enumerate(_text_items(content)):
            if not text:
                continue
            spans.append(
                (
                    "pdf-text",
                    {"page": page_number, "item": item, "x": x_point, "y": y_point},
                    text,
                )
            )
    return tuple(spans)


def _content(items: Sequence[tuple[int, int, str]]) -> bytes:
    lines = ["BT", "/F1 12 Tf"]
    for x_point, y_point, text in items:
        lines.append(f"1 0 0 1 {x_point} {y_point} Tm")
        lines.append(f"<{_hex(text)}> Tj")
    lines.append("ET")
    return ("\n".join(lines) + "\n").encode()


def _hex(text: str) -> str:
    return "FEFF" + text.encode("utf-16-be").hex().upper()


def _objects(data: bytes) -> dict[int, tuple[bytes, bytes | None]]:
    found: dict[int, tuple[bytes, bytes | None]] = {}
    for match in _OBJECT.finditer(data):
        object_id = int(match.group(1))
        start = match.end()
        stream_at = data.find(b"stream", start)
        endobj = data.find(b"endobj", start)
        if endobj < 0:
            raise DocumentFormatError("document tool is unavailable")
        if stream_at < 0 or stream_at > endobj:
            found[object_id] = (data[start:endobj], None)
            continue
        header = data[start:stream_at]
        length_match = _LENGTH.search(header)
        if length_match is None:
            raise DocumentFormatError("document tool is unavailable")
        cursor = stream_at + len(b"stream")
        if data[cursor : cursor + 2] == b"\r\n":
            cursor += 2
        elif data[cursor : cursor + 1] == b"\n":
            cursor += 1
        length = int(length_match.group(1))
        payload = data[cursor : cursor + length]
        if b"/FlateDecode" in header:
            payload = zlib.decompress(payload)
        found[object_id] = (header, payload)
    return found


def _pages(objects: dict[int, tuple[bytes, bytes | None]]) -> tuple[str, ...]:
    pages_header = next(
        (header for header, _payload in objects.values() if b"/Type /Pages" in header),
        None,
    )
    if pages_header is None or b"/Kids" not in pages_header:
        raise DocumentFormatError("document tool is unavailable")
    kids_text = pages_header.split(b"/Kids", 1)[1].split(b"]", 1)[0]
    kids = [int(item) for item in re.findall(rb"(\d+)\s+0\s+R", kids_text)]
    if not kids:
        raise DocumentFormatError("document tool is unavailable")
    contents: list[str] = []
    for kid in kids:
        header, _payload = objects[kid]
        contents_match = _CONTENTS.search(header)
        if contents_match is None:
            raise DocumentFormatError("document tool is unavailable")
        payload = objects[int(contents_match.group(1))][1]
        if payload is None:
            raise DocumentFormatError("document tool is unavailable")
        contents.append(payload.decode("latin-1"))
    return tuple(contents)


def _text_items(content: str) -> tuple[tuple[int, int, str], ...]:
    tokens = _tokenize(content)
    operands: list[object] = []
    x_point = 0
    y_point = 0
    items: list[tuple[int, int, str]] = []
    for token in tokens:
        if token == "[":
            operands.append([])
            continue
        if token == "]":
            array: list[object] = []
            while operands and operands[-1] != []:
                array.append(operands.pop())
            if not operands or operands[-1] != []:
                raise DocumentFormatError("document tool is unavailable")
            operands.pop()
            operands.append(list(reversed(array)))
            continue
        if not _OPERATOR.fullmatch(token):
            operands.append(token)
            continue
        if token == "Tm" and len(operands) >= 6:
            x_point = _whole(operands[-2])
            y_point = _whole(operands[-1])
        elif token in {"Td", "TD"} and len(operands) >= 2:
            x_point += _whole(operands[-2])
            y_point += _whole(operands[-1])
        elif token == "Tj" and operands:
            text = _decode(operands[-1])
            items.append((x_point, y_point, text))
        elif token == "TJ" and operands and isinstance(operands[-1], list):
            text = "".join(
                _decode(part)
                for part in operands[-1]
                if isinstance(part, str) and part.startswith(("<", "("))
            )
            items.append((x_point, y_point, text))
        operands = []
    return tuple(items)


def _tokenize(content: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(content):
        character = content[index]
        if character.isspace():
            index += 1
            continue
        if character == "%":
            newline = content.find("\n", index)
            index = len(content) if newline < 0 else newline + 1
            continue
        if character in "[]":
            tokens.append(character)
            index += 1
            continue
        if character == "(":
            index, token = _literal(content, index)
            tokens.append(token)
            continue
        if character == "<":
            close = content.find(">", index)
            if close < 0:
                raise DocumentFormatError("document tool is unavailable")
            tokens.append(content[index : close + 1])
            index = close + 1
            continue
        if character == "/":
            end = index + 1
            while (
                end < len(content)
                and not content[end].isspace()
                and content[end] not in "[]()<>"
            ):
                end += 1
            tokens.append(content[index:end])
            index = end
            continue
        end = index + 1
        while (
            end < len(content)
            and not content[end].isspace()
            and content[end] not in "[]()<>/"
        ):
            end += 1
        tokens.append(content[index:end])
        index = end
    return tokens


def _literal(content: str, index: int) -> tuple[int, str]:
    end = index + 1
    while end < len(content):
        if content[end] == "\\":
            end += 2
            continue
        if content[end] == ")":
            return end + 1, content[index : end + 1]
        end += 1
    raise DocumentFormatError("document tool is unavailable")


def _decode(token: object) -> str:
    if not isinstance(token, str):
        return ""
    if token.startswith("<") and token.endswith(">"):
        raw = bytes.fromhex(token[1:-1])
        if raw.startswith(b"\xfe\xff"):
            return raw[2:].decode("utf-16-be")
        return raw.decode("latin-1")
    if token.startswith("(") and token.endswith(")"):
        return token[1:-1]
    return ""


def _whole(token: object) -> int:
    if not isinstance(token, str):
        raise DocumentFormatError("document tool is unavailable")
    return int(round(float(token)))
