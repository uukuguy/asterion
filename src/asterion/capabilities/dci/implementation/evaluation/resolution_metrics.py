"""Pure paper-compatible DCI coverage and localization primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class ResolutionMetricError(ValueError):
    """A resolution metric input is incomplete, ambiguous, or invalid."""


class LocalizationUnavailableReason(str, Enum):
    """Closed reasons why a resolution value cannot be computed."""

    NO_SURFACED_GOLD = "no-surfaced-gold"
    NO_DATASET_SURFACED_GOLD = "no-dataset-surfaced-gold"
    FINAL_CONTEXT_UNAVAILABLE = "final-context-unavailable"


@dataclass(frozen=True, slots=True)
class GoldDocumentSet:
    ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ids != _validated_ids(self.ids, allow_empty=False):
            raise ResolutionMetricError("DCI resolution gold set is invalid")


@dataclass(frozen=True, slots=True)
class SurfacedGoldSet:
    ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ids != _validated_ids(self.ids, allow_empty=True):
            raise ResolutionMetricError("DCI resolution surfaced set is invalid")


@dataclass(frozen=True, slots=True)
class CoverageMetrics:
    any: float
    mean: float
    all: float

    def __post_init__(self) -> None:
        _validate_coverage_metrics(self)


@dataclass(frozen=True, slots=True)
class OptionalMetric:
    value: float | None
    unavailable_reason: LocalizationUnavailableReason | None

    def __post_init__(self) -> None:
        available = (
            type(self.value) is float
            and math.isfinite(self.value)
            and 0.0 <= self.value <= 1.0
            and self.unavailable_reason is None
        )
        unavailable = (
            self.value is None
            and type(self.unavailable_reason) is LocalizationUnavailableReason
        )
        if not (available or unavailable):
            raise ResolutionMetricError("DCI optional resolution value is invalid")


@dataclass(frozen=True, slots=True)
class DocumentLocalization:
    document_id: str
    score: float

    def __post_init__(self) -> None:
        if (
            type(self.document_id) is not str
            or not self.document_id
            or type(self.score) is not float
            or not math.isfinite(self.score)
            or not 0.0 <= self.score <= 1.0
        ):
            raise ResolutionMetricError("DCI document localization is invalid")


@dataclass(frozen=True, slots=True)
class LocalizationAggregate:
    value: float | None
    matched_gold_count: int
    per_document: tuple[DocumentLocalization, ...]
    unavailable_reason: LocalizationUnavailableReason | None

    def __post_init__(self) -> None:
        if type(self.per_document) is not tuple or any(
            type(value) is not DocumentLocalization for value in self.per_document
        ):
            raise ResolutionMetricError("DCI localization aggregate is invalid")
        if type(self.matched_gold_count) is not int or self.matched_gold_count < 0:
            raise ResolutionMetricError("DCI localization aggregate is invalid")
        if self.per_document:
            expected = sum(value.score for value in self.per_document) / len(
                self.per_document
            )
            if (
                self.matched_gold_count != len(self.per_document)
                or type(self.value) is not float
                or not math.isclose(self.value, expected, rel_tol=0.0, abs_tol=1e-15)
                or self.unavailable_reason is not None
            ):
                raise ResolutionMetricError("DCI localization aggregate is invalid")
        elif (
            self.matched_gold_count != 0
            or self.value is not None
            or type(self.unavailable_reason) is not LocalizationUnavailableReason
        ):
            raise ResolutionMetricError("DCI localization aggregate is invalid")


def _validated_ids(values: object, *, allow_empty: bool) -> tuple[str, ...]:
    if type(values) not in {list, tuple}:
        raise ResolutionMetricError("DCI resolution document IDs are invalid")
    ids = tuple(values)
    if (
        (not allow_empty and not ids)
        or any(type(value) is not str or not value for value in ids)
        or len(ids) != len(set(ids))
    ):
        raise ResolutionMetricError("DCI resolution document IDs are invalid")
    return tuple(sorted(ids))


def gold_document_set(ids: object) -> GoldDocumentSet:
    """Create one non-empty unique gold-document identity set."""

    return GoldDocumentSet(_validated_ids(ids, allow_empty=False))


def surfaced_gold_set(gold: GoldDocumentSet, ids: object) -> SurfacedGoldSet:
    """Create the unique subset of gold documents surfaced by observations."""

    if type(gold) is not GoldDocumentSet:
        raise ResolutionMetricError("DCI resolution gold set is invalid")
    if gold.ids != _validated_ids(gold.ids, allow_empty=False):
        raise ResolutionMetricError("DCI resolution gold set is invalid")
    surfaced = _validated_ids(ids, allow_empty=True)
    if not set(surfaced).issubset(gold.ids):
        raise ResolutionMetricError("DCI surfaced documents are not gold documents")
    return SurfacedGoldSet(surfaced)


def compute_query_coverage(
    gold: GoldDocumentSet, surfaced: SurfacedGoldSet
) -> CoverageMetrics:
    """Compute paper any/mean/all coverage for one query."""

    if type(gold) is not GoldDocumentSet or type(surfaced) is not SurfacedGoldSet:
        raise ResolutionMetricError("DCI resolution coverage input is invalid")
    if not gold.ids or not set(surfaced.ids).issubset(gold.ids):
        raise ResolutionMetricError("DCI resolution coverage input is invalid")
    return CoverageMetrics(
        any=coverage_any(gold, surfaced),
        mean=coverage_mean(gold, surfaced),
        all=coverage_all(gold, surfaced),
    )


def _coverage_counts(
    gold: GoldDocumentSet, surfaced: SurfacedGoldSet
) -> tuple[int, int]:
    if type(gold) is not GoldDocumentSet or type(surfaced) is not SurfacedGoldSet:
        raise ResolutionMetricError("DCI resolution coverage input is invalid")
    canonical_gold = _validated_ids(gold.ids, allow_empty=False)
    canonical_surfaced = _validated_ids(surfaced.ids, allow_empty=True)
    if (
        gold.ids != canonical_gold
        or surfaced.ids != canonical_surfaced
        or not set(canonical_surfaced).issubset(canonical_gold)
    ):
        raise ResolutionMetricError("DCI resolution coverage input is invalid")
    return len(canonical_gold), len(canonical_surfaced)


def coverage_any(gold: GoldDocumentSet, surfaced: SurfacedGoldSet) -> float:
    """Return one when any gold document was surfaced."""

    _gold_count, surfaced_count = _coverage_counts(gold, surfaced)
    return float(surfaced_count > 0)


def coverage_mean(gold: GoldDocumentSet, surfaced: SurfacedGoldSet) -> float:
    """Return the fraction of unique gold documents surfaced."""

    gold_count, surfaced_count = _coverage_counts(gold, surfaced)
    return surfaced_count / gold_count


def coverage_all(gold: GoldDocumentSet, surfaced: SurfacedGoldSet) -> float:
    """Return one only when every gold document was surfaced."""

    gold_count, surfaced_count = _coverage_counts(gold, surfaced)
    return float(surfaced_count == gold_count)


def aggregate_query_coverage(values: object) -> CoverageMetrics:
    """Arithmetic per-query aggregation for the three coverage measures."""

    if type(values) not in {list, tuple}:
        raise ResolutionMetricError("DCI query coverage aggregate is invalid")
    metrics = tuple(values)
    if not metrics or any(type(value) is not CoverageMetrics for value in metrics):
        raise ResolutionMetricError("DCI query coverage aggregate is invalid")
    for value in metrics:
        _validate_coverage_metrics(value)
    count = len(metrics)
    return CoverageMetrics(
        any=sum(value.any for value in metrics) / count,
        mean=sum(value.mean for value in metrics) / count,
        all=sum(value.all for value in metrics) / count,
    )


def _validate_coverage_metrics(value: CoverageMetrics) -> None:
    if any(
        type(field) is not float
        or not math.isfinite(field)
        or not 0.0 <= field <= 1.0
        for field in (value.any, value.mean, value.all)
    ):
        raise ResolutionMetricError("DCI resolution coverage value is invalid")
    if not value.all <= value.mean <= value.any:
        raise ResolutionMetricError("DCI resolution coverage relationship is invalid")


def compute_retained_coverage(
    gold: GoldDocumentSet, retained: SurfacedGoldSet | None
) -> OptionalMetric:
    """Compute retained gold fraction, separately from trajectory coverage."""

    if type(gold) is not GoldDocumentSet or not gold.ids:
        raise ResolutionMetricError("DCI retained coverage input is invalid")
    canonical_gold = _validated_ids(gold.ids, allow_empty=False)
    if gold.ids != canonical_gold:
        raise ResolutionMetricError("DCI retained coverage input is invalid")
    if retained is None:
        return OptionalMetric(
            value=None,
            unavailable_reason=LocalizationUnavailableReason.FINAL_CONTEXT_UNAVAILABLE,
        )
    if type(retained) is not SurfacedGoldSet:
        raise ResolutionMetricError("DCI retained coverage input is invalid")
    canonical_retained = _validated_ids(retained.ids, allow_empty=True)
    if (
        retained.ids != canonical_retained
        or not set(canonical_retained).issubset(canonical_gold)
    ):
        raise ResolutionMetricError("DCI retained coverage input is invalid")
    return OptionalMetric(
        value=len(canonical_retained) / len(canonical_gold),
        unavailable_reason=None,
    )


def _positive_character_count(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ResolutionMetricError("DCI localization character count is invalid")
    return value


def normalize_segment_count(
    character_count: object, segment_characters: object
) -> int:
    """Return ν(x)=max(1, ceil(x/cseg)) for explicit positive integers."""

    characters = _positive_character_count(character_count)
    segment = _positive_character_count(segment_characters)
    return max(1, math.ceil(characters / segment))


def localization_candidate_score(
    snippet_characters: object,
    full_document_characters: object,
    segment_characters: object,
) -> float:
    """Compute ψ(ν(snippet),ν(document)) with a finite [0,1] result."""

    snippet = _positive_character_count(snippet_characters)
    full = _positive_character_count(full_document_characters)
    if snippet > full:
        raise ResolutionMetricError("DCI localization snippet exceeds its document")
    a = normalize_segment_count(snippet, segment_characters)
    b = normalize_segment_count(full, segment_characters)
    if b == 1:
        return 1.0
    score = max(1.0 - math.log(a) / math.log(b), 0.0)
    if not math.isfinite(score):
        raise ResolutionMetricError("DCI localization score is invalid")
    return min(max(score, 0.0), 1.0)


def best_document_localization(
    document_id: object,
    full_document_characters: object,
    candidate_snippet_characters: object,
    segment_characters: object,
) -> DocumentLocalization:
    """Keep one surfaced document's maximum candidate or conservative fallback."""

    if type(document_id) is not str or not document_id:
        raise ResolutionMetricError("DCI localization document ID is invalid")
    full = _positive_character_count(full_document_characters)
    if type(candidate_snippet_characters) not in {list, tuple}:
        raise ResolutionMetricError("DCI localization candidates are invalid")
    candidates = tuple(candidate_snippet_characters) or (full,)
    scores = tuple(
        localization_candidate_score(value, full, segment_characters)
        for value in candidates
    )
    return DocumentLocalization(document_id=document_id, score=max(scores))


def query_localization(values: object) -> LocalizationAggregate:
    """Average per-gold maxima over surfaced gold documents for one query."""

    if type(values) not in {list, tuple}:
        raise ResolutionMetricError("DCI query localization input is invalid")
    documents = tuple(values)
    if not documents:
        return LocalizationAggregate(
            value=None,
            matched_gold_count=0,
            per_document=(),
            unavailable_reason=LocalizationUnavailableReason.NO_SURFACED_GOLD,
        )
    _validate_document_localizations(documents, require_unique=True)
    documents = tuple(sorted(documents, key=lambda value: value.document_id))
    return LocalizationAggregate(
        value=sum(value.score for value in documents) / len(documents),
        matched_gold_count=len(documents),
        per_document=documents,
        unavailable_reason=None,
    )


def aggregate_dataset_localization(values: object) -> LocalizationAggregate:
    """Flatten surfaced-gold maxima across queries for paper micro aggregation."""

    if type(values) not in {list, tuple}:
        raise ResolutionMetricError("DCI dataset localization input is invalid")
    queries = tuple(values)
    if not queries or any(type(value) is not LocalizationAggregate for value in queries):
        raise ResolutionMetricError("DCI dataset localization input is invalid")
    for query in queries:
        _validate_query_localization_aggregate(query)
    documents = tuple(
        document for query in queries for document in query.per_document
    )
    if not documents:
        return LocalizationAggregate(
            value=None,
            matched_gold_count=0,
            per_document=(),
            unavailable_reason=LocalizationUnavailableReason.NO_DATASET_SURFACED_GOLD,
        )
    return LocalizationAggregate(
        value=sum(document.score for document in documents) / len(documents),
        matched_gold_count=len(documents),
        per_document=documents,
        unavailable_reason=None,
    )


def _validate_document_localizations(
    documents: tuple[DocumentLocalization, ...], *, require_unique: bool
) -> None:
    if any(type(value) is not DocumentLocalization for value in documents):
        raise ResolutionMetricError("DCI localization documents are invalid")
    for value in documents:
        if (
            type(value.document_id) is not str
            or not value.document_id
            or type(value.score) is not float
            or not math.isfinite(value.score)
            or not 0.0 <= value.score <= 1.0
        ):
            raise ResolutionMetricError("DCI localization documents are invalid")
    if require_unique and len({value.document_id for value in documents}) != len(
        documents
    ):
        raise ResolutionMetricError("DCI query localization documents collide")


def _validate_query_localization_aggregate(query: LocalizationAggregate) -> None:
    documents = query.per_document
    if type(documents) is not tuple:
        raise ResolutionMetricError("DCI dataset localization input is invalid")
    _validate_document_localizations(documents, require_unique=True)
    if documents:
        expected = sum(value.score for value in documents) / len(documents)
        if (
            query.matched_gold_count != len(documents)
            or type(query.value) is not float
            or not math.isclose(query.value, expected, rel_tol=0.0, abs_tol=1e-15)
            or query.unavailable_reason is not None
        ):
            raise ResolutionMetricError("DCI dataset localization input is invalid")
    elif (
        query.matched_gold_count != 0
        or query.value is not None
        or query.unavailable_reason
        is not LocalizationUnavailableReason.NO_SURFACED_GOLD
    ):
        raise ResolutionMetricError("DCI dataset localization input is invalid")
