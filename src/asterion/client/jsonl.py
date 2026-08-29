"""Bounded, LF-delimited JSON object framing for client transports."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast


_MAX_SAFE_INTEGER = 9_007_199_254_740_991


class ClientJsonlError(ValueError):
    """Raised for unsafe, incomplete, or non-canonical client JSONL frames."""


class JsonlClientCodec:
    """Incrementally decode only complete, bounded JSON object frames."""

    def __init__(self, *, max_line_bytes: int = 64 * 1024, max_depth: int = 32) -> None:
        if (
            isinstance(max_line_bytes, bool)
            or not isinstance(max_line_bytes, int)
            or max_line_bytes < 2
            or isinstance(max_depth, bool)
            or not isinstance(max_depth, int)
            or max_depth < 1
        ):
            raise ClientJsonlError("client JSONL limits are invalid")
        self._max_line_bytes = max_line_bytes
        self._max_depth = max_depth
        self._buffer = bytearray()
        self._closed = False

    def feed(self, data: bytes, *, eof: bool = False) -> tuple[Mapping[str, object], ...]:
        if self._closed or not isinstance(data, bytes) or b"\r" in data:
            self._closed = True
            raise ClientJsonlError("client JSONL frame is invalid")
        self._buffer.extend(data)
        try:
            lines = _take_complete_lf_lines(self._buffer, self._max_line_bytes)
            if eof and self._buffer:
                raise ClientJsonlError("client JSONL final line is incomplete")
            decoded = tuple(_decode_bounded_object(line, self._max_depth) for line in lines)
        except ClientJsonlError:
            self._closed = True
            raise
        if eof:
            self._closed = True
        return decoded

    def encode(self, value: Mapping[str, object]) -> bytes:
        if self._closed:
            raise ClientJsonlError("client JSONL codec is closed")
        try:
            canonical = _canonical_json_value(
                value, max_depth=self._max_depth, depth=1, ancestors=set()
            )
            if not isinstance(canonical, dict):
                raise ClientJsonlError("client JSONL frame must be an object")
            encoded = json.dumps(
                canonical,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8") + b"\n"
        except Exception:
            self._closed = True
            raise ClientJsonlError("client JSONL value is invalid") from None
        if b"\r" in encoded or len(encoded) > self._max_line_bytes:
            raise ClientJsonlError("client JSONL line exceeds limit")
        return encoded


def _take_complete_lf_lines(buffer: bytearray, max_line_bytes: int) -> tuple[bytes, ...]:
    if b"\r" in buffer:
        raise ClientJsonlError("client JSONL frame is invalid")
    lines: list[bytes] = []
    while (newline := buffer.find(b"\n")) >= 0:
        if newline + 1 > max_line_bytes:
            raise ClientJsonlError("client JSONL line exceeds limit")
        lines.append(bytes(buffer[:newline]))
        del buffer[: newline + 1]
    if len(buffer) >= max_line_bytes:
        raise ClientJsonlError("client JSONL line exceeds limit")
    return tuple(lines)


def _decode_bounded_object(line: bytes, max_depth: int) -> Mapping[str, object]:
    if not line:
        raise ClientJsonlError("client JSONL frame is invalid")
    try:
        parsed = json.loads(
            line.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite,
        )
        canonical = _canonical_json_value(parsed, max_depth=max_depth, depth=1, ancestors=set())
    except Exception:
        raise ClientJsonlError("client JSONL frame is invalid") from None
    if not isinstance(canonical, dict):
        raise ClientJsonlError("client JSONL frame must be an object")
    return cast(Mapping[str, object], _freeze_json_value(canonical))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ClientJsonlError("client JSONL object has duplicate keys")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> object:
    raise ClientJsonlError("client JSONL number is invalid")


def _canonical_json_value(
    value: object, *, max_depth: int, depth: int, ancestors: set[int]
) -> object:
    if depth > max_depth:
        raise ClientJsonlError("client JSONL nesting exceeds limit")
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        if not -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER:
            raise ClientJsonlError("client JSONL number is invalid")
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > _MAX_SAFE_INTEGER:
            raise ClientJsonlError("client JSONL number is invalid")
        return value
    if isinstance(value, Mapping):
        return _canonical_mapping(value, max_depth=max_depth, depth=depth, ancestors=ancestors)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return _canonical_sequence(value, max_depth=max_depth, depth=depth, ancestors=ancestors)
    raise ClientJsonlError("client JSONL value is invalid")


def _canonical_mapping(
    value: Mapping[object, object], *, max_depth: int, depth: int, ancestors: set[int]
) -> dict[str, object]:
    identity = id(value)
    if identity in ancestors:
        raise ClientJsonlError("client JSONL value is invalid")
    ancestors.add(identity)
    try:
        keys = tuple(value)
        if len(keys) != len(value):
            raise ClientJsonlError("client JSONL value is invalid")
        result: dict[str, object] = {}
        for key in keys:
            if not isinstance(key, str) or key in result:
                raise ClientJsonlError("client JSONL value is invalid")
            result[key] = _canonical_json_value(
                value[key], max_depth=max_depth, depth=depth + 1, ancestors=ancestors
            )
        return result
    finally:
        ancestors.remove(identity)


def _canonical_sequence(
    value: Sequence[object], *, max_depth: int, depth: int, ancestors: set[int]
) -> list[object]:
    identity = id(value)
    if identity in ancestors:
        raise ClientJsonlError("client JSONL value is invalid")
    ancestors.add(identity)
    try:
        return [
            _canonical_json_value(item, max_depth=max_depth, depth=depth + 1, ancestors=ancestors)
            for item in tuple(value)
        ]
    finally:
        ancestors.remove(identity)


def _freeze_json_value(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json_value(item) for item in value)
    return value
