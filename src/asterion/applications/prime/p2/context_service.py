"""P2 context service: bounded retrieval/transform over an Asterion-owned corpus.

The service is the only seam through which P2's source material reaches
the model. Its two operations — :meth:`P2ContextService.retrieve` and
:meth:`P2ContextService.transform` — accept an operator-owned corpus path
and a bounds tuple, never the corpus content itself. Phase 6 builds
detach/checkpoint/attach/recovery on top of this surface.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class P2ContextSlice:
    """One bounded slice of an operator-owned corpus, returned to the runtime."""

    corpus_path: str
    operation: str
    bounds: tuple[int, int]
    payload: tuple[dict[str, object], ...]
    payload_sha256: str
    bytes_returned: int

    def __post_init__(self) -> None:
        if (
            type(self.corpus_path) is not str
            or not self.corpus_path
            or self.operation not in {"retrieve", "transform"}
            or type(self.bounds) is not tuple
            or len(self.bounds) != 2
            or not all(type(part) is int and part >= 0 for part in self.bounds)
            or self.bounds[0] > self.bounds[1]
            or type(self.payload_sha256) is not str
            or len(self.payload_sha256) != 64
            or type(self.bytes_returned) is not int
            or self.bytes_returned < 0
        ):
            raise ValueError("P2 context slice is invalid")
        # Use the pre-computed digest from the producer; do not re-digest.
        serialized = json.dumps(
            [record for record in self.payload],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(serialized).hexdigest() != self.payload_sha256:
            raise ValueError("P2 context slice digest does not match payload")
        if len(serialized) != self.bytes_returned:
            raise ValueError("P2 context slice byte count does not match payload")


class P2ContextServiceError(RuntimeError):
    """Operator-owned corpus input was refused before any retrieval ran."""


class P2ContextService:
    """Read-only, bounded retrieval/transform over an Asterion-owned corpus."""

    __slots__ = ("_corpus_path", "_records")

    def __init__(self, corpus_path: Path | str) -> None:
        try:
            resolved = Path(corpus_path).resolve(strict=True)
        except OSError as error:
            raise P2ContextServiceError("P2 corpus path is unusable") from error
        if not resolved.is_file():
            raise P2ContextServiceError("P2 corpus path is not a file")
        try:
            raw = resolved.read_bytes()
        except OSError as error:
            raise P2ContextServiceError("P2 corpus could not be read") from error
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as error:
            raise P2ContextServiceError("P2 corpus is not valid JSON") from error
        if not isinstance(decoded, list):
            raise P2ContextServiceError("P2 corpus must be a JSON array")
        records: list[dict[str, object]] = []
        for index, record in enumerate(decoded):
            if not isinstance(record, dict):
                raise P2ContextServiceError(
                    f"P2 corpus record {index} is not a JSON object"
                )
            records.append(record)
        self._corpus_path = resolved
        self._records = tuple(records)

    @property
    def corpus_path(self) -> str:
        return str(self._corpus_path)

    @property
    def record_count(self) -> int:
        return len(self._records)

    def _slice(self, bounds: tuple[int, int]) -> tuple[dict[str, object], ...]:
        start, end = bounds
        if start > end or end > len(self._records):
            raise P2ContextServiceError(
                f"P2 bounds {bounds} exceed corpus size {len(self._records)}"
            )
        return self._records[start:end]

    @staticmethod
    def _digest(payload: Iterable[dict[str, object]]) -> tuple[str, int]:
        serialized = json.dumps(
            [record for record in payload],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest(), len(serialized)

    def retrieve(
        self,
        *,
        bounds: tuple[int, int] = (0, 1),
    ) -> P2ContextSlice:
        payload = self._slice(bounds)
        digest, size = self._digest(payload)
        return P2ContextSlice(
            corpus_path=str(self._corpus_path),
            operation="retrieve",
            bounds=bounds,
            payload=tuple(payload),
            payload_sha256=digest,
            bytes_returned=size,
        )

    def transform(
        self,
        *,
        select_keys: tuple[str, ...],
        bounds: tuple[int, int] = (0, 1),
    ) -> P2ContextSlice:
        if not select_keys:
            raise P2ContextServiceError(
                "P2 transform requires at least one selected key"
            )
        sliced = self._slice(bounds)
        projected: list[dict[str, object]] = []
        for record in sliced:
            projected.append({key: record[key] for key in select_keys if key in record})
        digest, size = self._digest(projected)
        return P2ContextSlice(
            corpus_path=str(self._corpus_path),
            operation="transform",
            bounds=bounds,
            payload=tuple(projected),
            payload_sha256=digest,
            bytes_returned=size,
        )


__all__ = (
    "P2ContextService",
    "P2ContextServiceError",
    "P2ContextSlice",
)