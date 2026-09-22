"""Internal canonical JSONL row codec for the control journal."""

from __future__ import annotations

import json
from collections.abc import Mapping


JOURNAL_FILE_VERSION = "asterion.control-journal/v1"
_FILE_ROW_FIELDS = frozenset(
    {"version", "position", "previous_digest", "record_digest", "record"}
)
_RECORD_FIELDS = frozenset({"record_id", "kind", "payload"})


def json_value(value: object) -> object:
    """Convert frozen journal values to canonical JSON container shapes."""

    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    return value


def encode_row(
    position: int,
    previous_digest: str | None,
    record_digest: str,
    record_id: str,
    kind: str,
    payload: Mapping[str, object],
) -> bytes:
    value = {
        "version": JOURNAL_FILE_VERSION,
        "position": position,
        "previous_digest": previous_digest,
        "record_digest": record_digest,
        "record": {
            "record_id": record_id,
            "kind": kind,
            "payload": json_value(payload),
        },
    }
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        + b"\n"
    )


def decode_row(
    raw_line: bytes, expected_position: int, previous_digest: str | None
) -> dict[str, object]:
    """Decode one canonical row without accepting alternate wire encodings."""

    try:
        value = json.loads(raw_line.decode("utf-8", errors="strict"))
        if (
            not isinstance(value, dict)
            or set(value) != _FILE_ROW_FIELDS
            or json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            != raw_line
            or value["version"] != JOURNAL_FILE_VERSION
            or value["position"] != expected_position
            or value["previous_digest"] != previous_digest
            or not isinstance(value["record"], dict)
            or set(value["record"]) != _RECORD_FIELDS
        ):
            raise ValueError("file journal row is invalid")
    except (TypeError, ValueError, UnicodeError):
        raise ValueError("file journal row is invalid") from None
    return value
