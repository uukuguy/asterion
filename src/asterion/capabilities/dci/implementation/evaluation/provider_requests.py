"""Private provider-request capture and closed cross-language validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
from datetime import datetime
from typing import NoReturn, cast

from asterion.pathlight import ContextSegmentSummary, ProviderRequestObservation


_CAPTURE_NAME = "provider-requests.jsonl"
_PRIVATE_SCHEMA = "dci.private-provider-request/v1"
_SAFE_SCHEMA = "dci.provider-request-observation/v1"
_FIXED_ERROR = "provider request capture is invalid"
_MAX_RECORD_BYTES = 64 * 1024 * 1024
_MAX_CAPTURE_BYTES = 512 * 1024 * 1024
# Shape projection expands nesting; this leaves a wide recursion safety margin.
_MAX_JSON_STRUCTURAL_DEPTH = 128
_DIGEST = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
_PRIVATE_FIELDS = frozenset(
    {
        "schema",
        "request_index",
        "captured_at",
        "payload_json",
        "payload_sha256",
        "payload_bytes",
        "shape_sha256",
        "summary_sha256",
    }
)
_SAFE_FIELDS = frozenset(
    {
        "schema",
        "request_index",
        "capture_status",
        "payload_sha256",
        "payload_bytes",
        "shape_sha256",
        "field_count",
        "leaf_count",
        "text_characters",
        "segments",
        "missing_evidence",
        "summary_sha256",
    }
)
_SEGMENT_FIELDS = frozenset(
    {
        "segment_index",
        "role",
        "structure_kind",
        "content_sha256",
        "content_length",
        "source_call_sha256",
        "missing_evidence",
        "segment_sha256",
    }
)
_ROLES = frozenset({"system", "user", "assistant", "tool-result", "unknown"})
_KINDS = frozenset({"message", "tool-result", "contract", "missing"})
_MISSING = object()


class ProviderRequestCaptureError(RuntimeError):
    """Fixed, content-free failure for the private observation side channel."""


def _invalid() -> NoReturn:
    raise ProviderRequestCaptureError(_FIXED_ERROR) from None


class ProviderRequestCapture:
    """An exclusively-created private capture held by descriptor, never by path."""

    __slots__ = ("_fd", "_identity", "_validated_snapshot")

    def __init__(self, descriptor: int, identity: tuple[int, int]) -> None:
        self._fd = descriptor
        self._identity = identity
        self._validated_snapshot: tuple[int, int, int, int] | None = None

    @classmethod
    def open_at(cls, directory_fd: int) -> ProviderRequestCapture:
        """Exclusively create the fixed capture name relative to ``directory_fd``."""

        descriptor = -1
        try:
            if type(directory_fd) is not int or directory_fd < 0:
                _invalid()
            descriptor = os.open(
                _CAPTURE_NAME,
                os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                _invalid()
            return cls(descriptor, (metadata.st_dev, metadata.st_ino))
        except ProviderRequestCaptureError:
            if descriptor >= 0:
                _close_quietly(descriptor)
            raise
        except Exception:
            if descriptor >= 0:
                _close_quietly(descriptor)
            _invalid()

    @property
    def child_fd(self) -> int:
        """Return the exact descriptor the host must explicitly pass to the child."""

        if self._fd < 0:
            _invalid()
        return self._fd

    def validate(
        self, safe_entries: tuple[dict[str, object], ...]
    ) -> tuple[ProviderRequestObservation, ...]:
        """Cross-check raw JSONL against safe entries as one atomic batch."""

        try:
            self._validated_snapshot = None
            if self._fd < 0 or type(safe_entries) is not tuple:
                _invalid()
            raw, snapshot = _read_held_capture(self._fd)
            observations = _validate_raw_safe_batch(raw, snapshot, safe_entries)
            self._validated_snapshot = snapshot
            return observations
        except ProviderRequestCaptureError:
            raise
        except RecursionError:
            _invalid()
        except Exception:
            _invalid()

    def seal(self) -> None:
        """Make the verified held inode read-only and close its writable FD."""

        try:
            if self._fd < 0:
                _invalid()
            os.fsync(self._fd)
            before = os.fstat(self._fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o600
                or (before.st_dev, before.st_ino) != self._identity
                or (
                    self._validated_snapshot is not None
                    and (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                    )
                    != self._validated_snapshot
                )
            ):
                _invalid()
            os.fchmod(self._fd, 0o400)
            os.fsync(self._fd)
            after = os.fstat(self._fd)
            if (
                not stat.S_ISREG(after.st_mode)
                or stat.S_IMODE(after.st_mode) != 0o400
                or (after.st_dev, after.st_ino) != self._identity
                or (after.st_size, after.st_mtime_ns)
                != (before.st_size, before.st_mtime_ns)
            ):
                _invalid()
            self.close()
        except ProviderRequestCaptureError:
            raise
        except Exception:
            _invalid()

    def close(self) -> None:
        """Close the held descriptor; repeated close calls are harmless."""

        descriptor = self._fd
        if descriptor < 0:
            return
        self._fd = -1
        try:
            os.close(descriptor)
        except Exception:
            _invalid()


def _close_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _read_held_capture(
    descriptor: int,
) -> tuple[bytes, tuple[int, int, int, int]]:
    os.fsync(descriptor)
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size < 0
        or before.st_size > _MAX_CAPTURE_BYTES
    ):
        _invalid()
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(descriptor, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            _invalid()
        chunks.append(chunk)
        offset += len(chunk)
    after = os.fstat(descriptor)
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) or stat.S_IMODE(after.st_mode) != 0o600:
        _invalid()
    return b"".join(chunks), (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def read_sealed_provider_requests_at(
    directory_fd: int,
    safe_entries: tuple[dict[str, object], ...],
) -> tuple[ProviderRequestObservation, ...]:
    """Validate one sealed private capture through a caller-held directory FD."""

    descriptor = -1
    try:
        if type(directory_fd) is not int or directory_fd < 0:
            _invalid()
        descriptor = os.open(
            _CAPTURE_NAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        raw, snapshot = _read_sealed_capture(descriptor)
        return _validate_raw_safe_batch(raw, snapshot, safe_entries)
    except ProviderRequestCaptureError:
        raise
    except Exception:
        _invalid()
    finally:
        if descriptor >= 0:
            _close_quietly(descriptor)


def _read_sealed_capture(
    descriptor: int,
) -> tuple[bytes, tuple[int, int, int, int]]:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat.S_IMODE(before.st_mode) != 0o400
        or before.st_size < 0
        or before.st_size > _MAX_CAPTURE_BYTES
    ):
        _invalid()
    chunks: list[bytes] = []
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(descriptor, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            _invalid()
        chunks.append(chunk)
        offset += len(chunk)
    if os.pread(descriptor, 1, before.st_size):
        _invalid()
    after = os.fstat(descriptor)
    snapshot = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if (
        not stat.S_ISREG(after.st_mode)
        or after.st_uid != os.geteuid()
        or stat.S_IMODE(after.st_mode) != 0o400
        or snapshot
        != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    ):
        _invalid()
    return b"".join(chunks), snapshot


def _validate_raw_safe_batch(
    raw: bytes,
    snapshot: tuple[int, int, int, int],
    safe_entries: tuple[dict[str, object], ...],
) -> tuple[ProviderRequestObservation, ...]:
    if (
        type(snapshot) is not tuple
        or len(snapshot) != 4
        or any(type(value) is not int or value < 0 for value in snapshot)
        or type(safe_entries) is not tuple
    ):
        _invalid()
    records = _parse_records(raw)
    if len(records) != len(safe_entries):
        _invalid()
    lines = () if not raw else tuple(raw[:-1].split(b"\n"))
    return tuple(
        _validate_pair(index, line, record, safe)
        for index, (line, record, safe) in enumerate(
            zip(lines, records, safe_entries, strict=True), 1
        )
    )


def _parse_records(raw: bytes) -> tuple[dict[str, object], ...]:
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        _invalid()
    lines = raw[:-1].split(b"\n")
    if any(not line or len(line) + 1 > _MAX_RECORD_BYTES for line in lines):
        _invalid()
    records: list[dict[str, object]] = []
    for line in lines:
        value = _loads_exact(line.decode("utf-8", errors="strict"))
        if type(value) is not dict:
            _invalid()
        records.append(cast(dict[str, object], value))
    return tuple(records)


def _loads_exact(value: str, *, javascript_numbers: bool = False) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                _invalid()
            result[key] = item
        return result

    def invalid_constant(_value: str) -> NoReturn:
        _invalid()

    options: dict[str, object] = {
        "object_pairs_hook": object_pairs,
        "parse_constant": invalid_constant,
    }
    if javascript_numbers:
        options.update(parse_int=float, parse_float=float)
    return json.loads(value, **options)  # type: ignore[arg-type]


def _validate_serialized_json_depth(value: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in value:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            depth += 1
            if depth > _MAX_JSON_STRUCTURAL_DEPTH:
                _invalid()
        elif character in "}]":
            depth -= 1
            if depth < 0:
                _invalid()
    if in_string or escaped or depth != 0:
        _invalid()


def _validate_pair(
    expected_index: int,
    raw_line: bytes,
    record: dict[str, object],
    safe: object,
) -> ProviderRequestObservation:
    if set(record) != _PRIVATE_FIELDS or type(safe) is not dict:
        _invalid()
    safe_mapping = cast(dict[str, object], safe)
    if set(safe_mapping) != _SAFE_FIELDS:
        _invalid()
    if (
        not _equal_text(record["schema"], _PRIVATE_SCHEMA)
        or not _equal_text(safe_mapping["schema"], _SAFE_SCHEMA)
        or not _equal_text(safe_mapping["capture_status"], "captured")
        or not _exact_index(record["request_index"], expected_index)
        or not _exact_index(safe_mapping["request_index"], expected_index)
        or not _valid_timestamp(record["captured_at"])
        or type(record["payload_json"]) is not str
    ):
        _invalid()

    payload_json = cast(str, record["payload_json"])
    payload_bytes = payload_json.encode("utf-8", errors="strict")
    _validate_serialized_json_depth(payload_json)
    payload = _loads_exact(payload_json, javascript_numbers=True)
    if not hmac.compare_digest(_json_stringify(payload), payload_json):
        _invalid()
    summary = _summarize_payload(payload, payload_bytes)

    for name in ("payload_sha256", "shape_sha256", "summary_sha256"):
        if not _valid_digest(record[name]) or not _equal_text(
            record[name], summary[name]
        ):
            _invalid()
    if not _exact_nonnegative_int(record["payload_bytes"], len(payload_bytes)):
        _invalid()
    for name, expected in summary.items():
        supplied = safe_mapping[name]
        if not _safe_equal(supplied, expected):
            _invalid()

    segments = tuple(
        ContextSegmentSummary(**_segment_constructor_values(segment))
        for segment in cast(list[dict[str, object]], summary["segments"])
    )
    return ProviderRequestObservation.build(
        request_index=expected_index,
        payload_sha256=summary["payload_sha256"],
        payload_bytes=summary["payload_bytes"],
        shape_sha256=summary["shape_sha256"],
        field_count=summary["field_count"],
        leaf_count=summary["leaf_count"],
        text_characters=summary["text_characters"],
        private_reference_sha256=hashlib.sha256(raw_line).hexdigest(),
        segments=segments,
    )


def _segment_constructor_values(segment: dict[str, object]) -> dict[str, object]:
    return {name: value for name, value in segment.items() if name != "segment_sha256"}


def _valid_timestamp(value: object) -> bool:
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _valid_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _equal_text(left: object, right: object) -> bool:
    return type(left) is str and type(right) is str and hmac.compare_digest(left, right)


def _exact_index(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _exact_nonnegative_int(value: object, expected: int) -> bool:
    return type(value) is int and value >= 0 and value == expected


def _safe_equal(supplied: object, expected: object) -> bool:
    if type(supplied) is str and type(expected) is str:
        return hmac.compare_digest(supplied, expected)
    if type(supplied) is not type(expected):
        return False
    if type(expected) is list:
        left = cast(list[object], supplied)
        right = cast(list[object], expected)
        return len(left) == len(right) and all(
            _safe_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if type(expected) is dict:
        left_mapping = cast(dict[str, object], supplied)
        right_mapping = cast(dict[str, object], expected)
        return set(left_mapping) == set(right_mapping) and all(
            _safe_equal(left_mapping[name], value)
            for name, value in right_mapping.items()
        )
    return supplied == expected


def _summarize_payload(payload: object, payload_bytes: bytes) -> dict[str, object]:
    projection, field_count, leaf_count, text_characters = _summarize_shape(payload)
    segments = [
        _close_segment(index, *draft)
        for index, draft in enumerate(_segment_drafts(payload))
    ]
    missing_evidence = (
        ["context-segment"]
        if any(cast(bool, segment["missing_evidence"]) for segment in segments)
        else []
    )
    unsigned: dict[str, object] = {
        "payload_bytes": len(payload_bytes),
        "shape_sha256": _canonical_digest("dci.provider-request/shape/v1", projection),
        "field_count": field_count,
        "leaf_count": leaf_count,
        "text_characters": text_characters,
        "segments": segments,
        "missing_evidence": missing_evidence,
    }
    return {
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        **unsigned,
        "summary_sha256": _canonical_digest(
            "dci.provider-request-observation/summary/v1", unsigned
        ),
    }


def _summarize_shape(value: object) -> tuple[object, int, int, int]:
    if type(value) is list:
        children = [_summarize_shape(item) for item in cast(list[object], value)]
        return (
            ["array", [child[0] for child in children]],
            sum(child[1] for child in children),
            sum(child[2] for child in children),
            sum(child[3] for child in children),
        )
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        children = [
            _summarize_shape(mapping[key]) for key in sorted(mapping, key=_scalar_key)
        ]
        return (
            ["object", [child[0] for child in children]],
            len(children) + sum(child[1] for child in children),
            sum(child[2] for child in children),
            sum(child[3] for child in children),
        )
    kind = (
        "null"
        if value is None
        else "boolean"
        if type(value) is bool
        else "number"
        if type(value) in (int, float)
        else "string"
    )
    return [kind], 0, 1, len(cast(str, value)) if type(value) is str else 0


def _scalar_key(value: str) -> tuple[int, ...]:
    return tuple(ord(character) for character in value)


def _segment_drafts(
    payload: object,
) -> list[tuple[str, str, object, object, bool]]:
    if type(payload) is not dict:
        return [("unknown", "missing", _MISSING, None, True)]
    mapping = cast(dict[str, object], payload)
    drafts: list[tuple[str, str, object, object, bool]] = []
    for name in ("instructions", "system"):
        if name in mapping:
            content = mapping[name]
            drafts.append(("system", "contract", content, None, content is None))
    messages = (
        mapping["messages"]
        if type(mapping.get("messages")) is list
        else mapping["input"]
        if type(mapping.get("input")) is list
        else None
    )
    if type(messages) is list:
        for message in cast(list[object], messages):
            drafts.extend(_message_drafts(message))
    if not drafts:
        drafts.append(("unknown", "missing", _MISSING, None, True))
    return drafts


def _message_drafts(value: object) -> list[tuple[str, str, object, object, bool]]:
    if type(value) is not dict:
        return [("unknown", "missing", _MISSING, None, True)]
    mapping = cast(dict[str, object], value)
    role_value = mapping.get("role")
    if role_value in ("tool", "tool-result", "tool_result", "toolResult"):
        return [_tool_result_draft(mapping)]
    role = role_value if role_value in ("system", "user", "assistant") else "unknown"
    content = (
        mapping["content"] if "content" in mapping else mapping.get("text", _MISSING)
    )
    if type(content) is list and any(_is_tool_result(item) for item in content):
        drafts: list[tuple[str, str, object, object, bool]] = []
        for item in cast(list[object], content):
            if _is_tool_result(item):
                drafts.append(_tool_result_draft(cast(dict[str, object], item)))
            elif type(item) is dict:
                block = cast(dict[str, object], item)
                block_content = block["text"] if "text" in block else block
                drafts.append(
                    (
                        cast(str, role),
                        "missing" if role == "unknown" else "message",
                        _MISSING if role == "unknown" else block_content,
                        None,
                        role == "unknown",
                    )
                )
            else:
                drafts.append(
                    (
                        cast(str, role),
                        "missing" if role == "unknown" else "message",
                        _MISSING if role == "unknown" else item,
                        None,
                        role == "unknown",
                    )
                )
        return drafts
    return [
        (
            cast(str, role),
            "missing" if role == "unknown" else "message",
            _MISSING if role == "unknown" else content,
            None,
            role == "unknown" or content is _MISSING,
        )
    ]


def _is_tool_result(value: object) -> bool:
    return type(value) is dict and cast(dict[str, object], value).get("type") in (
        "tool_result",
        "tool-result",
        "toolResult",
    )


def _tool_result_draft(
    value: dict[str, object],
) -> tuple[str, str, object, object, bool]:
    content = value["content"] if "content" in value else value.get("text", _MISSING)
    source = value.get(
        "toolCallId", value.get("tool_call_id", value.get("tool_use_id", _MISSING))
    )
    return (
        "tool-result",
        "tool-result",
        content,
        source,
        content is _MISSING or type(source) is not str or not source,
    )


def _close_segment(
    index: int,
    role: str,
    kind: str,
    content: object,
    source: object,
    missing: bool,
) -> dict[str, object]:
    content_digest, content_length = _content_summary(content)
    source_digest = (
        hashlib.sha256(_node_utf8(source)).hexdigest()
        if type(source) is str and source
        else None
    )
    unsigned: dict[str, object] = {
        "segment_index": index,
        "role": role,
        "structure_kind": kind,
        "content_sha256": content_digest,
        "content_length": content_length,
        "source_call_sha256": source_digest,
        "missing_evidence": missing or content_digest is None,
    }
    return {
        **unsigned,
        "segment_sha256": _canonical_digest(
            "asterion.pathlight/context-segment-summary/v1", unsigned
        ),
    }


def _content_summary(value: object) -> tuple[str | None, int | None]:
    if value is _MISSING or value is None:
        return None, None
    rendered = value if type(value) is str else _canonical_json(value)
    text = cast(str, rendered)
    normalized = _node_string(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), len(normalized)


def _node_utf8(value: str) -> bytes:
    return _node_string(value).encode("utf-8")


def _node_string(value: str) -> str:
    """Apply Node's UTF-8 treatment while preserving JS code-point length."""

    normalized: list[str] = []
    index = 0
    while index < len(value):
        codepoint = ord(value[index])
        if 0xD800 <= codepoint <= 0xDBFF and index + 1 < len(value):
            following = ord(value[index + 1])
            if 0xDC00 <= following <= 0xDFFF:
                normalized.append(
                    chr(0x10000 + ((codepoint - 0xD800) << 10) + following - 0xDC00)
                )
                index += 2
                continue
        normalized.append("\ufffd" if 0xD800 <= codepoint <= 0xDFFF else value[index])
        index += 1
    return "".join(normalized)


def _canonical_digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_json({"domain": domain, "value": value}).encode("utf-8")
    ).hexdigest()


def _canonical_json(value: object) -> str:
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        return (
            "{"
            + ",".join(
                f"{_json_string(key)}:{_canonical_json(mapping[key])}"
                for key in sorted(mapping, key=_scalar_key)
            )
            + "}"
        )
    if type(value) is list:
        return (
            "["
            + ",".join(_canonical_json(item) for item in cast(list[object], value))
            + "]"
        )
    return _json_primitive(value)


def _json_stringify(value: object) -> str:
    if type(value) is dict:
        mapping = cast(dict[str, object], value)
        return (
            "{"
            + ",".join(
                f"{_json_string(key)}:{_json_stringify(item)}"
                for key, item in mapping.items()
            )
            + "}"
        )
    if type(value) is list:
        return (
            "["
            + ",".join(_json_stringify(item) for item in cast(list[object], value))
            + "]"
        )
    return _json_primitive(value)


def _json_primitive(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return _json_string(value)
    if type(value) is int:
        if abs(value) >= 10**21:
            _invalid()
        return str(value)
    if type(value) is float:
        if not math.isfinite(value):
            _invalid()
        return _js_number(value)
    _invalid()


def _json_string(value: str) -> str:
    pieces = ['"']
    escapes = {
        '"': '\\"',
        "\\": "\\\\",
        "\b": "\\b",
        "\f": "\\f",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
    }
    for character in value:
        codepoint = ord(character)
        if character in escapes:
            pieces.append(escapes[character])
        elif codepoint < 0x20 or 0xD800 <= codepoint <= 0xDFFF:
            pieces.append(f"\\u{codepoint:04x}")
        else:
            pieces.append(character)
    pieces.append('"')
    return "".join(pieces)


def _js_number(value: float) -> str:
    if value == 0:
        return "0"
    negative = value < 0
    rendered = repr(abs(value)).lower()
    coefficient, separator, exponent_text = rendered.partition("e")
    exponent = int(exponent_text) if separator else 0
    integer, dot, fraction = coefficient.partition(".")
    digits = integer + (fraction if dot else "")
    decimal_position = len(integer) + exponent
    digits = digits.rstrip("0") if dot else digits
    if not digits:
        digits = "0"
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        if decimal_position <= 0:
            result = "0." + "0" * (-decimal_position) + digits
        elif decimal_position >= len(digits):
            result = digits + "0" * (decimal_position - len(digits))
        else:
            result = digits[:decimal_position] + "." + digits[decimal_position:]
    else:
        exponent = decimal_position - 1
        mantissa = digits[0] + (("." + digits[1:]) if len(digits) > 1 else "")
        result = f"{mantissa}e{'+' if exponent >= 0 else ''}{exponent}"
    return ("-" if negative else "") + result


__all__ = ("ProviderRequestCapture", "ProviderRequestCaptureError")
