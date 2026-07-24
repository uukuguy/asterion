"""Body-free reproduction manifests and deterministic statistical comparison."""

from __future__ import annotations

import json
import math
import os
import random
import re
import stat
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from asterion.dci.experiment_profiles import (
    ExperimentProfile,
    experiment_profile_sha256,
    experiment_profile_ids,
    resolve_experiment_profile,
)
from asterion.dci.paper_benchmarks import canonical_sha256
from asterion.dci.paper_benchmarks import resolve_paper_benchmark
from asterion.dci.paper_benchmarks import resolve_paper_experiment_scope

RUN_MANIFEST_SCHEMA = "dci.reproduction-run/v1"
COMPARISON_SCHEMA = "dci.reproduction-comparison/v1"
RESULT_SCHEMA = "dci.reproduction-results/v1"
ESTIMATOR_NAME = "paired-bootstrap-percentile/v1"
TARGET_ESTIMATOR_NAME = "one-sample-bootstrap-percentile/v1"
ESTIMATOR_SEED = 340_007
ESTIMATOR_RESAMPLES = 10_000

_SHA256 = re.compile(r"[0-9a-f]{64}")
_PUBLIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]*")
_VERSIONED_REASON = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]*/v[1-9][0-9]*")
_STATUSES = ("completed", "failed", "cancelled", "timed_out", "missing")
_PRODUCTS = ("original-dci", "asterion-dci")
_ACCURACY_METRIC = "llm-answer-correctness"
_NDCG_METRIC = "ndcg@10-binary-deduplicated"
_METRIC_IDENTITIES = {_ACCURACY_METRIC, _NDCG_METRIC}


def _is_published_target_scope(selection_id: str) -> bool:
    return resolve_paper_experiment_scope(selection_id).experiment == "main-results"


def _validate_published_target_selection(
    profile: ExperimentProfile,
    dataset_id: str,
    selection_id: str,
    selection_sha256: str,
    query_ids: tuple[str, ...] | None,
    query_count: int | None,
) -> None:
    scope = resolve_paper_experiment_scope(selection_id)
    expected = dict(zip(profile.scope_ids, profile.selected_ids_sha256, strict=True))
    if (
        expected.get(selection_id) != selection_sha256
        or scope.dataset_id != dataset_id
        or (query_count is not None and scope.selection_count != query_count)
        or (
            query_ids is not None
            and canonical_sha256(tuple(sorted(query_ids))) != selection_sha256
        )
    ):
        raise ValueError("DCI published target selection identity drifted")


def _metric_contract(profile_id: str) -> Mapping[str, object]:
    if profile_id not in experiment_profile_ids():
        raise ValueError("DCI reproduction metric contract profile is invalid")
    return MappingProxyType(
        {
            "identity": "dci.reproduction-metric-contract/v1",
            "profile_id": profile_id,
            "metric_identities": (_ACCURACY_METRIC, _NDCG_METRIC),
            "allowed_exclusion_reasons": ("metric.not-applicable/v1",),
            "allowed_exclusion_statuses": ("completed",),
        }
    )


def reproduction_metric_contract_sha256(profile_id: str) -> str:
    contract = _metric_contract(profile_id)
    return canonical_sha256(
        {
            "identity": contract["identity"],
            "profile_id": contract["profile_id"],
            "metric_identities": list(contract["metric_identities"]),  # type: ignore[arg-type]
            "allowed_exclusion_reasons": list(
                contract["allowed_exclusion_reasons"]  # type: ignore[arg-type]
            ),
            "allowed_exclusion_statuses": list(
                contract["allowed_exclusion_statuses"]  # type: ignore[arg-type]
            ),
        }
    )
_MANIFEST_KEYS = {
    "schema",
    "run_id",
    "product",
    "implementation_sha256",
    "profile_id",
    "profile_sha256",
    "runtime",
    "dataset_id",
    "selection_id",
    "selection_sha256",
    "effective_config_sha256",
    "product_effective_config_sha256",
    "metric_contract_sha256",
    "metric_identities",
    "queries",
    "aggregates",
    "identity_sha256",
}
_QUERY_KEYS = {
    "query_id",
    "status",
    "judge_verdict",
    "ndcg_at_10",
    "failure_class",
    "exclusion_reason",
    "evidence_sha256",
    "operations",
    "tokens",
    "cost_usd",
}
_AGGREGATE_KEYS = {
    "query_count",
    "included_count",
    "excluded_count",
    "completed_count",
    "failed_count",
    "cancelled_count",
    "timed_out_count",
    "missing_count",
    "accuracy",
    "mean_ndcg_at_10",
    "agent_operations",
    "judge_operations",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_usd",
}
_COMPARISON_KEYS = {
    "schema",
    "comparison_kind",
    "profile_id",
    "profile_sha256",
    "profile_provider",
    "profile_model",
    "runtime",
    "dataset_id",
    "selection_id",
    "selection_sha256",
    "effective_config_sha256",
    "metric_contract_sha256",
    "metric_identities",
    "baseline_product",
    "baseline_implementation_sha256",
    "baseline_product_effective_config_sha256",
    "candidate_product",
    "candidate_implementation_sha256",
    "candidate_product_effective_config_sha256",
    "baseline_run_sha256",
    "candidate_run_sha256",
    "target_identity",
    "target_sha256",
    "target_sample_ids",
    "target_samples",
    "pair_ids",
    "exclusion_ids",
    "pairs",
    "exclusions",
    "baseline",
    "candidate",
    "metrics",
    "accepted",
    "identity_sha256",
}
_FORBIDDEN_KEY_PARTS = (
    "answer",
    "prompt",
    "credential",
    "secret",
    "api_key",
    "authorization",
    "tool_body",
    "request_body",
    "response_body",
    "private_path",
)


def _resource_mapping(name: str) -> dict[str, object]:
    try:
        value = json.loads(
            resources.files("asterion.dci.resources")
            .joinpath(name)
            .read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError("DCI reproduction resource is invalid") from error
    if type(value) is not dict:
        raise RuntimeError("DCI reproduction resource is invalid")
    return value


def reproduction_result_schema_sha256() -> str:
    return canonical_sha256(_resource_mapping("reproduction-result.schema.json"))


def reproduction_target_schema_sha256() -> str:
    value = _resource_mapping("reproduction-target.schema.json")
    if value.get("$id") != "dci.reproduction-target/v1":
        raise RuntimeError("DCI reproduction target schema is invalid")
    return canonical_sha256(value)


def reproduction_targets_sha256() -> str:
    value = _resource_mapping("reproduction-targets.json")
    if value.get("schema") != "dci.reproduction-target/v1":
        raise RuntimeError("DCI reproduction target registry is invalid")
    return canonical_sha256(value)


def _published_target(profile_id: str) -> Mapping[str, object]:
    registry = _resource_mapping("reproduction-targets.json")
    targets = registry.get("targets")
    if registry.get("schema") != "dci.reproduction-target/v1" or type(targets) is not list:
        raise RuntimeError("DCI reproduction target registry is invalid")
    matches = [
        target
        for target in targets
        if type(target) is dict and target.get("profile_id") == profile_id
    ]
    if len(matches) != 1:
        raise ValueError("DCI reproduction published target is unavailable")
    target = matches[0]
    required = {
        "target_id",
        "profile_id",
        "source_id",
        "source_url",
        "agentic_search_accuracy",
        "qa_accuracy",
        "ir_ndcg_at_10",
        "dataset_targets",
    }
    dataset_targets = target.get("dataset_targets")
    if (
        set(target) != required
        or type(dataset_targets) is not dict
        or not dataset_targets
        or any(
            type(dataset_id) is not str
            or _PUBLIC_ID.fullmatch(dataset_id) is None
            or _require_optional_unit(value, "published target") is None
            for dataset_id, value in dataset_targets.items()
        )
    ):
        raise RuntimeError("DCI reproduction target registry is invalid")
    _require_public_id(target["target_id"], "published target ID")
    _require_public_id(target["profile_id"], "published target profile")
    return MappingProxyType(dict(target))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DCI reproduction manifest contains a duplicate key")
        value[key] = item
    return value


def _require_exact_mapping(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"DCI reproduction {label} schema is invalid")
    return value


def _require_public_id(value: object, label: str) -> str:
    if type(value) is not str or _PUBLIC_ID.fullmatch(value) is None:
        raise ValueError(f"DCI reproduction {label} is invalid")
    return value


def _require_sha256(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"DCI reproduction {label} is invalid")
    return value


def _require_count(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"DCI reproduction {label} is invalid")
    return value


def _require_finite(value: object, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"DCI reproduction {label} is invalid")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"DCI reproduction {label} is invalid")
    return result


def _require_optional_unit(value: object, label: str) -> float | None:
    if value is None:
        return None
    result = _require_finite(value, label, minimum=0.0)
    if result > 1.0:
        raise ValueError(f"DCI reproduction {label} is invalid")
    return result


def _reject_body_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                raise ValueError("DCI reproduction evidence is not body-free")
            _reject_body_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_body_fields(item)


@dataclass(frozen=True, slots=True)
class OperationCounts:
    agent: int
    judge: int

    def __post_init__(self) -> None:
        _require_count(self.agent, "agent operation count")
        _require_count(self.judge, "Judge operation count")

    def to_dict(self) -> dict[str, int]:
        self.__post_init__()
        return {"agent": self.agent, "judge": self.judge}


@dataclass(frozen=True, slots=True)
class TokenCounts:
    input: int
    cached_input: int
    output: int

    def __post_init__(self) -> None:
        _require_count(self.input, "input token count")
        _require_count(self.cached_input, "cached input token count")
        _require_count(self.output, "output token count")

    def to_dict(self) -> dict[str, int]:
        self.__post_init__()
        return {
            "input": self.input,
            "cached_input": self.cached_input,
            "output": self.output,
        }


@dataclass(frozen=True, slots=True)
class QueryEvidence:
    query_id: str
    status: str
    judge_verdict: bool | None
    ndcg_at_10: float | None
    failure_class: str | None
    exclusion_reason: str | None
    evidence_sha256: str
    operations: OperationCounts
    tokens: TokenCounts
    cost_usd: float

    def __post_init__(self) -> None:
        _require_public_id(self.query_id, "query ID")
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("DCI reproduction query status is invalid")
        if self.judge_verdict is not None and type(self.judge_verdict) is not bool:
            raise ValueError("DCI reproduction Judge verdict is invalid")
        _require_optional_unit(self.ndcg_at_10, "NDCG@10")
        if self.failure_class is not None and (
            type(self.failure_class) is not str
            or _VERSIONED_REASON.fullmatch(self.failure_class) is None
        ):
            raise ValueError("DCI reproduction failure class is invalid")
        if self.exclusion_reason is not None and (
            type(self.exclusion_reason) is not str
            or _VERSIONED_REASON.fullmatch(self.exclusion_reason) is None
        ):
            raise ValueError("DCI reproduction exclusion reason is invalid")
        if self.status == "completed":
            if self.failure_class is not None:
                raise ValueError("DCI completed query cannot contain a failure class")
            if (
                self.exclusion_reason is None
                and self.judge_verdict is None
                and self.ndcg_at_10 is None
            ):
                raise ValueError("DCI completed query has no metric evidence")
        elif (
            self.failure_class is None
            or self.judge_verdict is not None
            or self.ndcg_at_10 is not None
        ):
            raise ValueError("DCI non-completed query evidence is invalid")
        _require_sha256(self.evidence_sha256, "evidence digest")
        if type(self.operations) is not OperationCounts or type(self.tokens) is not TokenCounts:
            raise ValueError("DCI reproduction query totals are invalid")
        self.operations.__post_init__()
        self.tokens.__post_init__()
        _require_finite(self.cost_usd, "cost", minimum=0.0)

    @classmethod
    def from_mapping(cls, value: object) -> "QueryEvidence":
        row = _require_exact_mapping(value, _QUERY_KEYS, "query")
        query_id = _require_public_id(row["query_id"], "query ID")
        status = row["status"]
        if type(status) is not str or status not in _STATUSES:
            raise ValueError("DCI reproduction query status is invalid")
        verdict = row["judge_verdict"]
        if verdict is not None and type(verdict) is not bool:
            raise ValueError("DCI reproduction Judge verdict is invalid")
        ndcg = _require_optional_unit(row["ndcg_at_10"], "NDCG@10")
        failure = row["failure_class"]
        exclusion = row["exclusion_reason"]
        if failure is not None and (
            type(failure) is not str or _VERSIONED_REASON.fullmatch(failure) is None
        ):
            raise ValueError("DCI reproduction failure class is invalid")
        if exclusion is not None and (
            type(exclusion) is not str
            or _VERSIONED_REASON.fullmatch(exclusion) is None
        ):
            raise ValueError("DCI reproduction exclusion reason is invalid")
        if status == "completed":
            if failure is not None:
                raise ValueError("DCI completed query cannot contain a failure class")
            if exclusion is None and verdict is None and ndcg is None:
                raise ValueError("DCI completed query has no metric evidence")
        elif failure is None or verdict is not None or ndcg is not None:
            raise ValueError("DCI non-completed query evidence is invalid")
        operations = _require_exact_mapping(
            row["operations"], {"agent", "judge"}, "operation totals"
        )
        tokens = _require_exact_mapping(
            row["tokens"], {"input", "cached_input", "output"}, "token totals"
        )
        return cls(
            query_id=query_id,
            status=status,
            judge_verdict=verdict,
            ndcg_at_10=ndcg,
            failure_class=failure,
            exclusion_reason=exclusion,
            evidence_sha256=_require_sha256(row["evidence_sha256"], "evidence digest"),
            operations=OperationCounts(
                agent=_require_count(operations["agent"], "agent operation count"),
                judge=_require_count(operations["judge"], "Judge operation count"),
            ),
            tokens=TokenCounts(
                input=_require_count(tokens["input"], "input token count"),
                cached_input=_require_count(
                    tokens["cached_input"], "cached input token count"
                ),
                output=_require_count(tokens["output"], "output token count"),
            ),
            cost_usd=_require_finite(row["cost_usd"], "cost", minimum=0.0),
        )

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "query_id": self.query_id,
            "status": self.status,
            "judge_verdict": self.judge_verdict,
            "ndcg_at_10": self.ndcg_at_10,
            "failure_class": self.failure_class,
            "exclusion_reason": self.exclusion_reason,
            "evidence_sha256": self.evidence_sha256,
            "operations": self.operations.to_dict(),
            "tokens": self.tokens.to_dict(),
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True, slots=True)
class RunAggregates:
    query_count: int
    included_count: int
    excluded_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    timed_out_count: int
    missing_count: int
    accuracy: float | None
    mean_ndcg_at_10: float | None
    agent_operations: int
    judge_operations: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float

    def __post_init__(self) -> None:
        count_names = (
            "query_count",
            "included_count",
            "excluded_count",
            "completed_count",
            "failed_count",
            "cancelled_count",
            "timed_out_count",
            "missing_count",
            "agent_operations",
            "judge_operations",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "total_tokens",
        )
        for name in count_names:
            _require_count(getattr(self, name), name.replace("_", " "))
        _require_optional_unit(self.accuracy, "accuracy")
        _require_optional_unit(self.mean_ndcg_at_10, "mean NDCG@10")
        _require_finite(self.cost_usd, "aggregate cost", minimum=0.0)
        if self.query_count < 1 or self.query_count != self.included_count + self.excluded_count:
            raise ValueError("DCI reproduction aggregate query counts are inconsistent")
        if self.included_count != sum(
            (
                self.completed_count,
                self.failed_count,
                self.cancelled_count,
                self.timed_out_count,
                self.missing_count,
            )
        ):
            raise ValueError("DCI reproduction aggregate status counts are inconsistent")
        if self.total_tokens != self.input_tokens + self.cached_input_tokens + self.output_tokens:
            raise ValueError("DCI reproduction aggregate token counts are inconsistent")

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            name: getattr(self, name)
            for name in (
                "query_count",
                "included_count",
                "excluded_count",
                "completed_count",
                "failed_count",
                "cancelled_count",
                "timed_out_count",
                "missing_count",
                "accuracy",
                "mean_ndcg_at_10",
                "agent_operations",
                "judge_operations",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "total_tokens",
                "cost_usd",
            )
        }


def _computed_aggregates(
    queries: tuple[QueryEvidence, ...],
    metric_identities: tuple[str, ...],
    profile_id: str,
) -> RunAggregates:
    contract = _metric_contract(profile_id)
    allowed_statuses = set(contract["allowed_exclusion_statuses"])
    included = tuple(
        row
        for row in queries
        if row.exclusion_reason is None or row.status not in allowed_statuses
    )
    has_accuracy = _ACCURACY_METRIC in metric_identities
    has_ndcg = _NDCG_METRIC in metric_identities
    accuracy_values = (
        tuple(
            1.0 if row.status == "completed" and row.judge_verdict is True else 0.0
            for row in included
        )
        if has_accuracy
        else ()
    )
    ndcg_values = (
        tuple(
            row.ndcg_at_10
            if row.status == "completed" and row.ndcg_at_10 is not None
            else 0.0
            for row in included
        )
        if has_ndcg
        else ()
    )
    input_tokens = sum(row.tokens.input for row in queries)
    cached_input_tokens = sum(row.tokens.cached_input for row in queries)
    output_tokens = sum(row.tokens.output for row in queries)
    return RunAggregates(
        query_count=len(queries),
        included_count=len(included),
        excluded_count=len(queries) - len(included),
        completed_count=sum(row.status == "completed" for row in included),
        failed_count=sum(row.status == "failed" for row in included),
        cancelled_count=sum(row.status == "cancelled" for row in included),
        timed_out_count=sum(row.status == "timed_out" for row in included),
        missing_count=sum(row.status == "missing" for row in included),
        accuracy=(sum(accuracy_values) / len(accuracy_values) if accuracy_values else None),
        mean_ndcg_at_10=(sum(ndcg_values) / len(ndcg_values) if ndcg_values else None),
        agent_operations=sum(row.operations.agent for row in queries),
        judge_operations=sum(row.operations.judge for row in queries),
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + cached_input_tokens + output_tokens,
        cost_usd=sum(row.cost_usd for row in queries),
    )


def _parse_aggregates(value: object) -> RunAggregates:
    item = _require_exact_mapping(value, _AGGREGATE_KEYS, "aggregate")
    return RunAggregates(
        query_count=_require_count(item["query_count"], "query count"),
        included_count=_require_count(item["included_count"], "included count"),
        excluded_count=_require_count(item["excluded_count"], "excluded count"),
        completed_count=_require_count(item["completed_count"], "completed count"),
        failed_count=_require_count(item["failed_count"], "failed count"),
        cancelled_count=_require_count(item["cancelled_count"], "cancelled count"),
        timed_out_count=_require_count(item["timed_out_count"], "timed-out count"),
        missing_count=_require_count(item["missing_count"], "missing count"),
        accuracy=_require_optional_unit(item["accuracy"], "accuracy"),
        mean_ndcg_at_10=_require_optional_unit(
            item["mean_ndcg_at_10"], "mean NDCG@10"
        ),
        agent_operations=_require_count(item["agent_operations"], "agent operations"),
        judge_operations=_require_count(item["judge_operations"], "Judge operations"),
        input_tokens=_require_count(item["input_tokens"], "input tokens"),
        cached_input_tokens=_require_count(
            item["cached_input_tokens"], "cached input tokens"
        ),
        output_tokens=_require_count(item["output_tokens"], "output tokens"),
        total_tokens=_require_count(item["total_tokens"], "total tokens"),
        cost_usd=_require_finite(item["cost_usd"], "aggregate cost", minimum=0.0),
    )


def _same_aggregates(left: RunAggregates, right: RunAggregates) -> bool:
    for name in _AGGREGATE_KEYS:
        a, b = getattr(left, name), getattr(right, name)
        if isinstance(a, float) or isinstance(b, float):
            if a is None or b is None or not math.isclose(float(a), float(b), abs_tol=1e-12):
                return a is b
        elif a != b:
            return False
    return True


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    product: str
    implementation_sha256: str
    profile_id: str
    profile_sha256: str
    runtime: str
    dataset_id: str
    selection_id: str
    selection_sha256: str
    effective_config_sha256: str
    product_effective_config_sha256: str
    metric_contract_sha256: str
    metric_identities: tuple[str, ...]
    queries: tuple[QueryEvidence, ...]
    aggregates: RunAggregates
    identity_sha256: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.run_id, "run ID"),
            (self.profile_id, "profile ID"),
            (self.runtime, "runtime ID"),
            (self.dataset_id, "dataset ID"),
            (self.selection_id, "selection ID"),
        ):
            _require_public_id(value, label)
        if type(self.product) is not str or self.product not in _PRODUCTS:
            raise ValueError("DCI reproduction product role is invalid")
        for value, label in (
            (self.implementation_sha256, "implementation digest"),
            (self.profile_sha256, "profile digest"),
            (self.selection_sha256, "selection digest"),
            (self.effective_config_sha256, "effective configuration digest"),
            (
                self.product_effective_config_sha256,
                "product effective configuration digest",
            ),
            (self.metric_contract_sha256, "metric contract digest"),
            (self.identity_sha256, "run identity"),
        ):
            _require_sha256(value, label)
        if (
            type(self.metric_identities) is not tuple
            or not self.metric_identities
            or not set(self.metric_identities).issubset(_METRIC_IDENTITIES)
            or len(set(self.metric_identities)) != len(self.metric_identities)
            or type(self.queries) is not tuple
            or not self.queries
            or any(type(row) is not QueryEvidence for row in self.queries)
            or type(self.aggregates) is not RunAggregates
        ):
            raise ValueError("DCI reproduction run manifest values are invalid")
        for row in self.queries:
            row.__post_init__()
        self.aggregates.__post_init__()
        profile_ids = experiment_profile_ids()
        if self.profile_id not in profile_ids:
            raise ValueError("DCI reproduction profile ID is invalid")
        expected_runtime = "pi" if self.profile_id.endswith("/pi") else "claude-code"
        if self.runtime != expected_runtime:
            raise ValueError("DCI reproduction runtime/profile identity is invalid")
        if self.product == "original-dci" and self.runtime != "pi":
            raise ValueError("Original DCI reproduction runtime is invalid")
        if self.metric_contract_sha256 != reproduction_metric_contract_sha256(
            self.profile_id
        ):
            raise ValueError("DCI reproduction metric contract identity is invalid")
        query_ids = tuple(row.query_id for row in self.queries)
        if query_ids != tuple(sorted(query_ids)) or len(set(query_ids)) != len(query_ids):
            raise ValueError("DCI reproduction query IDs are invalid")
        for row in self.queries:
            if row.status != "completed" or row.exclusion_reason is not None:
                continue
            if _ACCURACY_METRIC in self.metric_identities and row.judge_verdict is None:
                raise ValueError("DCI reproduction declared accuracy evidence is missing")
            if _NDCG_METRIC in self.metric_identities and row.ndcg_at_10 is None:
                raise ValueError("DCI reproduction declared NDCG evidence is missing")
        allowed_reasons = set(
            _metric_contract(self.profile_id)["allowed_exclusion_reasons"]
        )
        if any(
            row.exclusion_reason is not None
            and row.exclusion_reason not in allowed_reasons
            for row in self.queries
        ):
            raise ValueError("DCI reproduction exclusion reason is not allowed")
        if not _same_aggregates(
            self.aggregates,
            _computed_aggregates(
                self.queries, self.metric_identities, self.profile_id
            ),
        ):
            raise ValueError("DCI reproduction aggregates are inconsistent")
        unsigned = self._raw_dict()
        unsigned.pop("identity_sha256")
        if self.identity_sha256 != canonical_sha256(unsigned):
            raise ValueError("DCI reproduction run identity is invalid")

    @classmethod
    def from_mapping(cls, value: object) -> "RunManifest":
        _reject_body_fields(value)
        item = _require_exact_mapping(value, _MANIFEST_KEYS, "run manifest")
        if item["schema"] != RUN_MANIFEST_SCHEMA:
            raise ValueError("DCI reproduction run schema is invalid")
        supplied_identity = _require_sha256(item["identity_sha256"], "run identity")
        unsigned = {key: data for key, data in item.items() if key != "identity_sha256"}
        if supplied_identity != canonical_sha256(unsigned):
            raise ValueError("DCI reproduction run identity is invalid")
        raw_metrics = item["metric_identities"]
        if (
            type(raw_metrics) is not list
            or not raw_metrics
            or any(type(metric) is not str or _PUBLIC_ID.fullmatch(metric) is None for metric in raw_metrics)
            or len(set(raw_metrics)) != len(raw_metrics)
            or not set(raw_metrics).issubset(_METRIC_IDENTITIES)
        ):
            raise ValueError("DCI reproduction metric identities are invalid")
        raw_queries = item["queries"]
        if type(raw_queries) is not list or not raw_queries:
            raise ValueError("DCI reproduction queries are invalid")
        queries = tuple(QueryEvidence.from_mapping(row) for row in raw_queries)
        query_ids = tuple(row.query_id for row in queries)
        if query_ids != tuple(sorted(query_ids)) or len(set(query_ids)) != len(query_ids):
            raise ValueError("DCI reproduction query IDs are invalid")
        for row in queries:
            if row.status != "completed" or row.exclusion_reason is not None:
                continue
            if _ACCURACY_METRIC in raw_metrics and row.judge_verdict is None:
                raise ValueError("DCI reproduction declared accuracy evidence is missing")
            if _NDCG_METRIC in raw_metrics and row.ndcg_at_10 is None:
                raise ValueError("DCI reproduction declared NDCG evidence is missing")
        aggregates = _parse_aggregates(item["aggregates"])
        expected = _computed_aggregates(
            queries, tuple(raw_metrics), item["profile_id"]
        )
        if not _same_aggregates(aggregates, expected):
            raise ValueError("DCI reproduction aggregates are inconsistent")
        return cls(
            run_id=_require_public_id(item["run_id"], "run ID"),
            product=item["product"],
            implementation_sha256=_require_sha256(
                item["implementation_sha256"], "implementation digest"
            ),
            profile_id=_require_public_id(item["profile_id"], "profile ID"),
            profile_sha256=_require_sha256(item["profile_sha256"], "profile digest"),
            runtime=_require_public_id(item["runtime"], "runtime ID"),
            dataset_id=_require_public_id(item["dataset_id"], "dataset ID"),
            selection_id=_require_public_id(item["selection_id"], "selection ID"),
            selection_sha256=_require_sha256(
                item["selection_sha256"], "selection digest"
            ),
            effective_config_sha256=_require_sha256(
                item["effective_config_sha256"], "effective configuration digest"
            ),
            product_effective_config_sha256=_require_sha256(
                item["product_effective_config_sha256"],
                "product effective configuration digest",
            ),
            metric_contract_sha256=_require_sha256(
                item["metric_contract_sha256"], "metric contract digest"
            ),
            metric_identities=tuple(raw_metrics),
            queries=queries,
            aggregates=aggregates,
            identity_sha256=supplied_identity,
        )

    def _raw_dict(self) -> dict[str, object]:
        return {
            "schema": RUN_MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "product": self.product,
            "implementation_sha256": self.implementation_sha256,
            "profile_id": self.profile_id,
            "profile_sha256": self.profile_sha256,
            "runtime": self.runtime,
            "dataset_id": self.dataset_id,
            "selection_id": self.selection_id,
            "selection_sha256": self.selection_sha256,
            "effective_config_sha256": self.effective_config_sha256,
            "product_effective_config_sha256": self.product_effective_config_sha256,
            "metric_contract_sha256": self.metric_contract_sha256,
            "metric_identities": list(self.metric_identities),
            "queries": [row.to_dict() for row in self.queries],
            "aggregates": self.aggregates.to_dict(),
            "identity_sha256": self.identity_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return self._raw_dict()


def load_run_manifest(path: Path) -> RunManifest:
    """Load one exact, duplicate-key-free, body-free reproduction manifest."""

    source = Path(path)
    try:
        metadata = source.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("DCI reproduction manifest path is invalid")
        payload = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("DCI reproduction manifest is invalid") from None
    return RunManifest.from_mapping(payload)


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float

    def __post_init__(self) -> None:
        lower = _require_finite(self.lower, "confidence lower bound")
        upper = _require_finite(self.upper, "confidence upper bound")
        if lower > upper:
            raise ValueError("DCI reproduction confidence interval is invalid")

    def to_dict(self) -> dict[str, float]:
        self.__post_init__()
        return {"lower": self.lower, "upper": self.upper}


@dataclass(frozen=True, slots=True)
class EstimatorEvidence:
    name: str
    seed: int
    resamples: int
    sample_sha256: str

    def __post_init__(self) -> None:
        if (
            self.name not in {ESTIMATOR_NAME, TARGET_ESTIMATOR_NAME}
            or type(self.seed) is not int
            or self.seed != ESTIMATOR_SEED
            or type(self.resamples) is not int
            or self.resamples != ESTIMATOR_RESAMPLES
        ):
            raise ValueError("DCI reproduction estimator identity is invalid")
        _require_sha256(self.sample_sha256, "estimator sample digest")

    @property
    def query_set_sha256(self) -> str:
        """Backward-compatible name for the now value-bound sample digest."""

        return self.sample_sha256

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "name": self.name,
            "seed": self.seed,
            "resamples": self.resamples,
            "sample_sha256": self.sample_sha256,
        }


@dataclass(frozen=True, slots=True)
class MetricComparison:
    baseline: float
    candidate: float
    delta: float
    confidence_interval: ConfidenceInterval
    margin: float
    accepted: bool
    estimator: EstimatorEvidence

    def __post_init__(self) -> None:
        baseline = _require_optional_unit(self.baseline, "baseline metric")
        candidate = _require_optional_unit(self.candidate, "candidate metric")
        delta = _require_finite(self.delta, "metric delta")
        _require_finite(self.margin, "non-inferiority margin")
        if (
            baseline is None
            or candidate is None
            or not math.isclose(candidate - baseline, delta, abs_tol=1e-12)
            or type(self.confidence_interval) is not ConfidenceInterval
            or type(self.accepted) is not bool
            or type(self.estimator) is not EstimatorEvidence
            or self.accepted
            is not (self.confidence_interval.lower >= self.margin)
        ):
            raise ValueError("DCI reproduction metric comparison is invalid")
        self.confidence_interval.__post_init__()
        self.estimator.__post_init__()

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
            "confidence_interval": self.confidence_interval.to_dict(),
            "margin": self.margin,
            "accepted": self.accepted,
            "estimator": self.estimator.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ComparisonTotals:
    completion_rate: float
    failure_rate: float
    agent_operations: int
    judge_operations: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float

    def __post_init__(self) -> None:
        completion = _require_optional_unit(self.completion_rate, "completion rate")
        failure = _require_optional_unit(self.failure_rate, "failure rate")
        if completion is None or failure is None or not (
            math.isclose(completion + failure, 1.0, abs_tol=1e-12)
            or (completion == 0.0 and failure == 0.0)
        ):
            raise ValueError("DCI reproduction completion rates are invalid")
        for name in (
            "agent_operations",
            "judge_operations",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "total_tokens",
        ):
            _require_count(getattr(self, name), name.replace("_", " "))
        if self.total_tokens != self.input_tokens + self.cached_input_tokens + self.output_tokens:
            raise ValueError("DCI reproduction comparison token totals are inconsistent")
        _require_finite(self.cost_usd, "comparison cost", minimum=0.0)

    @classmethod
    def from_manifest(cls, manifest: RunManifest) -> "ComparisonTotals":
        aggregates = manifest.aggregates
        denominator = aggregates.included_count
        completed = aggregates.completed_count
        return cls(
            completion_rate=completed / denominator if denominator else 0.0,
            failure_rate=(denominator - completed) / denominator if denominator else 0.0,
            agent_operations=aggregates.agent_operations,
            judge_operations=aggregates.judge_operations,
            input_tokens=aggregates.input_tokens,
            cached_input_tokens=aggregates.cached_input_tokens,
            output_tokens=aggregates.output_tokens,
            total_tokens=aggregates.total_tokens,
            cost_usd=aggregates.cost_usd,
        )

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "completion_rate": self.completion_rate,
            "failure_rate": self.failure_rate,
            "agent_operations": self.agent_operations,
            "judge_operations": self.judge_operations,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }


@dataclass(frozen=True, slots=True)
class _ComparedQueryEvidence:
    status: str
    judge_verdict: bool | None
    ndcg_at_10: float | None
    evidence_sha256: str
    exclusion_reason: str | None

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("DCI comparison query status is invalid")
        if self.judge_verdict is not None and type(self.judge_verdict) is not bool:
            raise ValueError("DCI comparison Judge verdict is invalid")
        _require_optional_unit(self.ndcg_at_10, "comparison NDCG@10")
        _require_sha256(self.evidence_sha256, "comparison evidence digest")
        if self.exclusion_reason is not None and (
            type(self.exclusion_reason) is not str
            or _VERSIONED_REASON.fullmatch(self.exclusion_reason) is None
        ):
            raise ValueError("DCI comparison exclusion reason is invalid")

    @classmethod
    def from_query(cls, row: QueryEvidence) -> "_ComparedQueryEvidence":
        return cls(
            status=row.status,
            judge_verdict=row.judge_verdict,
            ndcg_at_10=row.ndcg_at_10,
            evidence_sha256=row.evidence_sha256,
            exclusion_reason=row.exclusion_reason,
        )

    def to_pair_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "status": self.status,
            "judge_verdict": self.judge_verdict,
            "ndcg_at_10": self.ndcg_at_10,
            "evidence_sha256": self.evidence_sha256,
        }

    def to_exclusion_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {**self.to_pair_dict(), "exclusion_reason": self.exclusion_reason}


@dataclass(frozen=True, slots=True)
class _MatchedPairEvidence:
    query_id: str
    baseline: _ComparedQueryEvidence
    candidate: _ComparedQueryEvidence

    def __post_init__(self) -> None:
        _require_public_id(self.query_id, "matched query ID")
        if (
            type(self.baseline) is not _ComparedQueryEvidence
            or type(self.candidate) is not _ComparedQueryEvidence
            or self.baseline.exclusion_reason is not None
            or self.candidate.exclusion_reason is not None
        ):
            raise ValueError("DCI matched pair evidence is invalid")

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "query_id": self.query_id,
            "baseline": self.baseline.to_pair_dict(),
            "candidate": self.candidate.to_pair_dict(),
        }


@dataclass(frozen=True, slots=True)
class _TargetSampleEvidence:
    query_id: str
    candidate: _ComparedQueryEvidence

    def __post_init__(self) -> None:
        _require_public_id(self.query_id, "target sample query ID")
        if (
            type(self.candidate) is not _ComparedQueryEvidence
            or self.candidate.exclusion_reason is not None
        ):
            raise ValueError("DCI target sample evidence is invalid")

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "query_id": self.query_id,
            "candidate": self.candidate.to_pair_dict(),
        }


@dataclass(frozen=True, slots=True)
class _ExclusionEvidence:
    query_id: str
    baseline: _ComparedQueryEvidence
    candidate: _ComparedQueryEvidence

    def __post_init__(self) -> None:
        _require_public_id(self.query_id, "excluded query ID")
        if (
            type(self.baseline) is not _ComparedQueryEvidence
            or type(self.candidate) is not _ComparedQueryEvidence
            or self.baseline.exclusion_reason is None
            or self.candidate.exclusion_reason is None
        ):
            raise ValueError("DCI exclusion evidence is invalid")

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return {
            "query_id": self.query_id,
            "baseline": self.baseline.to_exclusion_dict(),
            "candidate": self.candidate.to_exclusion_dict(),
        }


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    comparison_kind: str
    profile_id: str
    profile_sha256: str
    profile_provider: str | None
    profile_model: str | None
    runtime: str
    dataset_id: str
    selection_id: str
    selection_sha256: str
    effective_config_sha256: str
    metric_contract_sha256: str
    metric_identities: tuple[str, ...]
    baseline_product: str | None
    baseline_implementation_sha256: str | None
    baseline_product_effective_config_sha256: str | None
    candidate_product: str
    candidate_implementation_sha256: str
    candidate_product_effective_config_sha256: str
    baseline_run_sha256: str | None
    candidate_run_sha256: str
    target_identity: str | None
    target_sha256: str | None
    target_samples: tuple[_TargetSampleEvidence, ...]
    pairs: tuple[_MatchedPairEvidence, ...]
    exclusions: tuple[_ExclusionEvidence, ...]
    baseline: ComparisonTotals | None
    candidate: ComparisonTotals
    metrics: Mapping[str, MetricComparison]
    accepted: bool | None
    identity_sha256: str

    def __post_init__(self) -> None:
        copied_metrics = MappingProxyType(dict(self.metrics))
        object.__setattr__(self, "metrics", copied_metrics)
        self._validate()

    @classmethod
    def from_mapping(cls, value: object) -> "ComparisonReport":
        _reject_body_fields(value)
        item = _require_exact_mapping(value, _COMPARISON_KEYS, "comparison report")
        if item["schema"] != COMPARISON_SCHEMA:
            raise ValueError("DCI reproduction comparison schema is invalid")
        identity = _require_sha256(item["identity_sha256"], "comparison identity")
        unsigned = {key: data for key, data in item.items() if key != "identity_sha256"}
        if identity != canonical_sha256(unsigned):
            raise ValueError("DCI reproduction comparison identity is invalid")
        raw_pairs = item["pairs"]
        raw_target_samples = item["target_samples"]
        raw_exclusions = item["exclusions"]
        if (
            type(raw_pairs) is not list
            or type(raw_target_samples) is not list
            or type(raw_exclusions) is not list
        ):
            raise ValueError("DCI reproduction comparison evidence is invalid")
        pairs = tuple(_parse_matched_pair(pair) for pair in raw_pairs)
        target_samples = tuple(
            _parse_target_sample(sample) for sample in raw_target_samples
        )
        exclusions = tuple(_parse_exclusion(row) for row in raw_exclusions)
        if item["pair_ids"] != [pair.query_id for pair in pairs] or item[
            "exclusion_ids"
        ] != [row.query_id for row in exclusions]:
            raise ValueError("DCI reproduction comparison query IDs are invalid")
        if item["target_sample_ids"] != [
            sample.query_id for sample in target_samples
        ]:
            raise ValueError("DCI reproduction target sample IDs are invalid")
        raw_metrics = item["metrics"]
        if type(raw_metrics) is not dict or set(raw_metrics) - {
            "accuracy",
            "ndcg_at_10",
        }:
            raise ValueError("DCI reproduction comparison metrics are invalid")
        metrics = {name: _parse_metric(metric) for name, metric in raw_metrics.items()}
        baseline = (
            None if item["baseline"] is None else _parse_comparison_totals(item["baseline"])
        )
        return cls(
            comparison_kind=item["comparison_kind"],
            profile_id=item["profile_id"],
            profile_sha256=item["profile_sha256"],
            profile_provider=item["profile_provider"],
            profile_model=item["profile_model"],
            runtime=item["runtime"],
            dataset_id=item["dataset_id"],
            selection_id=item["selection_id"],
            selection_sha256=item["selection_sha256"],
            effective_config_sha256=item["effective_config_sha256"],
            metric_contract_sha256=item["metric_contract_sha256"],
            metric_identities=tuple(item["metric_identities"])
            if type(item["metric_identities"]) is list
            else (),
            baseline_product=item["baseline_product"],
            baseline_implementation_sha256=item["baseline_implementation_sha256"],
            baseline_product_effective_config_sha256=item[
                "baseline_product_effective_config_sha256"
            ],
            candidate_product=item["candidate_product"],
            candidate_implementation_sha256=item["candidate_implementation_sha256"],
            candidate_product_effective_config_sha256=item[
                "candidate_product_effective_config_sha256"
            ],
            baseline_run_sha256=item["baseline_run_sha256"],
            candidate_run_sha256=item["candidate_run_sha256"],
            target_identity=item["target_identity"],
            target_sha256=item["target_sha256"],
            target_samples=target_samples,
            pairs=pairs,
            exclusions=exclusions,
            baseline=baseline,
            candidate=_parse_comparison_totals(item["candidate"]),
            metrics=metrics,
            accepted=item["accepted"],
            identity_sha256=identity,
        )

    @property
    def pair_ids(self) -> tuple[str, ...]:
        return tuple(pair.query_id for pair in self.pairs)

    @property
    def exclusion_ids(self) -> tuple[str, ...]:
        return tuple(exclusion.query_id for exclusion in self.exclusions)

    @property
    def target_sample_ids(self) -> tuple[str, ...]:
        return tuple(sample.query_id for sample in self.target_samples)

    def _validate(self) -> None:
        if self.comparison_kind not in {"source-parity", "target-comparison"}:
            raise ValueError("DCI reproduction comparison kind is invalid")
        for value, label in (
            (self.profile_id, "comparison profile ID"),
            (self.runtime, "comparison runtime"),
            (self.dataset_id, "comparison dataset ID"),
            (self.selection_id, "comparison selection ID"),
            (self.candidate_product, "candidate product"),
        ):
            _require_public_id(value, label)
        for value, label in (
            (self.profile_provider, "comparison profile provider"),
            (self.profile_model, "comparison profile model"),
        ):
            if value is not None:
                _require_public_id(value, label)
        for value, label in (
            (self.profile_sha256, "comparison profile digest"),
            (self.selection_sha256, "comparison selection digest"),
            (self.effective_config_sha256, "normalized experiment digest"),
            (self.metric_contract_sha256, "metric contract digest"),
            (self.candidate_implementation_sha256, "candidate implementation digest"),
            (
                self.candidate_product_effective_config_sha256,
                "candidate product configuration digest",
            ),
            (self.candidate_run_sha256, "candidate run digest"),
            (self.identity_sha256, "comparison identity"),
        ):
            _require_sha256(value, label)
        if (
            self.candidate_product != "asterion-dci"
            or self.metric_contract_sha256
            != reproduction_metric_contract_sha256(self.profile_id)
            or type(self.candidate) is not ComparisonTotals
            or type(self.target_samples) is not tuple
            or any(
                type(sample) is not _TargetSampleEvidence
                for sample in self.target_samples
            )
            or type(self.pairs) is not tuple
            or type(self.exclusions) is not tuple
            or any(type(pair) is not _MatchedPairEvidence for pair in self.pairs)
            or any(type(item) is not _ExclusionEvidence for item in self.exclusions)
            or set(self.metrics) - {"accuracy", "ndcg_at_10"}
            or any(type(metric) is not MetricComparison for metric in self.metrics.values())
            or type(self.metric_identities) is not tuple
        ):
            raise ValueError("DCI reproduction comparison values are invalid")
        profile = _resolve_report_profile(self)
        expected_metric_identities, expected_metric_names = _expected_report_metrics(
            profile, self.dataset_id
        )
        if (
            self.profile_sha256 != _profile_digest(profile)
            or self.profile_provider != profile.provider
            or self.profile_model != profile.model
            or self.runtime != profile.runtime
            or self.metric_identities != expected_metric_identities
        ):
            raise ValueError("DCI reproduction comparison profile contract drifted")
        pair_ids = self.pair_ids
        target_sample_ids = self.target_sample_ids
        exclusion_ids = self.exclusion_ids
        if (
            pair_ids != tuple(sorted(pair_ids))
            or target_sample_ids != tuple(sorted(target_sample_ids))
            or exclusion_ids != tuple(sorted(exclusion_ids))
            or len(set(pair_ids)) != len(pair_ids)
            or len(set(target_sample_ids)) != len(target_sample_ids)
            or len(set(exclusion_ids)) != len(exclusion_ids)
            or (set(pair_ids) | set(target_sample_ids)) & set(exclusion_ids)
            or set(pair_ids) & set(target_sample_ids)
        ):
            raise ValueError("DCI reproduction comparison query evidence is invalid")
        if self.comparison_kind == "source-parity":
            if (
                self.baseline_product != "original-dci"
                or self.baseline_implementation_sha256 is None
                or self.baseline_product_effective_config_sha256 is None
                or self.baseline_run_sha256 is None
                or self.baseline_run_sha256 == self.candidate_run_sha256
                or self.target_identity is not None
                or self.target_sha256 is not None
                or self.target_samples
                or type(self.baseline) is not ComparisonTotals
                or not self.pairs
                or not self.metrics
                or type(self.accepted) is not bool
                or self.accepted is not all(metric.accepted for metric in self.metrics.values())
            ):
                raise ValueError("DCI source-parity comparison is invalid")
            for value, label in (
                (self.baseline_implementation_sha256, "baseline implementation digest"),
                (
                    self.baseline_product_effective_config_sha256,
                    "baseline product configuration digest",
                ),
                (self.baseline_run_sha256, "baseline run digest"),
            ):
                _require_sha256(value, label)
            _validate_report_evidence(
                self.pairs, self.exclusions, self.metric_identities, profile.profile_id
            )
            expected_metrics = _recompute_metrics(self.pairs, expected_metric_names, profile)
            if (
                dict(self.metrics) != expected_metrics
                or self.accepted
                is not all(metric.accepted for metric in expected_metrics.values())
            ):
                raise ValueError("DCI reproduction comparison metrics are inconsistent")
        else:
            if (
                self.baseline_product is not None
                or self.baseline_implementation_sha256 is not None
                or self.baseline_product_effective_config_sha256 is not None
                or self.baseline_run_sha256 is not None
                or self.baseline is not None
                or self.exclusions
                or type(self.target_identity) is not str
            ):
                raise ValueError("DCI target comparison is invalid")
            _require_public_id(self.target_identity, "target identity")
            if profile.comparison.get("published_target") is not None:
                _validate_published_target_selection(
                    profile,
                    self.dataset_id,
                    self.selection_id,
                    self.selection_sha256,
                    tuple(sample.query_id for sample in self.target_samples)
                    if _is_published_target_scope(self.selection_id)
                    else None,
                    len(self.target_samples)
                    if _is_published_target_scope(self.selection_id)
                    else None,
                )
                target = _published_target(profile.profile_id)
                target_sha256 = canonical_sha256(dict(target))
                reported_main_scope = _is_published_target_scope(self.selection_id)
                expected_metrics = (
                    _recompute_target_metrics(
                        self.target_samples,
                        expected_metric_names,
                        target,
                        target_sha256,
                        self.dataset_id,
                    )
                    if reported_main_scope
                    else {}
                )
                if self.target_identity != target["target_id"] or self.target_sha256 != target_sha256:
                    raise ValueError("DCI target comparison evidence drifted")
                if reported_main_scope:
                    if (
                        self.pairs
                        or not self.target_samples
                        or dict(self.metrics) != expected_metrics
                        or type(self.accepted) is not bool
                        or self.accepted
                        is not all(
                            metric.accepted for metric in expected_metrics.values()
                        )
                    ):
                        raise ValueError("DCI target comparison evidence drifted")
                    _validate_target_evidence(
                        self.target_samples, self.metric_identities
                    )
                elif (
                    self.pairs
                    or self.target_samples
                    or self.metrics
                    or self.accepted is not None
                ):
                    raise ValueError("DCI unreported target scope evidence drifted")
            elif (
                self.target_identity != profile.comparison.get("target_identity")
                or self.target_sha256 is not None
                or self.target_samples
                or self.pairs
                or self.metrics
                or self.accepted is not None
            ):
                raise ValueError("DCI target comparison identity drifted")
        if self.identity_sha256 != canonical_sha256(self._unsigned_dict()):
            raise ValueError("DCI reproduction comparison identity is invalid")

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "schema": COMPARISON_SCHEMA,
            "comparison_kind": self.comparison_kind,
            "profile_id": self.profile_id,
            "profile_sha256": self.profile_sha256,
            "profile_provider": self.profile_provider,
            "profile_model": self.profile_model,
            "runtime": self.runtime,
            "dataset_id": self.dataset_id,
            "selection_id": self.selection_id,
            "selection_sha256": self.selection_sha256,
            "effective_config_sha256": self.effective_config_sha256,
            "metric_contract_sha256": self.metric_contract_sha256,
            "metric_identities": list(self.metric_identities),
            "baseline_product": self.baseline_product,
            "baseline_implementation_sha256": self.baseline_implementation_sha256,
            "baseline_product_effective_config_sha256": self.baseline_product_effective_config_sha256,
            "candidate_product": self.candidate_product,
            "candidate_implementation_sha256": self.candidate_implementation_sha256,
            "candidate_product_effective_config_sha256": self.candidate_product_effective_config_sha256,
            "baseline_run_sha256": self.baseline_run_sha256,
            "candidate_run_sha256": self.candidate_run_sha256,
            "target_identity": self.target_identity,
            "target_sha256": self.target_sha256,
            "target_sample_ids": list(self.target_sample_ids),
            "target_samples": [sample.to_dict() for sample in self.target_samples],
            "pair_ids": list(self.pair_ids),
            "exclusion_ids": list(self.exclusion_ids),
            "pairs": [pair.to_dict() for pair in self.pairs],
            "exclusions": [item.to_dict() for item in self.exclusions],
            "baseline": None if self.baseline is None else self.baseline.to_dict(),
            "candidate": self.candidate.to_dict(),
            "metrics": {name: metric.to_dict() for name, metric in self.metrics.items()},
            "accepted": self.accepted,
        }

    def to_dict(self) -> dict[str, object]:
        self._validate()
        return {**self._unsigned_dict(), "identity_sha256": self.identity_sha256}

    def to_json_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")


def _parse_comparison_totals(value: object) -> ComparisonTotals:
    keys = {
        "completion_rate",
        "failure_rate",
        "agent_operations",
        "judge_operations",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
    }
    item = _require_exact_mapping(value, keys, "comparison totals")
    return ComparisonTotals(
        completion_rate=_require_finite(item["completion_rate"], "completion rate"),
        failure_rate=_require_finite(item["failure_rate"], "failure rate"),
        agent_operations=_require_count(item["agent_operations"], "agent operations"),
        judge_operations=_require_count(item["judge_operations"], "Judge operations"),
        input_tokens=_require_count(item["input_tokens"], "input tokens"),
        cached_input_tokens=_require_count(
            item["cached_input_tokens"], "cached input tokens"
        ),
        output_tokens=_require_count(item["output_tokens"], "output tokens"),
        total_tokens=_require_count(item["total_tokens"], "total tokens"),
        cost_usd=_require_finite(item["cost_usd"], "comparison cost", minimum=0.0),
    )


def _parse_compared_query(value: object, *, excluded: bool) -> _ComparedQueryEvidence:
    keys = {"status", "judge_verdict", "ndcg_at_10", "evidence_sha256"}
    if excluded:
        keys.add("exclusion_reason")
    item = _require_exact_mapping(value, keys, "compared query")
    return _ComparedQueryEvidence(
        status=item["status"],
        judge_verdict=item["judge_verdict"],
        ndcg_at_10=item["ndcg_at_10"],
        evidence_sha256=item["evidence_sha256"],
        exclusion_reason=item["exclusion_reason"] if excluded else None,
    )


def _parse_matched_pair(value: object) -> _MatchedPairEvidence:
    item = _require_exact_mapping(
        value, {"query_id", "baseline", "candidate"}, "matched pair"
    )
    return _MatchedPairEvidence(
        query_id=item["query_id"],
        baseline=_parse_compared_query(item["baseline"], excluded=False),
        candidate=_parse_compared_query(item["candidate"], excluded=False),
    )


def _parse_target_sample(value: object) -> _TargetSampleEvidence:
    item = _require_exact_mapping(
        value, {"query_id", "candidate"}, "target sample"
    )
    return _TargetSampleEvidence(
        query_id=item["query_id"],
        candidate=_parse_compared_query(item["candidate"], excluded=False),
    )


def _parse_exclusion(value: object) -> _ExclusionEvidence:
    item = _require_exact_mapping(
        value, {"query_id", "baseline", "candidate"}, "exclusion"
    )
    return _ExclusionEvidence(
        query_id=item["query_id"],
        baseline=_parse_compared_query(item["baseline"], excluded=True),
        candidate=_parse_compared_query(item["candidate"], excluded=True),
    )


def _parse_metric(value: object) -> MetricComparison:
    item = _require_exact_mapping(
        value,
        {
            "baseline",
            "candidate",
            "delta",
            "confidence_interval",
            "margin",
            "accepted",
            "estimator",
        },
        "metric comparison",
    )
    interval = _require_exact_mapping(
        item["confidence_interval"], {"lower", "upper"}, "confidence interval"
    )
    estimator = _require_exact_mapping(
        item["estimator"],
        {"name", "seed", "resamples", "sample_sha256"},
        "estimator",
    )
    return MetricComparison(
        baseline=item["baseline"],
        candidate=item["candidate"],
        delta=item["delta"],
        confidence_interval=ConfidenceInterval(
            lower=interval["lower"], upper=interval["upper"]
        ),
        margin=item["margin"],
        accepted=item["accepted"],
        estimator=EstimatorEvidence(
            name=estimator["name"],
            seed=estimator["seed"],
            resamples=estimator["resamples"],
            sample_sha256=estimator["sample_sha256"],
        ),
    )


def _metric_value(row: QueryEvidence | _ComparedQueryEvidence, metric: str) -> float:
    if row.status != "completed":
        return 0.0
    if metric == "accuracy":
        return 1.0 if row.judge_verdict is True else 0.0
    return row.ndcg_at_10 if row.ndcg_at_10 is not None else 0.0


def _paired_metric_values(
    baseline_values: tuple[float, ...],
    candidate_values: tuple[float, ...],
    margin: float,
    sample_sha256: str,
    *,
    estimator_name: str = ESTIMATOR_NAME,
) -> MetricComparison:
    differences = tuple(
        candidate_value - baseline_value
        for baseline_value, candidate_value in zip(
            baseline_values, candidate_values, strict=True
        )
    )
    count = len(differences)
    if not count:
        raise ValueError("DCI reproduction comparison has no matched queries")
    rng = random.Random(ESTIMATOR_SEED)
    estimates = [
        sum(rng.choices(differences, k=count)) / count
        for _ in range(ESTIMATOR_RESAMPLES)
    ]
    estimates.sort()
    lower = estimates[math.floor(0.025 * (ESTIMATOR_RESAMPLES - 1))]
    upper = estimates[math.ceil(0.975 * (ESTIMATOR_RESAMPLES - 1))]
    baseline_mean = sum(baseline_values) / count
    candidate_mean = sum(candidate_values) / count
    delta = candidate_mean - baseline_mean
    return MetricComparison(
        baseline=baseline_mean,
        candidate=candidate_mean,
        delta=delta,
        confidence_interval=ConfidenceInterval(lower=lower, upper=upper),
        margin=margin,
        accepted=lower >= margin,
        estimator=EstimatorEvidence(
            name=estimator_name,
            seed=ESTIMATOR_SEED,
            resamples=ESTIMATOR_RESAMPLES,
            sample_sha256=sample_sha256,
        ),
    )


def _recompute_metrics(
    pairs: tuple[_MatchedPairEvidence, ...],
    metric_names: tuple[str, ...],
    profile: ExperimentProfile,
) -> dict[str, MetricComparison]:
    """Purely recompute report statistics from retained pair evidence."""

    comparison = dict(profile.comparison)
    margins = {
        "accuracy": _require_finite(
            comparison.get("accuracy_margin"), "accuracy margin"
        ),
        "ndcg_at_10": _require_finite(
            comparison.get("ndcg_margin"), "NDCG margin"
        ),
    }
    if (
        not metric_names
        or len(set(metric_names)) != len(metric_names)
        or set(metric_names) - set(margins)
    ):
        raise ValueError("DCI reproduction comparison metrics are invalid")
    metrics: dict[str, MetricComparison] = {}
    for metric in metric_names:
        sample_sha256 = canonical_sha256(
            {
                "schema": "dci.paired-bootstrap-sample/v1",
                "metric": metric,
                "pairs": [pair.to_dict() for pair in pairs],
            }
        )
        metrics[metric] = _paired_metric_values(
            tuple(_metric_value(pair.baseline, metric) for pair in pairs),
            tuple(_metric_value(pair.candidate, metric) for pair in pairs),
            margins[metric],
            sample_sha256,
        )
    return metrics


def _validate_target_evidence(
    samples: tuple[_TargetSampleEvidence, ...],
    metric_identities: tuple[str, ...],
) -> None:
    has_accuracy = _ACCURACY_METRIC in metric_identities
    has_ndcg = _NDCG_METRIC in metric_identities
    for sample in samples:
        candidate = sample.candidate
        if (
            candidate.exclusion_reason is not None
            or (candidate.status != "completed" and (
                candidate.judge_verdict is not None
                or candidate.ndcg_at_10 is not None
            ))
            or (candidate.status == "completed" and (
                (has_accuracy and type(candidate.judge_verdict) is not bool)
                or (has_ndcg and candidate.ndcg_at_10 is None)
            ))
            or (not has_accuracy and candidate.judge_verdict is not None)
            or (not has_ndcg and candidate.ndcg_at_10 is not None)
        ):
            raise ValueError("DCI target comparison query evidence drifted")


def _recompute_target_metrics(
    samples: tuple[_TargetSampleEvidence, ...],
    metric_names: tuple[str, ...],
    target: Mapping[str, object],
    target_sha256: str,
    dataset_id: str,
) -> dict[str, MetricComparison]:
    dataset_targets = target["dataset_targets"]
    if not samples or type(dataset_targets) is not dict:
        raise ValueError("DCI target comparison has no query evidence")
    metrics: dict[str, MetricComparison] = {}
    for metric in metric_names:
        if dataset_id not in dataset_targets:
            raise ValueError("DCI reproduction dataset target is unavailable")
        target_value = _require_optional_unit(
            dataset_targets[dataset_id], "published dataset target"
        )
        if target_value is None:
            raise ValueError("DCI reproduction dataset target is invalid")
        sample_sha256 = canonical_sha256(
            {
                "schema": "dci.target-bootstrap-sample/v1",
                "metric": metric,
                "target_id": target["target_id"],
                "target_sha256": target_sha256,
                "samples": [sample.to_dict() for sample in samples],
            }
        )
        metrics[metric] = _paired_metric_values(
            tuple(target_value for _ in samples),
            tuple(_metric_value(sample.candidate, metric) for sample in samples),
            0.0,
            sample_sha256,
            estimator_name=TARGET_ESTIMATOR_NAME,
        )
    return metrics


def compare_published_target_aggregates(
    reports: tuple[ComparisonReport, ...],
    profile: ExperimentProfile,
) -> dict[str, MetricComparison]:
    """Assess the paper's macro QA and IR rows from main-result reports."""

    if profile.profile_id != "paper-reference/claude-code":
        raise ValueError("DCI published aggregate profile is invalid")
    target = _published_target(profile.profile_id)
    target_sha256 = canonical_sha256(dict(target))
    by_dataset: dict[str, ComparisonReport] = {}
    for report in reports:
        if report.profile_id != profile.profile_id:
            raise ValueError("DCI published aggregate report set is invalid")
        if not _is_published_target_scope(report.selection_id):
            continue
        if report.target_sha256 != target_sha256 or report.dataset_id in by_dataset:
            raise ValueError("DCI published aggregate report set is invalid")
        by_dataset[report.dataset_id] = report
    dataset_targets = target["dataset_targets"]
    if type(dataset_targets) is not dict:
        raise ValueError("DCI published aggregate target is invalid")
    groups = {
        "qa_accuracy": (
            "accuracy",
            "qa_accuracy",
            tuple(sorted(key for key in dataset_targets if key.startswith("qa."))),
        ),
        "ir_ndcg_at_10": (
            "ndcg_at_10",
            "ir_ndcg_at_10",
            tuple(
                sorted(
                    key
                    for key in dataset_targets
                    if resolve_paper_benchmark(key).mode == "ir"
                )
            ),
        ),
    }
    metrics: dict[str, MetricComparison] = {}
    for aggregate_name, (metric_name, target_name, dataset_ids) in groups.items():
        if not dataset_ids or any(dataset_id not in by_dataset for dataset_id in dataset_ids):
            raise ValueError("DCI published aggregate evidence is incomplete")
        selected_reports = tuple(by_dataset[dataset_id] for dataset_id in dataset_ids)
        if any(metric_name not in report.metrics for report in selected_reports):
            raise ValueError("DCI published aggregate metric evidence is incomplete")
        target_value = _require_optional_unit(
            target[target_name], "published aggregate target"
        )
        if target_value is None:
            raise ValueError("DCI published aggregate target is invalid")
        sample_sha256 = canonical_sha256(
            {
                "schema": "dci.target-aggregate-bootstrap-sample/v1",
                "aggregate": aggregate_name,
                "target_id": target["target_id"],
                "target_sha256": target_sha256,
                "reports": [
                    {
                        "dataset_id": report.dataset_id,
                        "report_sha256": report.identity_sha256,
                        "candidate": report.metrics[metric_name].candidate,
                    }
                    for report in selected_reports
                ],
            }
        )
        metrics[aggregate_name] = _paired_metric_values(
            tuple(target_value for _ in selected_reports),
            tuple(
                report.metrics[metric_name].candidate
                for report in selected_reports
            ),
            0.0,
            sample_sha256,
            estimator_name=TARGET_ESTIMATOR_NAME,
        )
    return metrics


def _profile_digest(profile: ExperimentProfile) -> str:
    return experiment_profile_sha256(
        profile.profile_id,
        invocation_provider=profile.provider
        if profile.profile_id == "current-default/claude-minimax"
        else None,
        invocation_model=profile.model
        if profile.profile_id == "current-default/claude-minimax"
        else None,
    )


def _resolve_report_profile(report: ComparisonReport) -> ExperimentProfile:
    if report.profile_id == "current-default/claude-minimax":
        return resolve_experiment_profile(
            report.profile_id,
            invocation_provider=report.profile_provider,
            invocation_model=report.profile_model,
        )
    return resolve_experiment_profile(report.profile_id)


def _expected_report_metrics(
    profile: ExperimentProfile, dataset_id: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    benchmark = resolve_paper_benchmark(dataset_id)
    mode_metric = {
        "qa": _ACCURACY_METRIC,
        "ir": _NDCG_METRIC,
    }.get(benchmark.mode)
    contract_metrics = tuple(_metric_contract(profile.profile_id)["metric_identities"])
    if (
        mode_metric is None
        or benchmark.metric != mode_metric
        or mode_metric not in profile.metric_identities
        or mode_metric not in contract_metrics
    ):
        raise ValueError("DCI reproduction benchmark metric contract drifted")
    metric_name = "accuracy" if mode_metric == _ACCURACY_METRIC else "ndcg_at_10"
    return (mode_metric,), (metric_name,)


def _validate_report_evidence(
    pairs: tuple[_MatchedPairEvidence, ...],
    exclusions: tuple[_ExclusionEvidence, ...],
    metric_identities: tuple[str, ...],
    profile_id: str,
) -> None:
    contract = _metric_contract(profile_id)
    allowed_reasons = set(contract["allowed_exclusion_reasons"])
    allowed_statuses = set(contract["allowed_exclusion_statuses"])
    for exclusion in exclusions:
        baseline = exclusion.baseline
        candidate = exclusion.candidate
        if (
            baseline.exclusion_reason != candidate.exclusion_reason
            or baseline.exclusion_reason not in allowed_reasons
            or baseline.status not in allowed_statuses
            or candidate.status not in allowed_statuses
        ):
            raise ValueError("DCI reproduction exclusion contract drifted")
    has_accuracy = _ACCURACY_METRIC in metric_identities
    has_ndcg = _NDCG_METRIC in metric_identities
    for pair in pairs:
        for evidence in (pair.baseline, pair.candidate):
            if evidence.status != "completed" and (
                evidence.judge_verdict is not None or evidence.ndcg_at_10 is not None
            ):
                raise ValueError("DCI reproduction failed query evidence drifted")
            if evidence.status == "completed" and (
                (has_accuracy and type(evidence.judge_verdict) is not bool)
                or (has_ndcg and evidence.ndcg_at_10 is None)
            ):
                raise ValueError("DCI reproduction matched metric evidence drifted")
            if (not has_accuracy and evidence.judge_verdict is not None) or (
                not has_ndcg and evidence.ndcg_at_10 is not None
            ):
                raise ValueError("DCI reproduction undeclared metric evidence drifted")
    for exclusion in exclusions:
        for evidence in (exclusion.baseline, exclusion.candidate):
            if evidence.judge_verdict is not None or evidence.ndcg_at_10 is not None:
                raise ValueError("DCI reproduction excluded metric evidence drifted")


def compare_reproduction_runs(
    baseline: RunManifest | None,
    candidate: RunManifest,
    profile: ExperimentProfile,
) -> ComparisonReport:
    """Compare exact matched Pi runs or one Claude run against its target identity."""

    profile_digest = _profile_digest(profile)
    if (
        candidate.profile_id != profile.profile_id
        or candidate.profile_sha256 != profile_digest
        or candidate.metric_contract_sha256
        != reproduction_metric_contract_sha256(profile.profile_id)
        or candidate.product != "asterion-dci"
    ):
        raise ValueError("DCI reproduction profile identity drifted")
    if candidate.runtime != profile.runtime:
        raise ValueError("DCI reproduction runtime identity drifted")
    expected_metric_identities, expected_metric_names = _expected_report_metrics(
        profile, candidate.dataset_id
    )
    if candidate.metric_identities != expected_metric_identities:
        raise ValueError("DCI reproduction benchmark metric identity drifted")
    if profile.runtime == "claude-code":
        if baseline is not None:
            raise ValueError("DCI Claude reproduction has no source parity baseline")
        if any(row.exclusion_reason is not None for row in candidate.queries):
            raise ValueError("DCI target comparison cannot manufacture exclusions")
        target_label = profile.comparison.get("published_target") or profile.comparison.get(
            "target_identity"
        )
        if type(target_label) is not str:
            raise ValueError("DCI Claude reproduction target identity is invalid")
        target: Mapping[str, object] | None = None
        target_sha256: str | None = None
        target_identity = target_label
        target_samples: tuple[_TargetSampleEvidence, ...] = ()
        pairs: tuple[_MatchedPairEvidence, ...] = ()
        metrics: dict[str, MetricComparison] = {}
        accepted: bool | None = None
        if profile.comparison.get("published_target") is not None:
            _validate_published_target_selection(
                profile,
                candidate.dataset_id,
                candidate.selection_id,
                candidate.selection_sha256,
                tuple(row.query_id for row in candidate.queries),
                len(candidate.queries),
            )
            target = _published_target(profile.profile_id)
            target_sha256 = canonical_sha256(dict(target))
            target_identity = str(target["target_id"])
            if _is_published_target_scope(candidate.selection_id):
                target_samples = tuple(
                    _TargetSampleEvidence(
                        query_id=row.query_id,
                        candidate=_ComparedQueryEvidence.from_query(row),
                    )
                    for row in candidate.queries
                )
                metrics = _recompute_target_metrics(
                    target_samples,
                    expected_metric_names,
                    target,
                    target_sha256,
                    candidate.dataset_id,
                )
                accepted = all(metric.accepted for metric in metrics.values())
        candidate_totals = ComparisonTotals.from_manifest(candidate)
        values = dict(
            comparison_kind="target-comparison",
            profile_id=profile.profile_id,
            profile_sha256=profile_digest,
            profile_provider=profile.provider,
            profile_model=profile.model,
            runtime=profile.runtime,
            dataset_id=candidate.dataset_id,
            selection_id=candidate.selection_id,
            selection_sha256=candidate.selection_sha256,
            effective_config_sha256=candidate.effective_config_sha256,
            metric_contract_sha256=candidate.metric_contract_sha256,
            metric_identities=expected_metric_identities,
            baseline_product=None,
            baseline_implementation_sha256=None,
            baseline_product_effective_config_sha256=None,
            candidate_product=candidate.product,
            candidate_implementation_sha256=candidate.implementation_sha256,
            candidate_product_effective_config_sha256=(
                candidate.product_effective_config_sha256
            ),
            baseline_run_sha256=None,
            candidate_run_sha256=candidate.identity_sha256,
            target_identity=target_identity,
            target_sha256=target_sha256,
            target_samples=target_samples,
            pairs=pairs,
            exclusions=(),
            baseline=None,
            candidate=candidate_totals,
            metrics=metrics,
            accepted=accepted,
        )
        unsigned = {
            "schema": COMPARISON_SCHEMA,
            **values,
            "pair_ids": [pair.query_id for pair in pairs],
            "target_sample_ids": [
                sample.query_id for sample in target_samples
            ],
            "exclusion_ids": [],
        }
        unsigned["target_samples"] = [
            sample.to_dict() for sample in target_samples
        ]
        unsigned["pairs"] = [pair.to_dict() for pair in pairs]
        unsigned["exclusions"] = []
        unsigned["baseline"] = None
        unsigned["candidate"] = candidate_totals.to_dict()
        unsigned["metrics"] = {
            name: metric.to_dict() for name, metric in metrics.items()
        }
        return ComparisonReport(
            **values, identity_sha256=canonical_sha256(unsigned)  # type: ignore[arg-type]
        )
    if baseline is None:
        raise ValueError("DCI Pi reproduction requires a source baseline")
    if (
        baseline.product != "original-dci"
        or candidate.product != "asterion-dci"
        or baseline.identity_sha256 == candidate.identity_sha256
    ):
        raise ValueError("DCI reproduction source/candidate roles are invalid")
    identity_fields = (
        "profile_id",
        "profile_sha256",
        "runtime",
        "dataset_id",
        "selection_id",
        "selection_sha256",
        "effective_config_sha256",
        "metric_contract_sha256",
        "metric_identities",
    )
    if any(getattr(baseline, name) != getattr(candidate, name) for name in identity_fields):
        raise ValueError("DCI reproduction experiment identity drifted")
    if baseline.profile_id != profile.profile_id or baseline.profile_sha256 != profile_digest:
        raise ValueError("DCI reproduction profile identity drifted")
    baseline_by_id = {row.query_id: row for row in baseline.queries}
    candidate_by_id = {row.query_id: row for row in candidate.queries}
    all_ids = tuple(sorted(set(baseline_by_id) | set(candidate_by_id)))
    if set(baseline_by_id) != set(candidate_by_id):
        raise ValueError("DCI reproduction matched query IDs drifted")
    exclusion_ids = tuple(
        query_id
        for query_id in all_ids
        if baseline_by_id[query_id].exclusion_reason is not None
        or candidate_by_id[query_id].exclusion_reason is not None
    )
    exclusions: list[_ExclusionEvidence] = []
    metric_contract = _metric_contract(profile.profile_id)
    allowed_reasons = set(metric_contract["allowed_exclusion_reasons"])
    allowed_statuses = set(metric_contract["allowed_exclusion_statuses"])
    for query_id in exclusion_ids:
        baseline_row = baseline_by_id[query_id]
        candidate_row = candidate_by_id[query_id]
        if (
            baseline_row.exclusion_reason != candidate_row.exclusion_reason
            or baseline_row.exclusion_reason not in allowed_reasons
            or baseline_row.status not in allowed_statuses
            or candidate_row.status not in allowed_statuses
        ):
            raise ValueError("DCI reproduction exclusion contract drifted")
        exclusions.append(
            _ExclusionEvidence(
                query_id=query_id,
                baseline=_ComparedQueryEvidence.from_query(baseline_row),
                candidate=_ComparedQueryEvidence.from_query(candidate_row),
            )
        )
    pair_ids = tuple(query_id for query_id in all_ids if query_id not in exclusion_ids)
    pairs = tuple(
        _MatchedPairEvidence(
            query_id=query_id,
            baseline=_ComparedQueryEvidence.from_query(baseline_by_id[query_id]),
            candidate=_ComparedQueryEvidence.from_query(candidate_by_id[query_id]),
        )
        for query_id in pair_ids
    )
    metrics = _recompute_metrics(pairs, expected_metric_names, profile)
    accepted = all(metric.accepted for metric in metrics.values())
    baseline_totals = ComparisonTotals.from_manifest(baseline)
    candidate_totals = ComparisonTotals.from_manifest(candidate)
    values = dict(
        comparison_kind="source-parity",
        profile_id=profile.profile_id,
        profile_sha256=profile_digest,
        profile_provider=profile.provider,
        profile_model=profile.model,
        runtime=profile.runtime,
        dataset_id=candidate.dataset_id,
        selection_id=candidate.selection_id,
        selection_sha256=candidate.selection_sha256,
        effective_config_sha256=candidate.effective_config_sha256,
        metric_contract_sha256=candidate.metric_contract_sha256,
        metric_identities=expected_metric_identities,
        baseline_product=baseline.product,
        baseline_implementation_sha256=baseline.implementation_sha256,
        baseline_product_effective_config_sha256=(
            baseline.product_effective_config_sha256
        ),
        candidate_product=candidate.product,
        candidate_implementation_sha256=candidate.implementation_sha256,
        candidate_product_effective_config_sha256=(
            candidate.product_effective_config_sha256
        ),
        baseline_run_sha256=baseline.identity_sha256,
        candidate_run_sha256=candidate.identity_sha256,
        target_identity=None,
        target_sha256=None,
        target_samples=(),
        pairs=pairs,
        exclusions=tuple(exclusions),
        baseline=baseline_totals,
        candidate=candidate_totals,
        metrics=metrics,
        accepted=accepted,
    )
    unsigned = {
        "schema": COMPARISON_SCHEMA,
        **values,
        "pair_ids": list(pair_ids),
        "target_sample_ids": [],
        "exclusion_ids": list(exclusion_ids),
        "target_samples": [],
        "pairs": [pair.to_dict() for pair in pairs],
        "exclusions": [item.to_dict() for item in exclusions],
        "baseline": baseline_totals.to_dict(),
        "candidate": candidate_totals.to_dict(),
        "metrics": {name: metric.to_dict() for name, metric in metrics.items()},
    }
    return ComparisonReport(
        **values, identity_sha256=canonical_sha256(unsigned)  # type: ignore[arg-type]
    )


def write_comparison_report(path: Path, report: ComparisonReport) -> None:
    """Write a deterministic report beneath a private directory."""

    payload = report.to_json_bytes()
    destination = Path(path)
    parent = destination.parent
    if parent.exists():
        metadata = parent.lstat()
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise ValueError("DCI reproduction report parent is invalid")
    else:
        parent.mkdir(parents=True, mode=0o700)
        os.chmod(parent, 0o700)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise ValueError("DCI reproduction report path is invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def load_comparison_report(path: Path) -> ComparisonReport:
    """Load one exact, duplicate-key-free, body-free comparison report."""

    source = Path(path)
    try:
        metadata = source.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("DCI reproduction comparison path is invalid")
        payload = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("DCI reproduction comparison is invalid") from None
    return ComparisonReport.from_mapping(payload)
