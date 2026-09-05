"""Private canonical corpus and host-side aggregate for the P2 preset."""

from __future__ import annotations

from hashlib import sha256
import json


class PrimeP2DevelopmentWorkloadError(ValueError):
    """The private P2 workload cannot be admitted."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P2 development workload is unavailable")


# The model receives only the schema and container path.  These records never
# cross a public boundary or appear in the trace.
_RECORDS = (
    {"include": False, "value": 2, "private": "P2_PRIVATE_SENTINEL_01"},
    {"include": True, "value": 5, "private": "P2_PRIVATE_SENTINEL_02"},
    {"include": False, "value": 3, "private": "P2_PRIVATE_SENTINEL_03"},
    {"include": True, "value": 7, "private": "P2_PRIVATE_SENTINEL_04"},
    {"include": False, "value": 13, "private": "P2_PRIVATE_SENTINEL_05"},
    {"include": True, "value": 11, "private": "P2_PRIVATE_SENTINEL_06"},
    {"include": False, "value": 17, "private": "P2_PRIVATE_SENTINEL_07"},
    {"include": False, "value": 19, "private": "P2_PRIVATE_SENTINEL_08"},
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


_CORPUS = b"\n".join(_canonical(record) for record in _RECORDS) + b"\n"
P2_DEVELOPMENT_CORPUS_DIGEST = "sha256:" + sha256(_CORPUS).hexdigest()
P2_DEVELOPMENT_WORKLOAD_DIGEST = P2_DEVELOPMENT_CORPUS_DIGEST
P2_DEVELOPMENT_AGGREGATE = {"count": 3, "sum": 23}


def canonical_p2_development_corpus_bytes() -> bytes:
    return _CORPUS


def p2_development_aggregate(corpus: bytes) -> dict[str, int]:
    if type(corpus) is not bytes or corpus != _CORPUS:
        raise PrimeP2DevelopmentWorkloadError()
    try:
        records = [json.loads(line) for line in corpus.splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PrimeP2DevelopmentWorkloadError() from None
    if len(records) != 8 or any(type(row) is not dict or set(row) != {"include", "value", "private"} or type(row["include"]) is not bool or type(row["value"]) is not int or type(row["private"]) is not str for row in records):
        raise PrimeP2DevelopmentWorkloadError()
    aggregate = {"count": sum(row["include"] for row in records), "sum": sum(row["value"] for row in records if row["include"])}
    if aggregate != P2_DEVELOPMENT_AGGREGATE:
        raise PrimeP2DevelopmentWorkloadError()
    return aggregate


__all__ = ("P2_DEVELOPMENT_AGGREGATE", "P2_DEVELOPMENT_CORPUS_DIGEST", "P2_DEVELOPMENT_WORKLOAD_DIGEST", "PrimeP2DevelopmentWorkloadError", "canonical_p2_development_corpus_bytes", "p2_development_aggregate")
