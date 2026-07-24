"""Pure retrieval parsing and ranking metrics for Asterion DCI."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence, Set
from pathlib import Path
from typing import Any

from asterion.dci.datasets import (
    BenchmarkRow,
    DatasetError,
    normalize_retrieved_path as _normalize_retrieved_path,
    parse_retrieved_documents as _parse_retrieved_documents,
)


class MetricError(ValueError):
    """Safe public error for invalid metric inputs."""


def parse_retrieved_documents(result_text: str) -> list[str]:
    try:
        return _parse_retrieved_documents(result_text)
    except DatasetError as error:
        raise MetricError(str(error)) from error


def parse_retrieved_docs(result_text: str) -> list[str]:
    return parse_retrieved_documents(result_text)


def normalize_retrieved_path(path: str, corpus_dir: Path | None) -> str:
    try:
        return _normalize_retrieved_path(path, corpus_dir)
    except DatasetError as error:
        raise MetricError(str(error)) from error


def ndcg_at_k(retrieved: Sequence[str], gold_set: Set[str], k: int) -> float:
    if type(k) is not int or k <= 0:
        raise MetricError("DCI NDCG k must be a positive integer")
    if (
        isinstance(retrieved, (str, bytes))
        or not isinstance(retrieved, Sequence)
        or not isinstance(gold_set, Set)
    ):
        raise MetricError("DCI NDCG collections are invalid")
    if any(type(document) is not str for document in retrieved) or any(
        type(document) is not str for document in gold_set
    ):
        raise MetricError("DCI NDCG documents must be strings")
    if not gold_set:
        return 0.0
    unique_retrieved: list[str] = []
    seen: set[str] = set()
    for document in retrieved:
        if document not in seen:
            seen.add(document)
            unique_retrieved.append(document)
    dcg = sum(
        1.0 / math.log2(rank + 2)
        for rank, document in enumerate(unique_retrieved[:k])
        if document in gold_set
    )
    ideal_k = min(len(gold_set), k)
    idcg = sum(1.0 / math.log2(rank + 2) for rank in range(ideal_k))
    score = dcg / idcg if idcg > 0 else 0.0
    return min(max(score, 0.0), 1.0)


def compute_ndcg_at_k(retrieved: Sequence[str], gold_set: Set[str], k: int) -> float:
    return ndcg_at_k(retrieved, gold_set, k)


def _row_field(row: BenchmarkRow | Mapping[str, Any], name: str) -> Any:
    if isinstance(row, BenchmarkRow):
        return getattr(row, name)
    if not isinstance(row, Mapping):
        raise MetricError("DCI IR row must be a benchmark row or mapping")
    return row.get(name)


def _gold_documents(row: BenchmarkRow | Mapping[str, Any]) -> tuple[str, ...]:
    gold_docs = _row_field(row, "gold_docs")
    gold_ids = _row_field(row, "gold_ids")
    for candidate in (gold_docs, gold_ids):
        if candidate is not None and (
            type(candidate) not in {list, tuple}
            or any(type(item) is not str or not item for item in candidate)
        ):
            raise MetricError("DCI IR gold documents must be strings")
    if gold_docs is not None and gold_ids is not None:
        raise MetricError("DCI IR row must use exactly one gold alias")
    value = gold_docs or gold_ids or ()
    return tuple(value)


def compute_ir_ndcg(
    final_text: str,
    row: BenchmarkRow | Mapping[str, Any],
    corpus_dir: Path | None,
    k: int = 10,
) -> float:
    gold = _gold_documents(row)
    gold_set = {normalize_retrieved_path(document, corpus_dir) for document in gold}
    retrieved = [
        normalize_retrieved_path(document, corpus_dir)
        for document in parse_retrieved_documents(final_text)
    ]
    query_id = _row_field(row, "query_id")
    if query_id is not None and type(query_id) is not str:
        raise MetricError("DCI IR query ID must be a string")
    query_document = f"{query_id}.txt" if query_id else ""
    if query_document:
        retrieved = [document for document in retrieved if document != query_document]
    return ndcg_at_k(retrieved, gold_set, k)


__all__ = [
    "MetricError",
    "compute_ir_ndcg",
    "compute_ndcg_at_k",
    "ndcg_at_k",
    "normalize_retrieved_path",
    "parse_retrieved_docs",
    "parse_retrieved_documents",
]
