"""Read and write PDF text anchors with a page and a text position.

Identity-H fonts decode through a ToUnicode bfchar or bfrange map. Glyphs
that share a baseline form one span. A gap wider than 36 points starts
another span, so two columns on the same baseline stay apart.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path

_OBJECT = re.compile(rb"(\d+) 0 obj")
_LENGTH = re.compile(rb"/Length\s+(\d+)")
_CONTENTS = re.compile(rb"/Contents\s+(\d+)\s+0\s+R")
_OPERATOR = re.compile(r"^(?:BT|ET|Tf|Tj|TJ|Tm|Td|TD|T\*)$")
_TOUNICODE = re.compile(rb"/ToUnicode\s+(\d+)\s+0\s+R")
_CMAP_TOKEN = re.compile(r"<([0-9A-Fa-f]+)>|\[|\]")
# User-space points. Body text in the regulation PDFs stays under 24.
_BASELINE_GAP = 36
_MAX_CMAP_RANGE = 4096


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
    for page_number, (content, fonts) in enumerate(pages, start=1):
        for item, (x_point, y_point, text) in enumerate(_text_items(content, fonts)):
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


def _pages(
    objects: dict[int, tuple[bytes, bytes | None]],
) -> tuple[tuple[str, Mapping[str, Mapping[bytes, str] | None]], ...]:
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
    cache: dict[int, dict[bytes, str]] = {}
    contents: list[tuple[str, Mapping[str, Mapping[bytes, str] | None]]] = []
    for kid in kids:
        header, _payload = objects[kid]
        contents_match = _CONTENTS.search(header)
        if contents_match is None:
            raise DocumentFormatError("document tool is unavailable")
        payload = objects[int(contents_match.group(1))][1]
        if payload is None:
            raise DocumentFormatError("document tool is unavailable")
        contents.append(
            (payload.decode("latin-1"), _font_encodings(header, objects, cache))
        )
    return tuple(contents)


def _font_encodings(
    header: bytes,
    objects: dict[int, tuple[bytes, bytes | None]],
    cache: dict[int, dict[bytes, str]],
) -> dict[str, Mapping[bytes, str] | None]:
    chunk = header
    if b"/Font" not in chunk:
        resource = re.search(rb"/Resources\s+(\d+)\s+0\s+R", header)
        if resource is None:
            return {}
        chunk = objects[int(resource.group(1))][0]
    font_at = chunk.find(b"/Font")
    if font_at < 0 or b"<<" not in chunk[font_at:]:
        return {}
    body = chunk[font_at:].split(b"<<", 1)[1].split(b">>", 1)[0]
    encodings: dict[str, Mapping[bytes, str] | None] = {}
    for name, object_id in re.findall(rb"/([A-Za-z0-9]+)\s+(\d+)\s+0\s+R", body):
        font_header = objects[int(object_id)][0]
        link = _TOUNICODE.search(font_header)
        if link is None:
            encodings[name.decode()] = None
            continue
        cmap_id = int(link.group(1))
        if cmap_id not in cache:
            cmap_payload = objects[cmap_id][1]
            cache[cmap_id] = {} if cmap_payload is None else _tounicode(cmap_payload)
        encodings[name.decode()] = cache[cmap_id]
    return encodings


def _tounicode(payload: bytes) -> dict[bytes, str]:
    text = payload.decode("latin-1")
    mapping: dict[bytes, str] = {}
    for body in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        pairs = re.findall(r"<([0-9A-Fa-f]+)>", body)
        if len(pairs) % 2:
            continue
        for index in range(0, len(pairs), 2):
            _put_cmap(mapping, pairs[index], pairs[index + 1])
    for body in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        _bfrange(mapping, body)
    widths = {len(key) for key in mapping}
    if len(widths) != 1:
        return {}
    return mapping


def _cmap_tokens(body: str) -> list[str]:
    return [
        match.group(1) if match.group(1) is not None else match.group(0)
        for match in _CMAP_TOKEN.finditer(body)
    ]


def _bfrange(mapping: dict[bytes, str], body: str) -> None:
    tokens = _cmap_tokens(body)
    index = 0
    while index + 2 < len(tokens):
        start, end, third = tokens[index], tokens[index + 1], tokens[index + 2]
        if start in {"[", "]"} or end in {"[", "]"}:
            index += 1
            continue
        if third == "[":
            dests: list[str] = []
            index += 3
            while index < len(tokens) and tokens[index] != "]":
                if tokens[index] != "[":
                    dests.append(tokens[index])
                index += 1
            index += 1
            _fill_array(mapping, start, end, dests)
            continue
        _fill_scalar(mapping, start, end, third)
        index += 3


def _fill_array(
    mapping: dict[bytes, str], start: str, end: str, dests: Sequence[str]
) -> None:
    if len(start) % 2 or not start:
        return
    start_code = int(start, 16)
    end_code = int(end, 16)
    width = len(start) // 2
    count = end_code - start_code + 1
    if count <= 0 or count > _MAX_CMAP_RANGE or count != len(dests):
        return
    for offset, dest in enumerate(dests):
        _put_cmap(mapping, (start_code + offset).to_bytes(width, "big").hex(), dest)


def _fill_scalar(mapping: dict[bytes, str], start: str, end: str, dest: str) -> None:
    if len(start) % 2 or not start or len(dest) % 2:
        return
    start_code = int(start, 16)
    end_code = int(end, 16)
    width = len(start) // 2
    count = end_code - start_code + 1
    if count <= 0 or count > _MAX_CMAP_RANGE:
        return
    try:
        base = int(dest, 16)
        dest_width = len(dest) // 2
    except ValueError:
        return
    for offset in range(count):
        code = (start_code + offset).to_bytes(width, "big")
        try:
            encoded = (base + offset).to_bytes(dest_width, "big")
        except OverflowError:
            return
        _put_cmap(mapping, code.hex(), encoded.hex())


def _put_cmap(mapping: dict[bytes, str], src_hex: str, dst_hex: str) -> None:
    try:
        source = bytes.fromhex(src_hex)
        text = bytes.fromhex(dst_hex).decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return
    if source and text:
        mapping[source] = text


def _text_items(
    content: str, fonts: Mapping[str, Mapping[bytes, str] | None]
) -> tuple[tuple[int, int, str], ...]:
    tokens = _tokenize(content)
    operands: list[object] = []
    scale_a, scale_b, scale_c, scale_d = 1.0, 0.0, 0.0, 1.0
    x_point = 0.0
    y_point = 0.0
    leading = 0.0
    encoding: Mapping[bytes, str] | None = None
    glyphs: list[tuple[int, int, str, int]] = []
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
        if token == "BT":
            scale_a, scale_b, scale_c, scale_d = 1.0, 0.0, 0.0, 1.0
            x_point = y_point = leading = 0.0
        elif token == "Tm" and len(operands) >= 6:
            scale_a = _number(operands[-6])
            scale_b = _number(operands[-5])
            scale_c = _number(operands[-4])
            scale_d = _number(operands[-3])
            x_point = _number(operands[-2])
            y_point = _number(operands[-1])
        elif token == "Tf" and len(operands) >= 2 and isinstance(operands[-2], str):
            name = operands[-2]
            if name.startswith("/"):
                encoding = fonts.get(name[1:])
        elif token in {"Td", "TD"} and len(operands) >= 2:
            move_x = _number(operands[-2])
            move_y = _number(operands[-1])
            x_point = scale_a * move_x + scale_c * move_y + x_point
            y_point = scale_b * move_x + scale_d * move_y + y_point
            if token == "TD":
                leading = move_y
        elif token == "T*":
            x_point = scale_c * -leading + x_point
            y_point = scale_d * -leading + y_point
        elif token == "Tj" and operands:
            _append_glyph(glyphs, x_point, y_point, _shown(operands[-1], encoding))
        elif token == "TJ" and operands and isinstance(operands[-1], list):
            shown = "".join(
                _shown(part, encoding)
                for part in operands[-1]
                if isinstance(part, str) and part.startswith(("<", "("))
            )
            _append_glyph(glyphs, x_point, y_point, shown)
        operands = []
    return _baselines(glyphs)


def _append_glyph(
    glyphs: list[tuple[int, int, str, int]], x_point: float, y_point: float, text: str
) -> None:
    if text:
        glyphs.append((int(round(x_point)), int(round(y_point)), text, len(glyphs)))


def _baselines(
    glyphs: Sequence[tuple[int, int, str, int]],
) -> tuple[tuple[int, int, str], ...]:
    lines: dict[int, list[tuple[int, int, str, int]]] = {}
    for glyph in glyphs:
        lines.setdefault(glyph[1], []).append(glyph)
    spans: list[tuple[int, int, str]] = []
    for y_point in sorted(lines, reverse=True):
        ordered = sorted(lines[y_point], key=lambda item: (item[0], item[3]))
        run_x: int | None = None
        run: list[str] = []
        last_x: int | None = None
        for x_point, _y_point, text, _order in ordered:
            if last_x is not None and x_point - last_x > _BASELINE_GAP:
                spans.append(
                    (run_x if run_x is not None else x_point, y_point, "".join(run))
                )
                run = []
                run_x = None
            if run_x is None:
                run_x = x_point
            run.append(text)
            last_x = x_point
        if run and run_x is not None:
            spans.append((run_x, y_point, "".join(run)))
    return tuple(spans)


def _shown(token: object, encoding: Mapping[bytes, str] | None) -> str:
    if encoding is None:
        return _decode(token)
    if not encoding or not isinstance(token, str) or not token.startswith("<"):
        return ""
    if not token.endswith(">"):
        return ""
    try:
        raw = bytes.fromhex(token[1:-1])
    except ValueError:
        return ""
    width = len(next(iter(encoding)))
    if width == 0 or len(raw) % width:
        return ""
    return "".join(
        encoding.get(raw[index : index + width], "")
        for index in range(0, len(raw), width)
    )


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


def _number(token: object) -> float:
    if not isinstance(token, str):
        raise DocumentFormatError("document tool is unavailable")
    try:
        return float(token)
    except ValueError:
        raise DocumentFormatError("document tool is unavailable") from None
